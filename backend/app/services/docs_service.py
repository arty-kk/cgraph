#backend/app/services/docs_service.py
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlmodel import select

from ..config import settings
from ..contracts import get_or_build_contract
from ..db import get_session
from ..errors import BadRequestError, NotFoundError
from ..llm.orchestrator import generate_docs
from ..models import (
    ApiCall, ApiInclude,
    ApiRoute, FileEdge,
    FileNode, ProjectDoc,
)
from ..services.project_service import get_project
from ..utils import normalize_project_root, resolve_under_root


_KEY_FILE_MAX_CHARS = 4_000
_MAX_KEY_FILES = 14
_MAX_RUN_HINTS = 40
_MAX_CONTRACTS = 25
_MAX_CONTRACT_IMPORTS = 60
_MAX_CONTRACT_SYMBOLS = 60
_MAX_CONTRACT_DOC_CHARS = 1_200
_MAX_CONTRACT_SIG_CHARS = 240

_MAKE_TARGET_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]{0,80})\s*:\s*(?:#.*)?$")

_RUN_HINT_PREFIXES: tuple[str, ...] = (
    # general
    "cd ",
    "make",
    "docker",
    "docker-compose",
    "compose",
    # python
    "pytest",
    "uvicorn",
    "gunicorn",
    "alembic",
    "poetry",
    "pip",
    "python",
    "python3",
    "uv",
    # node
    "npm",
    "pnpm",
    "yarn",
    "bun",
    # go
    "go run",
    "go test",
    "go build",
    "go install",
    "go generate",
    # rust
    "cargo run",
    "cargo test",
    "cargo build",
    "cargo install",
    # dotnet
    "dotnet run",
    "dotnet test",
    "dotnet build",
    "dotnet restore",
    "dotnet publish",
    # java/kotlin
    "mvn",
    "./mvnw",
    "gradle",
    "./gradlew",
    # ruby
    "bundle exec",
    "bundle install",
    "rails ",
    "rake",
    # php
    "composer",
    "php artisan",
    "phpunit",
    "bin/console",
    # elixir
    "mix ",
    # task runners
    "task ",
    "just ",
    "mage ",
)

def _risk_row(path: str, loc: int, complexity: int, fan_in: int, fan_out: int, status: str) -> dict:
    risk = (0.3 * float(complexity)) + (0.7 * float(fan_in)) + (0.1 * float(fan_out))
    return {
        "path": path,
        "loc": int(loc),
        "complexity": int(complexity),
        "fan_in": int(fan_in),
        "fan_out": int(fan_out),
        "status": status,
        "risk": float(risk),
    }


def _tree_outline(paths: list[str], max_lines: int = 1200) -> dict:
    root: dict[str, Any] = {}
    for p in paths:
        parts = [x for x in p.split("/") if x]
        cur = root
        for part in parts:
            cur = cur.setdefault(part, {})

    lines: list[str] = []
    truncated = False

    def walk(node: dict[str, Any], prefix: str, depth: int) -> None:
        nonlocal truncated
        if truncated:
            return
        keys = sorted(node.keys())
        for k in keys:
            if truncated:
                return
            indent = "  " * depth
            lines.append(f"{indent}- {k}")
            if len(lines) >= max_lines:
                truncated = True
                return
            child = node.get(k)
            if isinstance(child, dict) and child:
                walk(child, prefix + k + "/", depth + 1)

    walk(root, "", 0)
    return {"lines": lines, "truncated": truncated, "max_lines": max_lines}

def _path_depth(p: str) -> int:
    if not isinstance(p, str) or not p:
        return 10**9
    return len([x for x in p.split("/") if x])

def _path_dir(p: str) -> str:
    if not isinstance(p, str) or not p:
        return ""
    return p.rsplit("/", 1)[0] if "/" in p else ""

def _basename(p: str) -> str:
    if not isinstance(p, str) or not p:
        return ""
    return p.rsplit("/", 1)[-1] if "/" in p else p

def _best_paths(paths: list[str], *, limit: int) -> list[str]:
    uniq = list(dict.fromkeys([p for p in paths if isinstance(p, str) and p.strip()]))
    uniq.sort(key=lambda x: (_path_depth(x), x))
    return uniq[: max(0, int(limit))]

def _read_text_under_root(root: Path, rel_path: str, *, max_chars: int) -> dict | None:
    if not isinstance(rel_path, str) or not rel_path.strip():
        return None
    try:
        abs_path, rel_norm = resolve_under_root(root, rel_path, max_length=settings.max_rel_path_chars)
    except Exception:
        return None
    if not abs_path.exists() or not abs_path.is_file():
        return None
    try:
        text = abs_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    truncated = len(text) > int(max_chars)
    if truncated:
        text = text[: int(max_chars)]
    return {"path": rel_norm, "content": text, "truncated": bool(truncated), "max_chars": int(max_chars)}

def _normalize_existing_file_under_root(root: Path, rel_path: str) -> str | None:
    if not isinstance(rel_path, str) or not rel_path.strip():
        return None
    try:
        abs_path, rel_norm = resolve_under_root(root, rel_path, max_length=settings.max_rel_path_chars)
    except Exception:
        return None
    if not abs_path.exists() or not abs_path.is_file():
        return None
    return rel_norm

def _extract_make_targets(text: str, *, max_targets: int = 40) -> list[str]:
    if not isinstance(text, str) or not text:
        return []
    out: list[str] = []
    for line in text.splitlines():
        m = _MAKE_TARGET_RE.match(line)
        if not m:
            continue
        t = (m.group(1) or "").strip()
        if not t or t.startswith("."):
            continue
        if t not in out:
            out.append(t)
            if len(out) >= int(max_targets):
                break
    return out


def _extract_package_json_scripts(text: str, *, max_scripts: int = 30) -> dict[str, str]:
    if not isinstance(text, str) or not text.strip():
        return {}
    try:
        data = json.loads(text)
    except Exception:
        return {}
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in scripts.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if not isinstance(v, str) or not v.strip():
            continue
        out[k.strip()] = v.strip()
        if len(out) >= int(max_scripts):
            break
    return out

def _starts_with_run_prefix(low: str) -> bool:
    if not isinstance(low, str) or not low:
        return False
    s = low.lstrip()
    for pref in _RUN_HINT_PREFIXES:
        if not pref:
            continue
        p = pref.lower()
        # If prefix ends with space, treat as strict prefix (covers multiword like "go test")
        if p.endswith(" "):
            if s.startswith(p):
                return True
            continue
        # Otherwise enforce word boundary to avoid false positives like "makefile"
        if s == p or s.startswith(p + " ") or s.startswith(p + "\t"):
            return True
    return False

def _extract_run_hints(text: str, *, max_hints: int = _MAX_RUN_HINTS) -> list[str]:
    if not isinstance(text, str) or not text:
        return []

    out: list[str] = []
    for raw in text.splitlines():
        if len(out) >= int(max_hints):
            break
        s = (raw or "").strip()
        if not s:
            continue
        if s.startswith("```"):
            continue
        # common markdown formatting
        s = s.lstrip("-* ").strip()
        if s.startswith("$"):
            s = s.lstrip("$").strip()
        if not s:
            continue
        low = s.lower()
        if _starts_with_run_prefix(low):
            if len(s) > 220:
                s = s[:220] + "…"
            if s not in out:
                out.append(s)
    return out


def _compact_contract(c: dict) -> dict:
    if not isinstance(c, dict):
        return {}
    imports = c.get("imports") if isinstance(c.get("imports"), list) else []
    symbols = c.get("symbols") if isinstance(c.get("symbols"), list) else []
    module_doc = str(c.get("module_doc") or "")
    if len(module_doc) > _MAX_CONTRACT_DOC_CHARS:
        module_doc = module_doc[:_MAX_CONTRACT_DOC_CHARS] + "…"
    out: dict[str, Any] = {
        "version": c.get("version"),
        "path": c.get("path"),
        "language": c.get("language"),
        "exports": c.get("exports") if isinstance(c.get("exports"), list) else [],
        "module_doc": module_doc,
        "imports": [],
        "symbols": [],
        "notes": c.get("notes") if isinstance(c.get("notes"), str) else "",
    }

    imp_out: list[dict[str, Any]] = []
    for item in imports[:_MAX_CONTRACT_IMPORTS]:
        if not isinstance(item, dict):
            continue
        spec = str(item.get("spec") or "")
        if not spec:
            continue
        imp_out.append(
            {
                "spec": spec,
                "kind": str(item.get("kind") or ""),
                "resolved_path": str(item.get("resolved_path") or ""),
            }
        )
    out["imports"] = imp_out

    sym_out: list[dict[str, Any]] = []
    for item in symbols[:_MAX_CONTRACT_SYMBOLS]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        sig = str(item.get("signature") or "")
        if len(sig) > _MAX_CONTRACT_SIG_CHARS:
            sig = sig[:_MAX_CONTRACT_SIG_CHARS] + "…"
        doc = str(item.get("doc") or "")
        if len(doc) > 240:
            doc = doc[:240] + "…"
        sym_out.append(
            {
                "name": name,
                "kind": str(item.get("kind") or ""),
                "signature": sig,
                "doc": doc,
                "start_line": int(item.get("start_line") or 0),
                "end_line": int(item.get("end_line") or 0),
                "exported": bool(item.get("exported")),
            }
        )
    out["symbols"] = sym_out
    return out


def _normalize_prefix(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return ""
    return p if p.startswith("/") else ("/" + p)


def _route_prefix(path: str) -> str:
    p = _normalize_prefix(path)
    parts = [x for x in p.split("/") if x]
    if not parts:
        return "/"
    if parts[0] == "api" and len(parts) >= 2:
        return "/api/" + parts[1]
    return "/" + parts[0]


def _build_api_summary(project_id: int) -> dict:
    try:
        with get_session() as s:
            routes_total_row = s.exec(select(func.count()).select_from(ApiRoute).where(ApiRoute.project_id == project_id)).one()
            calls_total_row = s.exec(select(func.count()).select_from(ApiCall).where(ApiCall.project_id == project_id)).one()
            includes_total_row = s.exec(select(func.count()).select_from(ApiInclude).where(ApiInclude.project_id == project_id)).one()

            routes_total = int(routes_total_row[0] if isinstance(routes_total_row, (tuple, list)) else routes_total_row)
            calls_total = int(calls_total_row[0] if isinstance(calls_total_row, (tuple, list)) else calls_total_row)
            includes_total = int(includes_total_row[0] if isinstance(includes_total_row, (tuple, list)) else includes_total_row)

            route_methods_rows = s.exec(
                select(ApiRoute.method, func.count())
                .where(ApiRoute.project_id == project_id)
                .group_by(ApiRoute.method)
                .order_by(ApiRoute.method)
            ).all()
            call_methods_rows = s.exec(
                select(ApiCall.method, func.count())
                .where(ApiCall.project_id == project_id)
                .group_by(ApiCall.method)
                .order_by(ApiCall.method)
            ).all()

            ROUTE_SAMPLE = 20_000
            CALL_SAMPLE = 20_000
            route_paths_rows = s.exec(select(ApiRoute.path).where(ApiRoute.project_id == project_id).limit(ROUTE_SAMPLE)).all()
            call_paths_rows = s.exec(select(ApiCall.path).where(ApiCall.project_id == project_id).limit(CALL_SAMPLE)).all()
    except Exception as e:
        return {"error": "api_summary_failed", "message": str(e)}

    routes_by_method: list[dict] = []
    for row in route_methods_rows:
        if isinstance(row, (tuple, list)) and len(row) >= 2:
            m, cnt = row[0], row[1]
        else:
            continue
        routes_by_method.append({"method": str(m or ""), "count": int(cnt or 0)})

    calls_by_method: list[dict] = []
    for row in call_methods_rows:
        if isinstance(row, (tuple, list)) and len(row) >= 2:
            m, cnt = row[0], row[1]
        else:
            continue
        calls_by_method.append({"method": str(m or ""), "count": int(cnt or 0)})

    pref_routes: dict[str, int] = {}
    for row in route_paths_rows:
        p = row[0] if isinstance(row, (tuple, list)) else row
        if not isinstance(p, str) or not p:
            continue
        pref = _route_prefix(p)
        pref_routes[pref] = pref_routes.get(pref, 0) + 1

    pref_calls: dict[str, int] = {}
    for row in call_paths_rows:
        p = row[0] if isinstance(row, (tuple, list)) else row
        if not isinstance(p, str) or not p:
            continue
        pref = _route_prefix(p)
        pref_calls[pref] = pref_calls.get(pref, 0) + 1

    top_route_prefixes = sorted(pref_routes.items(), key=lambda x: (-x[1], x[0]))[:20]
    top_call_prefixes = sorted(pref_calls.items(), key=lambda x: (-x[1], x[0]))[:20]

    return {
        "counts": {"routes": int(routes_total), "calls": int(calls_total), "includes": int(includes_total)},
        "routes_by_method": routes_by_method,
        "calls_by_method": calls_by_method,
        "top_route_prefixes": [{"prefix": k, "count": int(v)} for k, v in top_route_prefixes],
        "top_call_prefixes": [{"prefix": k, "count": int(v)} for k, v in top_call_prefixes],
        "notes": (
            "Routes are stored as local decorator paths. include_router prefixes are not expanded in this summary."
        ),
    }


def _collect_key_files(root: Path, project_paths: list[str]) -> tuple[list[dict], dict]:
    key_files: list[dict] = []
    parsed: dict[str, Any] = {"makefiles": [], "node_packages": []}
    seen: set[str] = set()

    all_paths = [p for p in (project_paths or []) if isinstance(p, str) and p.strip()]
    all_paths = list(dict.fromkeys(all_paths))
    paths_set = set(all_paths)

    by_base: dict[str, list[str]] = {}
    for p in all_paths:
        b = _basename(p)
        if b:
            by_base.setdefault(b, []).append(p)
    for b, lst in by_base.items():
        lst.sort(key=lambda x: (_path_depth(x), x))

    def _exists_in_dir(dir_path: str, filename: str) -> bool:
        if not isinstance(filename, str) or not filename:
            return False
        if dir_path:
            return f"{dir_path.rstrip('/')}/{filename}" in paths_set
        return filename in paths_set

    def _detect_node_pm(dir_path: str) -> str:
        # Prefer local lockfile next to package.json; fallback to repo root.
        if _exists_in_dir(dir_path, "pnpm-lock.yaml") or _exists_in_dir("", "pnpm-lock.yaml"):
            return "pnpm"
        if _exists_in_dir(dir_path, "yarn.lock") or _exists_in_dir("", "yarn.lock"):
            return "yarn"
        if _exists_in_dir(dir_path, "bun.lockb") or _exists_in_dir("", "bun.lockb"):
            return "bun"
        if _exists_in_dir(dir_path, "package-lock.json") or _exists_in_dir("", "package-lock.json"):
            return "npm"
        return ""

    def add(role: str, rel_path: str, *, include_content: bool = True) -> None:
        if len(key_files) >= _MAX_KEY_FILES:
            return
        if include_content:
            rec = _read_text_under_root(root, rel_path, max_chars=_KEY_FILE_MAX_CHARS)
            if not isinstance(rec, dict):
                return
        else:
            rp_norm = _normalize_existing_file_under_root(root, rel_path)
            if not rp_norm:
                return
            rec = {"path": rp_norm, "content": "", "truncated": False, "max_chars": 0, "content_omitted": True}

        rp = str(rec.get("path") or "")
        if not rp or rp in seen:
            return
        seen.add(rp)
        rec["role"] = role
        txt = str(rec.get("content") or "")
        d = _path_dir(rp)
        if role == "makefile" and txt:
            targets = _extract_make_targets(txt, max_targets=40)
            if targets:
                parsed.setdefault("makefiles", [])
                if isinstance(parsed["makefiles"], list) and len(parsed["makefiles"]) < 4:
                    parsed["makefiles"].append({"path": rp, "dir": d, "targets": targets})
        if role == "node_project" and (_basename(rp) == "package.json") and txt:
            scripts = _extract_package_json_scripts(txt, max_scripts=30)
            pm = _detect_node_pm(d)
            parsed.setdefault("node_packages", [])
            if isinstance(parsed["node_packages"], list) and len(parsed["node_packages"]) < 4:
                parsed["node_packages"].append({"path": rp, "dir": d, "package_manager": pm, "scripts": scripts})
        key_files.append(rec)

    specs: list[dict[str, Any]] = [
        # docs / ops
        {"role": "readme", "basename": "README.md", "max": 2},
        {"role": "readme", "basename": "readme.md", "max": 1},
        {"role": "makefile", "basename": "Makefile", "max": 2},
        {"role": "taskfile", "basename": "Taskfile.yml", "max": 1},
        {"role": "taskfile", "basename": "Taskfile.yaml", "max": 1},
        {"role": "justfile", "basename": "Justfile", "max": 1},
        {"role": "docker", "basename": "docker-compose.yml", "max": 2},
        {"role": "docker", "basename": "docker-compose.yaml", "max": 2},
        {"role": "docker", "basename": "compose.yml", "max": 2},
        {"role": "docker", "basename": "compose.yaml", "max": 2},
        {"role": "docker", "basename": "Dockerfile", "max": 2},

        # python
        {"role": "python_project", "basename": "pyproject.toml", "max": 2},
        {"role": "python_project", "basename": "requirements.txt", "max": 2},
        {"role": "python_project", "basename": "requirements-dev.txt", "max": 2},
        {"role": "python_project", "basename": "Pipfile", "max": 2},
        {"role": "python_project", "basename": "setup.py", "max": 1},
        {"role": "python_project", "basename": "setup.cfg", "max": 1},
        {"role": "python_project", "basename": "tox.ini", "max": 1},

        # node
        {"role": "node_project", "basename": "package.json", "max": 3},

        # go
        {"role": "go_project", "basename": "go.mod", "max": 2},
        {"role": "go_project", "basename": "go.work", "max": 1},

        # rust
        {"role": "rust_project", "basename": "Cargo.toml", "max": 2},

        # java/kotlin
        {"role": "java_project", "basename": "pom.xml", "max": 2},
        {"role": "java_project", "basename": "build.gradle", "max": 2},
        {"role": "java_project", "basename": "build.gradle.kts", "max": 2},
        {"role": "java_project", "basename": "settings.gradle", "max": 1},
        {"role": "java_project", "basename": "settings.gradle.kts", "max": 1},

        # dotnet
        {"role": "dotnet_project", "suffix": ".csproj", "max": 2},
        {"role": "dotnet_project", "suffix": ".fsproj", "max": 1},
        {"role": "dotnet_solution", "suffix": ".sln", "max": 1},

        # ruby
        {"role": "ruby_project", "basename": "Gemfile", "max": 2},

        # php
        {"role": "php_project", "basename": "composer.json", "max": 2},

        # elixir
        {"role": "elixir_project", "basename": "mix.exs", "max": 1},
    ]

    for spec in specs:
        if len(key_files) >= _MAX_KEY_FILES:
            break
        role = str(spec.get("role") or "")
        lim = int(spec.get("max") or 1)
        bname = spec.get("basename")
        suf = spec.get("suffix")
        matches: list[str] = []
        if isinstance(bname, str) and bname:
            matches = by_base.get(bname, [])[:]
        elif isinstance(suf, str) and suf:
            matches = [p for p in all_paths if p.endswith(suf)]
        matches = _best_paths(matches, limit=lim)
        for p in matches:
            add(role, p, include_content=True)
            if len(key_files) >= _MAX_KEY_FILES:
                break

    entry_names = (
        # python
        "main.py", "__main__.py", "app.py", "wsgi.py", "asgi.py", "manage.py",
        # node
        "index.ts", "index.js", "main.ts", "main.js", "server.ts", "server.js", "app.ts", "app.js",
        # go / rust
        "main.go", "main.rs",
        # dotnet
        "Program.cs",
        # java/kotlin (conventional names)
        "Main.java", "Application.java", "Main.kt", "Application.kt",
    )
    entry_candidates = [p for p in (project_paths or []) if isinstance(p, str) and p.endswith(entry_names)]
    entry_candidates = sorted(entry_candidates, key=lambda x: (len(x.split("/")), x))[:6]
    for p in entry_candidates:
        add("entrypoint", p)

    return key_files, parsed


def _build_run_hints(key_files: list[dict], parsed: dict) -> list[str]:
    hints: list[str] = []
    for kf in key_files or []:
        if isinstance(kf, dict):
            hints.extend(_extract_run_hints(str(kf.get("content") or ""), max_hints=_MAX_RUN_HINTS))

    makefiles = parsed.get("makefiles") if isinstance(parsed, dict) else None
    if isinstance(makefiles, list):
        for mf in makefiles[:4]:
            if not isinstance(mf, dict):
                continue
            d = str(mf.get("dir") or "")
            targets = mf.get("targets") if isinstance(mf.get("targets"), list) else []
            for t in targets[:20]:
                if not isinstance(t, str) or not t:
                    continue
                if d:
                    hints.append(f"cd {d} && make {t}")
                else:
                    hints.append(f"make {t}")

    def _node_cmd(pm: str, script: str) -> str:
        p = (pm or "").strip().lower()
        s = script.strip()
        if p == "pnpm":
            return f"pnpm run {s}"
        if p == "yarn":
            # yarn supports `yarn <script>` widely.
            return f"yarn {s}"
        if p == "bun":
            return f"bun run {s}"
        return f"npm run {s}"

    node_pkgs = parsed.get("node_packages") if isinstance(parsed, dict) else None
    if isinstance(node_pkgs, list):
        for pkg in node_pkgs[:4]:
            if not isinstance(pkg, dict):
                continue
            d = str(pkg.get("dir") or "")
            pm = str(pkg.get("package_manager") or "")
            scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
            for name in list(scripts.keys())[:25]:
                if not isinstance(name, str) or not name.strip():
                    continue
                cmd = _node_cmd(pm, name)
                if d:
                    hints.append(f"cd {d} && {cmd}")
                else:
                    hints.append(cmd)

    out: list[str] = []
    for h in hints:
        if not isinstance(h, str) or not h.strip():
            continue
        if h not in out:
            out.append(h)
        if len(out) >= _MAX_RUN_HINTS:
            break
    return out


def _api_summary_md(api_summary: dict) -> str:
    if not isinstance(api_summary, dict) or api_summary.get("error"):
        msg = str(api_summary.get("message") or "").strip()
        if msg:
            return f"> API summary unavailable: {msg}\n"
        return "> API summary unavailable.\n"

    counts = api_summary.get("counts") if isinstance(api_summary.get("counts"), dict) else {}
    routes = int(counts.get("routes") or 0)
    calls = int(counts.get("calls") or 0)
    includes = int(counts.get("includes") or 0)
 
    if routes == 0 and calls == 0 and includes == 0:
        return (
            "> No API map data available (Scan produced zero routes/calls/includes). "
            "This section is framework/indexer-dependent.\n"
        )

    out: list[str] = [
        f"- Backend routes: **{routes}**",
        f"- Frontend calls: **{calls}**",
        f"- include_router edges: **{includes}**",
        "",
    ]

    rbm = api_summary.get("routes_by_method") if isinstance(api_summary.get("routes_by_method"), list) else []
    if rbm:
        out += [
            "**Routes by method**",
            "",
            "| method | routes |",
            "|---|---:|",
        ]
        for r in rbm[:30]:
            if isinstance(r, dict):
                out.append(f"| `{str(r.get('method') or '')}` | {int(r.get('count') or 0)} |")
        out.append("")

    cbm = api_summary.get("calls_by_method") if isinstance(api_summary.get("calls_by_method"), list) else []
    if cbm:
        out += [
            "**Calls by method**",
            "",
            "| method | calls |",
            "|---|---:|",
        ]
        for r in cbm[:30]:
            if isinstance(r, dict):
                out.append(f"| `{str(r.get('method') or '')}` | {int(r.get('count') or 0)} |")
        out.append("")

    trp = api_summary.get("top_route_prefixes") if isinstance(api_summary.get("top_route_prefixes"), list) else []
    if trp:
        out += [
            "**Top route prefixes**",
            "",
            "| prefix | routes |",
            "|---|---:|",
        ]
        for r in trp[:15]:
            if isinstance(r, dict):
                out.append(f"| `{str(r.get('prefix') or '')}` | {int(r.get('count') or 0)} |")
        out.append("")

    tcp = api_summary.get("top_call_prefixes") if isinstance(api_summary.get("top_call_prefixes"), list) else []
    if tcp:
        out += [
            "**Top call prefixes**",
            "",
            "| prefix | calls |",
            "|---|---:|",
        ]
        for r in tcp[:15]:
            if isinstance(r, dict):
                out.append(f"| `{str(r.get('prefix') or '')}` | {int(r.get('count') or 0)} |")
        out.append("")

    note = str(api_summary.get("notes") or "").strip()
    if note:
        out.append(f"> {note}\n")
    return "\n".join(out).strip() + "\n"


def build_project_docs(project_id: int) -> dict:
    project = get_project(project_id)
    root = normalize_project_root(project.root_path, max_length=settings.max_root_path_chars)

    with get_session() as s:
        nodes = s.exec(
            select(FileNode.path, FileNode.language, FileNode.loc, FileNode.complexity, FileNode.fan_in, FileNode.fan_out, FileNode.status)
            .where(FileNode.project_id == project_id)
            .order_by(FileNode.path)
        ).all()
        edges_total_row = s.exec(
            select(func.count()).select_from(FileEdge).where(FileEdge.project_id == project_id)
        ).one()
        edges_total = int(edges_total_row[0] if isinstance(edges_total_row, (tuple, list)) else edges_total_row)

    if not nodes:
        raise BadRequestError("Проект не проиндексирован. Сначала сделай Scan.")

    lang_count: dict[str, int] = {}
    total_loc = 0
    risks: list[dict] = []
    paths: list[str] = []
    for row in nodes:
        try:
            path, language, loc, complexity, fan_in, fan_out, status = row
        except Exception:
            continue
        if not isinstance(path, str) or not path:
            continue
        loc = int(loc or 0)
        complexity = int(complexity or 0)
        fan_in = int(fan_in or 0)
        fan_out = int(fan_out or 0)
        status = str(status or "")
        total_loc += loc
        lang_count[str(language or "unknown")] = lang_count.get(str(language or "unknown"), 0) + 1
        paths.append(path)
        risks.append(_risk_row(path, loc, complexity, fan_in, fan_out, status))

    risks_sorted = sorted(risks, key=lambda x: (-float(x.get("risk", 0.0)), x.get("path", "")))
    hotspots = risks_sorted[:25]

    hubs = sorted(risks, key=lambda x: (-int(x.get("fan_in", 0)), -float(x.get("risk", 0.0)), x.get("path", "")))[:25]
 
    # Module map: top-level folders -> aggregated stats + top hotspots
    module_map: dict[str, dict[str, Any]] = {}
    for r in risks:
        p = str(r.get("path") or "").strip()
        if not p:
            continue
        top = p.split("/", 1)[0] if "/" in p else "."
        m = module_map.get(top)
        if not m:
            m = {"module": top, "files": 0, "loc": 0, "risk_max": 0.0, "top_hotspots": []}
            module_map[top] = m
        m["files"] = int(m["files"]) + 1
        m["loc"] = int(m["loc"]) + int(r.get("loc") or 0)
        risk_v = float(r.get("risk") or 0.0)
        if risk_v > float(m["risk_max"]):
            m["risk_max"] = risk_v
        # keep top 3 hotspots per module
        top_list: list[tuple[float, str]] = list(m["top_hotspots"])
        top_list.append((risk_v, p))
        top_list = sorted(top_list, key=lambda x: (-x[0], x[1]))[:3]
        m["top_hotspots"] = top_list

    module_rows = sorted(
        module_map.values(),
        key=lambda x: (-float(x.get("risk_max") or 0.0), -int(x.get("files") or 0), str(x.get("module") or "")),
    )

    module_table = [
        "| module | files | loc | risk_max | top hotspots |",
        "|---|---:|---:|---:|---|",
    ]
    for m in module_rows[:30]:
        hs = ", ".join([f"`{p}`" for _, p in (m.get("top_hotspots") or [])])
        module_table.append(
            f"| `{m['module']}` | {int(m['files'])} | {int(m['loc'])} | {float(m['risk_max']):.2f} | {hs} |"
        )

    # Contracts for top hotspots (lightweight)
    contracts: list[dict] = []
    contract_paths: list[str] = []

    def _push_path(p: str) -> None:
        if not isinstance(p, str) or not p.strip():
            return
        pp = p.strip()
        if pp not in contract_paths:
            contract_paths.append(pp)

    for item in hotspots[:15]:
        _push_path(str(item.get("path") or ""))

    for item in hubs[:8]:
        _push_path(str(item.get("path") or ""))

    top_fan_out = sorted(risks, key=lambda x: (-int(x.get("fan_out", 0)), -float(x.get("risk", 0.0)), x.get("path", "")))[:8]
    for item in top_fan_out:
        _push_path(str(item.get("path") or ""))

    entry_names = (
        # python
        "main.py", "__main__.py", "app.py", "wsgi.py", "asgi.py", "manage.py",
        # node
        "index.ts", "index.js", "main.ts", "main.js", "server.ts", "server.js", "app.ts", "app.js",
        # go / rust
        "main.go", "main.rs",
        # dotnet
        "Program.cs",
        # java/kotlin
        "Main.java", "Application.java", "Main.kt", "Application.kt",
    )
    entry_candidates = [p for p in paths if isinstance(p, str) and p.endswith(entry_names)]
    for p in sorted(entry_candidates, key=lambda x: (len(x.split("/")), x))[:4]:
        _push_path(p)

    for p in contract_paths[:_MAX_CONTRACTS]:
        try:
            c = get_or_build_contract(project_id, root, p)
            if isinstance(c, dict):
                contracts.append({"path": p, "contract": _compact_contract(c)})
        except Exception:
            continue

    outline = _tree_outline(paths, max_lines=1200)

    hotspots_table = [
        "| # | path | risk | loc | fan_in | fan_out | complexity | status |",
        "|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for i, h in enumerate(hotspots, start=1):
        hotspots_table.append(
            f"| {i} | `{h['path']}` | {h['risk']:.2f} | {h['loc']} | {h['fan_in']} | {h['fan_out']} | {h['complexity']} | {h['status']} |"
        )

    api_summary = _build_api_summary(project_id)
    key_files, key_files_parsed = _collect_key_files(root, paths)
    run_hints = _build_run_hints(key_files, key_files_parsed)

    facts = {
        "project": {"id": project_id, "name": project.name, "root_path": project.root_path},
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "counts": {
            "files": len(paths),
            "edges": edges_total,
            "loc": total_loc,
        },
        "languages": [{"language": k, "files": v} for k, v in sorted(lang_count.items(), key=lambda x: (-x[1], x[0]))],
        "hotspots": hotspots,
        "hubs_by_fan_in": hubs,
        "module_map": module_rows[:100],
        "tree_outline": outline,
        "contracts_sample": contracts,
        "api_summary": api_summary,
        "key_files": key_files,
        "run_hints": run_hints,
        "hotspots_table_md": "\n".join(hotspots_table),
        "module_map_table_md": "\n".join(module_table),
    }

    llm_error: str | None = None
    md = ""
    try:
        llm = generate_docs(facts)
        md = str(llm.get("markdown") or "").strip()
    except Exception as e:
        llm_error = str(e)

    if not md:
        if llm_error:
            md = (
                "## Overview\n\n"
                "> Автогенерация документации через LLM недоступна.\n"
                f"> Причина: {llm_error}\n"
            )
        else:
            md = "## Overview\n\n> Дополнительные разделы не сформированы.\n"

    tree_md = "\n".join(outline["lines"])
    if outline["truncated"]:
        tree_md += "\n\n> (Tree truncated)\n"

    api_md = _api_summary_md(api_summary)
    run_md = ""
    if run_hints:
        run_md = "\n".join([f"- `{h}`" for h in run_hints[:25]]) + "\n"
    else:
        run_md = "> No obvious run commands found in README/Makefile/compose/package manifests.\n"

    key_files_md = ""
    if key_files:
        rows = []
        for kf in key_files[:15]:
            if isinstance(kf, dict):
                p = str(kf.get("path") or "")
                role = str(kf.get("role") or "")
                if p:
                    suffix = f" ({role})" if role else ""
                    rows.append(f"- `{p}`{suffix}")
        key_files_md = "\n".join(rows).strip() + "\n"
    else:
        key_files_md = "> No key files (README/Makefile/compose/pyproject/package.json) were found under the project root.\n"

    final_md = (
        f"# {project.name}\n\n"
        f"**Root:** `{project.root_path}`\n\n"
        f"## Quick stats\n"
        f"- Files: **{len(paths)}**\n"
        f"- Edges: **{edges_total}**\n"
        f"- LOC (non-empty lines): **{total_loc}**\n\n"
        f"## API map (from Scan)\n\n"
        f"{api_md}\n"
        f"## Run hints (best-effort)\n\n"
        f"{run_md}\n"
        f"## Key files found\n\n"
        f"{key_files_md}\n"
        f"## Module map\n\n"
        f"{facts['module_map_table_md']}\n\n"
        f"## Hotspots (top risk)\n\n"
        f"{facts['hotspots_table_md']}\n\n"
        f"## Project tree\n\n{tree_md}\n\n"
        f"---\n\n"
        f"{md}\n"
    ).strip() + "\n"

    with get_session() as s:
        doc = ProjectDoc(project_id=project_id, kind="overview", content_md=final_md)
        s.add(doc)
        s.commit()
        s.refresh(doc)

    return {"project_id": project_id, "kind": "overview", "created_at": doc.created_at.isoformat(), "markdown": final_md}


def get_latest_project_doc(project_id: int, kind: str = "overview") -> dict:
    get_project(project_id)
    with get_session() as s:
        doc = s.exec(
            select(ProjectDoc)
            .where(ProjectDoc.project_id == project_id, ProjectDoc.kind == kind)
            .order_by(ProjectDoc.id.desc())
        ).first()
    if not doc:
        raise NotFoundError("Документация не найдена. Сначала нажми Build docs.", context={"kind": kind})
    return {"project_id": project_id, "kind": doc.kind, "created_at": doc.created_at.isoformat(), "markdown": doc.content_md}
