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

def get_or_build_contract(project_id: int, project_root: Path, rel_path: str) -> dict:
    project_root = project_root.resolve()
    try:
        p, rel_norm = resolve_under_root(project_root, rel_path)
    except ValueError:
        raise FileNotFoundError("Path escapes project root")
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
    contract = {
        "path": rel_norm,
        "language": idx.language(),
        "exports": exports,
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
