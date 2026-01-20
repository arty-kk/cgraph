#backend/app/resolve.py
from __future__ import annotations

import json
import re
from pathlib import Path
from functools import lru_cache
from typing import Optional

JS_EXTS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue"]
PY_EXTS = [".py", ".pyi"]
TSCONFIG_NAMES = ("tsconfig.json", "jsconfig.json")
PACKAGE_JSON_EXTS = JS_EXTS + [".d.ts"]

def _try_files(base: Path, exts: list[str]) -> Optional[Path]:
    try:
        base_suffix = base.suffix
        if base_suffix and base_suffix in exts:
            if base.exists() and base.is_file():
                return base
            exts = [base_suffix] + [e for e in exts if e != base_suffix]
    except Exception:
        pass
    
    for ext in exts:
        p = base.with_suffix(ext)
        if p.exists() and p.is_file():
            return p
    for ext in exts:
        p = base / f"index{ext}"
        if p.exists() and p.is_file():
            return p
    return None

def _pick_go_file(pkg_dir: Path) -> Optional[Path]:
    try:
        candidates = sorted(
            [
                p
                for p in pkg_dir.glob("*.go")
                if p.is_file() and not p.name.endswith("_test.go")
            ],
            key=lambda p: p.name,
        )
        return candidates[0] if candidates else None
    except Exception:
        return None

GO_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
GO_LINE_COMMENT_RE = re.compile(r"//.*?$", re.MULTILINE)

def _strip_go_comments(text: str) -> str:
    text = GO_BLOCK_COMMENT_RE.sub("", text)
    text = GO_LINE_COMMENT_RE.sub("", text)
    return text

def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and ((s[0] == s[-1]) and s[0] in ("'", '"', "`")):
        return s[1:-1].strip()
    return s

def _resolve_python_relative(project_root: Path, importer_dir: Path, spec: str) -> Optional[str]:
    leading = len(spec) - len(spec.lstrip("."))
    module = spec.lstrip(".")
    base_dir = importer_dir
    for _ in range(max(0, leading - 1)):
        base_dir = base_dir.parent
    if module:
        base_dir = base_dir.joinpath(*module.split("."))

    p = _try_files(base_dir, PY_EXTS)
    if p:
        pr = project_root.resolve()
        if pr in p.resolve().parents or p.resolve() == pr:
            return p.resolve().relative_to(pr).as_posix()
    init = base_dir / "__init__.py"
    if init.exists() and init.is_file():
        pr = project_root.resolve()
        if pr in init.resolve().parents or init.resolve() == pr:
            return init.resolve().relative_to(pr).as_posix()
    init_pyi = base_dir / "__init__.pyi"
    if init_pyi.exists() and init_pyi.is_file():
        pr = project_root.resolve()
        if pr in init_pyi.resolve().parents or init_pyi.resolve() == pr:
            return init_pyi.resolve().relative_to(pr).as_posix()
    return None

def _read_package_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None
    if isinstance(data, dict):
        return data
    return None

def _workspace_globs_from_package_json(project_root: Path) -> list[str]:
    pkg_json = project_root / "package.json"
    if not pkg_json.exists() or not pkg_json.is_file():
        return []
    data = _read_package_json(pkg_json)
    if not data:
        return []
    workspaces = data.get("workspaces")
    if isinstance(workspaces, list):
        return [w for w in workspaces if isinstance(w, str)]
    if isinstance(workspaces, dict):
        packages = workspaces.get("packages")
        if isinstance(packages, list):
            return [w for w in packages if isinstance(w, str)]
    return []

def _workspace_globs_from_pnpm_workspace(project_root: Path) -> list[str]:
    ws = project_root / "pnpm-workspace.yaml"
    if not ws.exists() or not ws.is_file():
        return []
    try:
        text = ws.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    globs: list[str] = []
    in_packages = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not in_packages:
            if stripped == "packages:":
                in_packages = True
            continue
        if not line.startswith((" ", "\t")):
            break
        if stripped.startswith("- "):
            glob = stripped[2:].strip().strip('"\'')
            if glob:
                globs.append(glob)
    return globs

def _workspace_paths_from_pnpm_lock(project_root: Path) -> list[str]:
    lock = project_root / "pnpm-lock.yaml"
    if not lock.exists() or not lock.is_file():
        return []
    try:
        text = lock.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    paths: list[str] = []
    in_importers = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not in_importers:
            if stripped == "importers:":
                in_importers = True
            continue
        if not line.startswith((" ", "\t")):
            break
        match = re.match(r"^\s{2}([^:#]+):\s*$", line)
        if match:
            entry = match.group(1).strip().strip('"\'')
            if entry:
                paths.append(entry)
    return paths

def _workspace_paths_from_package_lock(project_root: Path) -> list[str]:
    lock = project_root / "package-lock.json"
    if not lock.exists() or not lock.is_file():
        return []
    data = _read_package_json(lock)
    if not data:
        return []
    packages = data.get("packages")
    if not isinstance(packages, dict):
        return []
    paths: list[str] = []
    for key in packages.keys():
        if not isinstance(key, str) or not key:
            continue
        if "node_modules" in key.split("/"):
            continue
        paths.append(key)
    return paths

@lru_cache(maxsize=64)
def _local_package_info(project_root_str: str) -> dict[str, list[tuple[str, dict]]]:
    project_root = Path(project_root_str).resolve()
    candidates: set[Path] = set()

    for pattern in ("packages/*/package.json", "apps/*/package.json"):
        for path in project_root.glob(pattern):
            if path.is_file():
                candidates.add(path)

    for glob in _workspace_globs_from_package_json(project_root):
        for path in project_root.glob(glob):
            pkg = path / "package.json"
            if pkg.is_file():
                candidates.add(pkg)

    for glob in _workspace_globs_from_pnpm_workspace(project_root):
        for path in project_root.glob(glob):
            pkg = path / "package.json"
            if pkg.is_file():
                candidates.add(pkg)

    for rel in _workspace_paths_from_pnpm_lock(project_root):
        pkg = project_root / rel / "package.json"
        if pkg.is_file():
            candidates.add(pkg)

    for rel in _workspace_paths_from_package_lock(project_root):
        pkg = project_root / rel / "package.json"
        if pkg.is_file():
            candidates.add(pkg)

    root_pkg = project_root / "package.json"
    if root_pkg.is_file():
        candidates.add(root_pkg)

    info: dict[str, list[tuple[str, dict]]] = {}
    for pkg_path in sorted(candidates):
        try:
            resolved = pkg_path.resolve()
        except Exception:
            resolved = pkg_path
        if project_root not in resolved.parents and resolved != project_root:
            continue
        data = _read_package_json(resolved)
        if not data:
            continue
        name = data.get("name")
        if not isinstance(name, str) or not name:
            continue
        entries = info.setdefault(name, [])
        entries.append((str(resolved.parent), data))
    return info

def _export_targets(value: object) -> list[str]:
    targets: list[str] = []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        for item in value:
            targets.extend(_export_targets(item))
        return targets
    if isinstance(value, dict):
        for key in ("types", "import", "module", "default", "require"):
            if key in value:
                targets.extend(_export_targets(value.get(key)))
        return targets
    return targets

def _resolve_package_target(project_root: Path, pkg_dir: Path, target: str) -> Optional[str]:
    if not target:
        return None
    target = target.strip()
    if not target:
        return None
    if target.startswith("./"):
        target = target[2:]
    candidate = pkg_dir / target
    p = _try_files(candidate, PACKAGE_JSON_EXTS)
    if not p:
        return None
    try:
        pr = project_root.resolve()
        rp = p.resolve()
    except Exception:
        pr = project_root
        rp = p
    if pr not in rp.parents and rp != pr:
        return None
    try:
        return rp.relative_to(pr).as_posix()
    except Exception:
        return None

def _resolve_package_entry(project_root: Path, pkg_dir: Path, data: dict, subpath: str) -> Optional[str]:
    exports = data.get("exports")
    if exports is not None:
        if subpath:
            key = f"./{subpath}"
            if isinstance(exports, dict) and key in exports:
                for target in _export_targets(exports.get(key)):
                    resolved = _resolve_package_target(project_root, pkg_dir, target)
                    if resolved:
                        return resolved
        else:
            if isinstance(exports, str):
                resolved = _resolve_package_target(project_root, pkg_dir, exports)
                if resolved:
                    return resolved
            if isinstance(exports, dict):
                val = exports.get(".")
                for target in _export_targets(val):
                    resolved = _resolve_package_target(project_root, pkg_dir, target)
                    if resolved:
                        return resolved
            if isinstance(exports, list):
                for target in _export_targets(exports):
                    resolved = _resolve_package_target(project_root, pkg_dir, target)
                    if resolved:
                        return resolved

    if subpath:
        candidate = pkg_dir / subpath
        p = _try_files(candidate, PACKAGE_JSON_EXTS)
        if p:
            try:
                pr = project_root.resolve()
                rp = p.resolve()
            except Exception:
                pr = project_root
                rp = p
            if pr in rp.parents or rp == pr:
                return rp.relative_to(pr).as_posix()
        return None

    for key in ("module", "main", "types"):
        value = data.get(key)
        if isinstance(value, str) and value:
            resolved = _resolve_package_target(project_root, pkg_dir, value)
            if resolved:
                return resolved

    fallback = _try_files(pkg_dir / "index", PACKAGE_JSON_EXTS)
    if fallback:
        try:
            pr = project_root.resolve()
            rp = fallback.resolve()
        except Exception:
            pr = project_root
            rp = fallback
        if pr in rp.parents or rp == pr:
            return rp.relative_to(pr).as_posix()
    return None

def _resolve_local_package(project_root: Path, spec: str) -> Optional[str]:
    info = _local_package_info(str(project_root))
    if not info:
        return None
    best_name: Optional[str] = None
    best_entries: Optional[list[tuple[str, dict]]] = None
    for name, entries in info.items():
        if spec == name or spec.startswith(name + "/"):
            if best_name is None or len(name) > len(best_name):
                best_name = name
                best_entries = entries
    if not best_name or not best_entries:
        return None
    subpath = spec[len(best_name) :].lstrip("/")
    for pkg_dir_str, data in best_entries:
        resolved = _resolve_package_entry(project_root, Path(pkg_dir_str), data, subpath)
        if resolved:
            return resolved
    return None

def _parse_go_module_line(go_mod_text: str) -> Optional[str]:
    for line in go_mod_text.splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        if s.startswith("module "):
            s = s.split("//", 1)[0].strip()
            parts = s.split()
            if len(parts) >= 2:
                mod = parts[1].strip()
                return mod or None
    return None

def _parse_go_uses(go_work_text: str) -> list[str]:

    txt = _strip_go_comments(go_work_text)
    uses: list[str] = []
    in_block = False
    for line in txt.splitlines():
        s = line.strip()
        if not s:
            continue
        if not in_block:
            if s.startswith("use ("):
                in_block = True
                continue
            if s.startswith("use "):
                rest = s[len("use ") :].strip()
                rest = rest.split("//", 1)[0].strip()
                if rest:
                    uses.append(_strip_quotes(rest.split()[0]))
        else:
            if s.startswith(")"):
                in_block = False
                continue
            # each line in block is a path
            part = s.split("//", 1)[0].strip()
            if part:
                uses.append(_strip_quotes(part.split()[0]))
    return uses

def _parse_go_replaces(text: str) -> dict[str, str]:

    txt = _strip_go_comments(text)
    rep: dict[str, str] = {}
    in_block = False
    for line in txt.splitlines():
        s = line.strip()
        if not s:
            continue
        if not in_block:
            if s.startswith("replace ("):
                in_block = True
                continue
            if s.startswith("replace "):
                rest = s[len("replace ") :].strip()
                if "=>" not in rest:
                    continue
                left, right = rest.split("=>", 1)
                old = _strip_quotes(left.strip().split()[0])
                new = _strip_quotes(right.strip().split()[0])
                if old and new:
                    rep[old] = new
        else:
            if s.startswith(")"):
                in_block = False
                continue
            if "=>" not in s:
                continue
            left, right = s.split("=>", 1)
            old = _strip_quotes(left.strip().split()[0])
            new = _strip_quotes(right.strip().split()[0])
            if old and new:
                rep[old] = new
    return rep

def _localize_path(project_root: Path, base_dir: Path, p: str) -> Optional[Path]:

    p = _strip_quotes(p.strip())
    if not p:
        return None
    candidate = Path(p).expanduser()
    if not candidate.is_absolute():
        candidate = (base_dir / candidate)
    try:
        candidate = candidate.resolve()
    except Exception:
        candidate = candidate
    pr = project_root.resolve()
    if pr not in candidate.parents and candidate != pr:
        return None
    if not candidate.exists() or not candidate.is_dir():
        return None
    return candidate

@lru_cache(maxsize=512)
def _nearest_go_module(project_root_str: str, importer_dir_str: str) -> Optional[tuple[str, str]]:

    project_root = Path(project_root_str).resolve()
    cur = Path(importer_dir_str).resolve()

    if project_root not in cur.parents and cur != project_root:
        return None

    while True:
        gm = cur / "go.mod"
        if gm.exists() and gm.is_file():
            try:
                txt = gm.read_text(encoding="utf-8", errors="replace")
            except Exception:
                txt = ""
            mod = _parse_go_module_line(txt)
            if mod:
                return (mod, str(cur))
        if cur == project_root:
            break
        cur = cur.parent
        if project_root not in cur.parents and cur != project_root:
            break
    return None

@lru_cache(maxsize=512)
def _nearest_go_work_dir(project_root_str: str, importer_dir_str: str) -> Optional[str]:

    project_root = Path(project_root_str).resolve()
    cur = Path(importer_dir_str).resolve()

    if project_root not in cur.parents and cur != project_root:
        return None

    while True:
        gw = cur / "go.work"
        if gw.exists() and gw.is_file():
            return str(cur)
        if cur == project_root:
            break
        cur = cur.parent
        if project_root not in cur.parents and cur != project_root:
            break
    return None

@lru_cache(maxsize=256)
def _go_work_info(project_root_str: str, go_work_dir_str: str) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:

    project_root = Path(project_root_str).resolve()
    go_work_dir = Path(go_work_dir_str).resolve()
    gw = go_work_dir / "go.work"
    try:
        txt = gw.read_text(encoding="utf-8", errors="replace")
    except Exception:
        txt = ""

    modules: list[tuple[str, str]] = []
    uses = _parse_go_uses(txt)
    for u in uses:
        if not u:
            continue
        use_dir = Path(_strip_quotes(u)).expanduser()
        if not use_dir.is_absolute():
            use_dir = (go_work_dir / use_dir)
        try:
            use_dir = use_dir.resolve()
        except Exception:
            use_dir = use_dir

        if project_root not in use_dir.parents and use_dir != project_root:
            continue
        gm = use_dir / "go.mod"
        if not gm.exists() or not gm.is_file():
            continue
        try:
            gmt = gm.read_text(encoding="utf-8", errors="replace")
        except Exception:
            gmt = ""
        mod = _parse_go_module_line(gmt)
        if mod:
            modules.append((mod, str(use_dir)))

    replaces_raw = _parse_go_replaces(txt)
    replaces: list[tuple[str, str]] = []
    for old, new_tok in replaces_raw.items():
        new_dir = _localize_path(project_root, go_work_dir, new_tok)
        if new_dir:
            replaces.append((old, str(new_dir)))

    return (tuple(modules), tuple(replaces))

@lru_cache(maxsize=512)
def _go_mod_local_replaces(project_root_str: str, module_dir_str: str) -> tuple[tuple[str, str], ...]:

    project_root = Path(project_root_str).resolve()
    module_dir = Path(module_dir_str).resolve()
    gm = module_dir / "go.mod"
    if not gm.exists() or not gm.is_file():
        return tuple()
    try:
        txt = gm.read_text(encoding="utf-8", errors="replace")
    except Exception:
        txt = ""
    rep_raw = _parse_go_replaces(txt)
    out: list[tuple[str, str]] = []
    for old, new_tok in rep_raw.items():
        new_dir = _localize_path(project_root, module_dir, new_tok)
        if new_dir:
            out.append((old, str(new_dir)))
    return tuple(out)

def resolve_spec(project_root: Path, importer_rel: str, spec: str) -> Optional[str]:

    project_root = project_root.resolve()
    importer_path = (project_root / importer_rel).resolve()
    importer_dir = importer_path.parent

    if spec is None:
        return None
    spec = spec.strip()
    if not spec:
        return None

    if spec.startswith("node:"):
        return None

    spec_clean = re.split(r"[?#]", spec, maxsplit=1)[0].strip()
    if not spec_clean:
        return None

    if spec_clean.startswith("./") or spec_clean.startswith("../"):
        base = (importer_dir / spec_clean).resolve()
        if project_root not in base.parents and base != project_root:
            return None
        if base.exists() and base.is_file():
            return base.relative_to(project_root).as_posix()
        p = _try_files(base, JS_EXTS + PY_EXTS)
        if p:
            return p.relative_to(project_root).as_posix()
        return None

    if spec_clean.endswith(".php"):
        spec_path = Path(spec_clean)
        if spec_path.is_absolute():
            try:
                abs_path = spec_path.resolve()
            except Exception:
                abs_path = spec_path
            if (project_root in abs_path.parents) or (abs_path == project_root):
                if abs_path.exists() and abs_path.is_file():
                    return abs_path.relative_to(project_root).as_posix()
        else:
            candidate = (importer_dir / spec_clean)
            try:
                candidate_resolved = candidate.resolve()
            except Exception:
                candidate_resolved = candidate
            if (project_root in candidate_resolved.parents) or (candidate_resolved == project_root):
                if candidate_resolved.exists() and candidate_resolved.is_file():
                    return candidate_resolved.relative_to(project_root).as_posix()
            candidate_root = (project_root / spec_clean)
            try:
                candidate_root_resolved = candidate_root.resolve()
            except Exception:
                candidate_root_resolved = candidate_root
            if (project_root in candidate_root_resolved.parents) or (candidate_root_resolved == project_root):
                if candidate_root_resolved.exists() and candidate_root_resolved.is_file():
                    return candidate_root_resolved.relative_to(project_root).as_posix()

    if spec_clean.startswith("."):
        return _resolve_python_relative(project_root, importer_dir, spec_clean)

    ts_resolved = _resolve_tsconfig_path(project_root, importer_path, spec_clean)
    if ts_resolved:
        return ts_resolved

    pkg_resolved = _resolve_local_package(project_root, spec_clean)
    if pkg_resolved:
        return pkg_resolved

    def _best_prefix_match(value: str, candidates: list[tuple[str, str, int]]) -> Optional[tuple[str, str]]:
        best: Optional[tuple[str, str, int]] = None
        for prefix, d, prio in candidates:
            if not prefix:
                continue
            if value == prefix or value.startswith(prefix + "/"):
                cand = (prefix, d, prio)
                if best is None:
                    best = cand
                else:
                    if len(prefix) > len(best[0]) or (len(prefix) == len(best[0]) and prio < best[2]):
                        best = cand
        if best is None:
            return None
        return (best[0], best[1])

    nearest = _nearest_go_module(str(project_root), str(importer_dir))
    go_work_dir = _nearest_go_work_dir(str(project_root), str(importer_dir))

    module_candidates: list[tuple[str, str]] = []
    replace_candidates: list[tuple[str, str, int]] = []

    if nearest:
        mod_path, mod_dir_str = nearest
        module_candidates.append((mod_path, mod_dir_str))
        for old, new_dir in _go_mod_local_replaces(str(project_root), mod_dir_str):
            replace_candidates.append((old, new_dir, 0))

    if go_work_dir:
        mods, reps = _go_work_info(str(project_root), go_work_dir)
        for mp, md in mods:
            module_candidates.append((mp, md))
            for old, new_dir in _go_mod_local_replaces(str(project_root), md):
                replace_candidates.append((old, new_dir, 2))
        for old, new_dir in reps:
            replace_candidates.append((old, new_dir, 1))

    rep_match = _best_prefix_match(spec_clean, replace_candidates)
    if rep_match:
        old_prefix, new_dir_str = rep_match
        base_dir = Path(new_dir_str).resolve()
        sub = spec_clean[len(old_prefix) :].lstrip("/")
        pkg_dir = base_dir / sub if sub else base_dir
        try:
            pkg_dir_res = pkg_dir.resolve()
        except Exception:
            pkg_dir_res = pkg_dir
        if (project_root in pkg_dir_res.parents) or (pkg_dir_res == project_root):
            if pkg_dir_res.exists() and pkg_dir_res.is_dir():
                go_file = _pick_go_file(pkg_dir_res)
                if go_file:
                    return go_file.relative_to(project_root).as_posix()

    mod_prefix_candidates: list[tuple[str, str, int]] = []
    for i, (mp, md) in enumerate(module_candidates):
        mod_prefix_candidates.append((mp, md, i))
    mod_match = _best_prefix_match(spec_clean, mod_prefix_candidates)
    if mod_match:
        mod_path, mod_dir_str = mod_match
        module_dir = Path(mod_dir_str).resolve()
        sub = spec_clean[len(mod_path) :].lstrip("/")
        pkg_dir = module_dir / sub if sub else module_dir
        try:
            pkg_dir_res = pkg_dir.resolve()
        except Exception:
            pkg_dir_res = pkg_dir
        if (project_root in pkg_dir_res.parents) or (pkg_dir_res == project_root):
            if pkg_dir_res.exists() and pkg_dir_res.is_dir():
                go_file = _pick_go_file(pkg_dir_res)
                if go_file:
                    return go_file.relative_to(project_root).as_posix()

    roots = [project_root]
    src_root = project_root / "src"
    try:
        if src_root.exists() and src_root.is_dir():
            roots.append(src_root)
    except Exception:
        pass

    parts = spec_clean.split(".")
    for base_root in roots:
        base = base_root.joinpath(*parts)
        p = _try_files(base, PY_EXTS)
        if p:
            return p.relative_to(project_root).as_posix()
        init = base / "__init__.py"
        if init.exists() and init.is_file():
            return init.relative_to(project_root).as_posix()
        init_pyi = base / "__init__.pyi"
        if init_pyi.exists() and init_pyi.is_file():
            return init_pyi.relative_to(project_root).as_posix()

    return None


@lru_cache(maxsize=256)
def _tsconfig_info(project_root_str: str, importer_dir_str: str) -> dict:
    project_root = Path(project_root_str).resolve()
    cur = Path(importer_dir_str).resolve()

    if project_root not in cur.parents and cur != project_root:
        return {}

    while True:
        for name in TSCONFIG_NAMES:
            cfg = cur / name
            if not cfg.exists() or not cfg.is_file():
                continue
            try:
                data = json.loads(cfg.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            compiler_opts = data.get("compilerOptions")
            if not isinstance(compiler_opts, dict):
                compiler_opts = {}
            base_url = compiler_opts.get("baseUrl")
            if not isinstance(base_url, str):
                base_url = ""
            paths = compiler_opts.get("paths")
            if not isinstance(paths, dict):
                paths = {}
            try:
                base_dir = cfg.parent.resolve()
            except Exception:
                base_dir = cfg.parent
            return {
                "base_dir": base_dir,
                "base_url": base_url,
                "paths": paths,
            }
        if cur == project_root:
            break
        cur = cur.parent
        if project_root not in cur.parents and cur != project_root:
            break
    return {}


def _resolve_tsconfig_path(project_root: Path, importer_path: Path, spec: str) -> Optional[str]:
    if importer_path.suffix.lower() not in JS_EXTS:
        return None
    info = _tsconfig_info(str(project_root), str(importer_path.parent))
    if not info:
        return None

    base_dir: Path = info.get("base_dir") or project_root
    base_url_raw = str(info.get("base_url") or "").strip()
    base_url = (base_dir / base_url_raw) if base_url_raw else base_dir

    def _try_candidate(candidate: Path) -> Optional[str]:
        p = _try_files(candidate, JS_EXTS)
        if not p:
            return None
        try:
            pr = project_root.resolve()
            rp = p.resolve()
        except Exception:
            pr = project_root
            rp = p
        if pr not in rp.parents and rp != pr:
            return None
        try:
            return rp.relative_to(pr).as_posix()
        except Exception:
            return None
        return None

    paths = info.get("paths") or {}

    exact_targets = paths.get(spec)
    if isinstance(exact_targets, str):
        exact_targets_list = [exact_targets]
    elif isinstance(exact_targets, list):
        exact_targets_list = [t for t in exact_targets if isinstance(t, str)]
    else:
        exact_targets_list = []
    for target in exact_targets_list:
        resolved = _try_candidate(base_url / target)
        if resolved:
            return resolved

    best_match: Optional[str] = None
    best_prefix_len = -1
    for pat, targets in paths.items():
        if not isinstance(pat, str) or "*" not in pat:
            continue
        prefix, _, suffix = pat.partition("*")
        if not spec.startswith(prefix) or not spec.endswith(suffix):
            continue
        middle = spec[len(prefix) : len(spec) - len(suffix)]
        if len(prefix) <= best_prefix_len:
            continue
        if isinstance(targets, str):
            targets_list = [targets]
        elif isinstance(targets, list):
            targets_list = [t for t in targets if isinstance(t, str)]
        else:
            targets_list = []
        for target in targets_list:
            t_prefix, _, t_suffix = target.partition("*")
            candidate = base_url / (t_prefix + middle + t_suffix)
            resolved = _try_candidate(candidate)
            if resolved:
                best_match = resolved
                best_prefix_len = len(prefix)
                break
    if best_match:
        return best_match

    candidate = base_url / spec
    return _try_candidate(candidate)
