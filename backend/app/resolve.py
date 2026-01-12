#backend/app/resolve.py
from __future__ import annotations

import json
import re
from pathlib import Path
from functools import lru_cache
from typing import Optional

JS_EXTS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"]
PY_EXTS = [".py", ".pyi"]
TSCONFIG_NAMES = ("tsconfig.json", "jsconfig.json")

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
        p = _try_files(base, JS_EXTS + PY_EXTS)
        if p:
            return p.relative_to(project_root).as_posix()
        return None

    if spec_clean.startswith("."):
        return _resolve_python_relative(project_root, importer_dir, spec_clean)

    ts_resolved = _resolve_tsconfig_path(project_root, importer_path, spec_clean)
    if ts_resolved:
        return ts_resolved

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


@lru_cache(maxsize=128)
def _tsconfig_info(project_root_str: str) -> dict:
    project_root = Path(project_root_str).resolve()
    for name in TSCONFIG_NAMES:
        cfg = project_root / name
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
    return {}


def _resolve_tsconfig_path(project_root: Path, importer_path: Path, spec: str) -> Optional[str]:
    if importer_path.suffix.lower() not in JS_EXTS:
        return None
    info = _tsconfig_info(str(project_root))
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
