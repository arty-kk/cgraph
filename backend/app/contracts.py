# backend/app/contracts.py
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import delete, select

from .errors import PathValidationError
from .infra.fs_runtime import run_fs_io_async
from .indexers import pick_indexer
from .models import ModuleContract
from .resolve import resolve_spec
from .utils import resolve_under_root, sha256_file

CONTRACT_VERSION = 2
MAX_CONTRACT_SYMBOLS = 400
MAX_CONTRACT_IMPORTS = 2000


def _build_contract_payload(project_root: Path, rel_norm: str, p: Path, file_text: str) -> dict:
    idx = pick_indexer(rel_norm)
    exports = idx.parse_exports(p, file_text)
    exports_set = {str(x) for x in exports if isinstance(x, str)}

    imports_raw = idx.parse_imports(p, file_text)
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
        symbols_raw = idx.parse_symbols(p, file_text)
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
            module_doc = str(parse_module_doc(p, file_text) or "").strip()
        except Exception:
            module_doc = ""

    return {
        "version": CONTRACT_VERSION,
        "path": rel_norm,
        "language": idx.language(),
        "exports": exports,
        "imports": imports,
        "symbols": symbols,
        "module_doc": module_doc,
        "notes": "",
    }


def _path_exists_and_is_file(path: Path) -> tuple[bool, bool]:
    exists = path.exists()
    return exists, bool(exists and path.is_file())


async def _path_exists_and_is_file_async(path: Path) -> tuple[bool, bool]:
    return await run_fs_io_async(_path_exists_and_is_file, path, operation="contracts.path_is_file")


async def _resolve_path_async(path: Path) -> Path:
    return await run_fs_io_async(path.resolve, operation="contracts.resolve_path")


async def _resolve_under_root_async(project_root: Path, rel_path: str) -> tuple[Path, str]:
    return await run_fs_io_async(
        resolve_under_root,
        project_root,
        rel_path,
        operation="contracts.resolve_under_root",
    )


async def _sha256_file_async(path: Path) -> str:
    return await run_fs_io_async(sha256_file, path, operation="contracts.sha256")


async def _read_text_async(path: Path) -> str:
    return await run_fs_io_async(
        path.read_text,
        encoding="utf-8",
        errors="replace",
        operation="contracts.read_text",
    )


async def _build_contract_payload_async(
    project_root: Path,
    rel_norm: str,
    p: Path,
    file_text: str,
) -> dict:
    return await run_fs_io_async(
        _build_contract_payload,
        project_root,
        rel_norm,
        p,
        file_text,
        operation="contracts.build_payload",
    )


async def get_or_build_contract_async(
    session: AsyncSession,
    project_id: int,
    project_root: Path,
    rel_path: str,
) -> dict:
    project_root = await _resolve_path_async(project_root)
    try:
        p, rel_norm = await _resolve_under_root_async(project_root, rel_path)
    except PathValidationError as e:
        raise FileNotFoundError("Path escapes project root") from e
    exists, is_file = await _path_exists_and_is_file_async(p)
    if not exists or not is_file:
        raise FileNotFoundError(f"File not found: {rel_path}")

    file_hash = await _sha256_file_async(p)
    existing = (
        (
            await session.execute(
                select(ModuleContract)
                .where(
                    ModuleContract.project_id == project_id,
                    ModuleContract.path.in_([rel_norm, rel_path]),
                )
                .order_by(ModuleContract.id.desc())
            )
        )
        .scalars()
        .first()
    )
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
                    session.add(existing)
                    if rel_path != rel_norm:
                        await session.execute(
                            delete(ModuleContract).where(
                                ModuleContract.project_id == project_id,
                                ModuleContract.path == rel_path,
                            )
                        )
                    await session.commit()
                return data

    file_text = await _read_text_async(p)
    contract = await _build_contract_payload_async(project_root, rel_norm, p, file_text)

    contract_json = json.dumps(contract, ensure_ascii=False)
    stmt = (
        pg_insert(ModuleContract)
        .values(
            project_id=project_id,
            path=rel_norm,
            file_hash=file_hash,
            contract_json=contract_json,
        )
        .on_conflict_do_update(
            index_elements=["project_id", "path"],
            set_={
                "file_hash": file_hash,
                "contract_json": contract_json,
            },
        )
    )
    await session.execute(stmt)
    if rel_path != rel_norm:
        await session.execute(
            delete(ModuleContract).where(
                ModuleContract.project_id == project_id,
                ModuleContract.path == rel_path,
            )
        )
    await session.commit()

    return contract
