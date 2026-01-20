#backend/app/contracts.py
from __future__ import annotations

import json
from pathlib import Path
from sqlmodel import select, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from .db import get_session
from .models import ModuleContract
from .indexers import pick_indexer
from .utils import sha256_file, resolve_under_root
from .errors import PathValidationError
from .resolve import resolve_spec


CONTRACT_VERSION = 2
MAX_CONTRACT_SYMBOLS = 400
MAX_CONTRACT_IMPORTS = 2000

def get_or_build_contract(project_id: int, project_root: Path, rel_path: str) -> dict:
    project_root = project_root.resolve()
    try:
        p, rel_norm = resolve_under_root(project_root, rel_path)
    except PathValidationError as e:
        raise FileNotFoundError("Path escapes project root") from e
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"File not found: {rel_path}")

    file_hash = sha256_file(p)
    with get_session() as s:
        existing = s.exec(
            select(ModuleContract)
            .where(
                ModuleContract.project_id == project_id,
                ModuleContract.path.in_([rel_norm, rel_path]),
            )
            .order_by(ModuleContract.id.desc())
        ).first()
        if existing and existing.file_hash == file_hash:
            try:
                data = json.loads(existing.contract_json)
            except Exception:
                data = None
            if isinstance(data, dict):
                ver = data.get("version")
                try:
                    ver_i = int(ver) if ver is not None else 1
                except Exception:
                    ver_i = 1
                if ver_i >= CONTRACT_VERSION:
                    if data.get("path") != rel_norm:
                        data["path"] = rel_norm
                    if existing.path != rel_norm:
                        existing.path = rel_norm
                        existing.contract_json = json.dumps(data, ensure_ascii=False)
                        s.add(existing)
                        if rel_path != rel_norm:
                            s.exec(delete(ModuleContract).where(
                                ModuleContract.project_id == project_id,
                                ModuleContract.path == rel_path,
                            ))
                        s.commit()
                    return data

    text = p.read_text(encoding="utf-8", errors="replace")
    idx = pick_indexer(rel_norm)
    exports = idx.parse_exports(p, text)
    exports_set = {str(x) for x in exports if isinstance(x, str)}

    imports_raw = idx.parse_imports(p, text)
    imports: list[dict] = []
    for imp in (imports_raw or [])[:MAX_CONTRACT_IMPORTS]:
        spec = str(getattr(imp, "spec", "") or "")
        if not spec:
            continue
        kind = str(getattr(imp, "kind", "") or "import")
        raw = str(getattr(imp, "raw", "") or "")
        resolved = None
        if kind != "runtime_dynamic":
            try:
                resolved = resolve_spec(project_root, rel_norm, spec)
            except Exception:
                resolved = None
        imports.append({"spec": spec, "kind": kind, "raw": raw, "resolved_path": resolved})

    symbols_raw = []
    try:
        symbols_raw = idx.parse_symbols(p, text)
    except Exception:
        symbols_raw = []
    symbols: list[dict] = []
    for sym in (symbols_raw or [])[:MAX_CONTRACT_SYMBOLS]:
        name = str(getattr(sym, "name", "") or "")
        if not name:
            continue
        symbols.append(
            {
                "name": name,
                "kind": str(getattr(sym, "kind", "") or ""),
                "signature": str(getattr(sym, "signature", "") or ""),
                "doc": str(getattr(sym, "doc", "") or ""),
                "start_line": int(getattr(sym, "start_line", 0) or 0),
                "end_line": int(getattr(sym, "end_line", 0) or 0),
                "exported": bool(name in exports_set),
            }
        )

    module_doc = ""
    parse_module_doc = getattr(idx, "parse_module_doc", None)
    if callable(parse_module_doc):
        try:
            module_doc = str(parse_module_doc(p, text) or "").strip()
        except Exception:
            module_doc = ""

    contract = {
        "version": CONTRACT_VERSION,
        "path": rel_norm,
        "language": idx.language(),
        "exports": exports,
        "imports": imports,
        "symbols": symbols,
        "module_doc": module_doc,
        "notes": "",
    }

    with get_session() as s:
        cj = json.dumps(contract, ensure_ascii=False)
        stmt = sqlite_insert(ModuleContract).values(
            project_id=project_id,
            path=rel_norm,
            file_hash=file_hash,
            contract_json=cj,
        ).on_conflict_do_update(
            index_elements=["project_id", "path"],
            set_={
                "file_hash": file_hash,
                "contract_json": cj,
            },
        )
        s.exec(stmt)
        if rel_path != rel_norm:
            s.exec(delete(ModuleContract).where(
                ModuleContract.project_id == project_id,
                ModuleContract.path == rel_path,
            ))
        s.commit()

    return contract
