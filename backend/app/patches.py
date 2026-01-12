#backend/app/patches.py
from __future__ import annotations

import ast
import tempfile
from pathlib import Path
from unidiff import PatchSet

class PatchApplyError(RuntimeError):
    pass

def apply_unified_diff(
    project_root: Path,
    diff_text: str,
    *,
    allowed_rel_paths: set[str] | None = None,
    allow_new_files: bool = False,
) -> list[str]:
    try:
        patch = PatchSet(diff_text.splitlines(keepends=True))
    except Exception as e:
        raise PatchApplyError(f"Invalid unified diff: {e}")

    modified: list[str] = []
    root_resolved = project_root.resolve()
    new_contents: dict[Path, list[str]] = {}
    to_remove: list[Path] = []

    for f in patch:
        path = f.path
        if path.startswith("a/") or path.startswith("b/"):
            path = path[2:]
        rel = Path(path)
        abs_path = (project_root / rel).resolve()
        if root_resolved not in abs_path.parents and abs_path != root_resolved:
            raise PatchApplyError(f"Refusing to write outside project root: {rel}")
        if abs_path == root_resolved:
            raise PatchApplyError(f"Invalid patch path: {rel}")
        rel_norm = abs_path.relative_to(root_resolved).as_posix()
        if allowed_rel_paths is not None and rel_norm not in allowed_rel_paths:
            raise PatchApplyError(f"Refusing to patch outside allowed scope: {rel_norm}")
        if abs_path.exists() and not abs_path.is_file():
            raise PatchApplyError(f"Refusing to patch non-file path: {rel_norm}")

        if getattr(f, "is_removed_file", False):
            to_remove.append(abs_path)
            modified.append(rel_norm)
            continue

        if not abs_path.exists():
            if not allow_new_files:
                raise PatchApplyError(f"Refusing to create new file: {rel_norm}")
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            original_lines: list[str] = []
        else:
            original_lines = abs_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

        new_lines = _apply_file_patch(original_lines, f)
        new_contents[abs_path] = new_lines
        modified.append(rel_norm)

    for abs_path, lines in new_contents.items():
        if abs_path.suffix.lower() == ".py":
            try:
                ast.parse("".join(lines))
            except SyntaxError as e:
                raise PatchApplyError(f"Python syntax error after patch in {abs_path.name}: {e}")

    for abs_path, lines in new_contents.items():
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_name = tempfile.mkstemp(dir=str(abs_path.parent), prefix=abs_path.name + ".tmp.")
        tmp_path = Path(tmp_name)
        try:
            with open(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write("".join(lines))
            tmp_path.replace(abs_path)
        except Exception as e:
            raise PatchApplyError(f"Failed to write {abs_path}: {e}")
        finally:
            try:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    for abs_path in to_remove:
        try:
            if abs_path.exists():
                abs_path.unlink()
        except Exception as e:
            raise PatchApplyError(f"Failed to remove {abs_path}: {e}")

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
