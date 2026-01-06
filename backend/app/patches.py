#backend/app/patches.py
from __future__ import annotations

from pathlib import Path
from unidiff import PatchSet

class PatchApplyError(RuntimeError):
    pass

def apply_unified_diff(project_root: Path, diff_text: str) -> list[str]:
    try:
        patch = PatchSet(diff_text.splitlines(keepends=True))
    except Exception as e:
        raise PatchApplyError(f"Invalid unified diff: {e}")

    modified: list[str] = []
    root_resolved = project_root.resolve()

    for f in patch:
        path = f.path
        if path.startswith("a/") or path.startswith("b/"):
            path = path[2:]
        rel = Path(path)
        abs_path = (project_root / rel).resolve()
        if root_resolved not in abs_path.parents and abs_path != root_resolved:
            raise PatchApplyError(f"Refusing to write outside project root: {rel}")

        if getattr(f, "is_removed_file", False):
            if abs_path.exists():
                abs_path.unlink()
            modified.append(rel.as_posix())
            continue

        if not abs_path.exists():
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            original_lines: list[str] = []
        else:
            original_lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

        new_lines = _apply_file_patch(original_lines, f)
        abs_path.write_text("".join(new_lines), encoding="utf-8")
        modified.append(rel.as_posix())

    return modified

def _apply_file_patch(original: list[str], file_patch) -> list[str]:
    out: list[str] = []
    idx = 0
    for hunk in file_patch:
        target_start = max(0, (hunk.source_start or 1) - 1)
        while idx < target_start and idx < len(original):
            out.append(original[idx])
            idx += 1

        for line in hunk:
            if line.is_context:
                if idx >= len(original) or original[idx] != line.value:
                    raise PatchApplyError("Context mismatch while applying patch")
                out.append(original[idx])
                idx += 1
            elif line.is_removed:
                if idx >= len(original) or original[idx] != line.value:
                    raise PatchApplyError("Removal mismatch while applying patch")
                idx += 1
            elif line.is_added:
                out.append(line.value)
            else:
                raise PatchApplyError("Unknown patch line type")
    out.extend(original[idx:])
    return out
