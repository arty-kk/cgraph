# backend/app/indexers/infra_indexer.py
from __future__ import annotations

import json
import os
import re
import shlex
from typing import Sequence
from pathlib import Path

from .base import ImportRef, SymbolDef

DOCKER_COPY_RE = re.compile(r"^(?P<instr>ADD|COPY)\s+", re.IGNORECASE)
DOCKER_JSON_RE = re.compile(r"^(?P<instr>ADD|COPY)\s+\[", re.IGNORECASE)
COMPOSE_KEY_RE = re.compile(r"^\s*(?P<key>build|context|dockerfile|env_file)\s*:\s*(?P<value>.+)$")
COMPOSE_LIST_RE = re.compile(r"^\s*-\s*(?P<value>.+)$")
COMPOSE_VOLUME_RE = re.compile(r"^\s*-\s*(?P<host>\.?/[^:]+)")

INFRA_BASENAMES = {
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lockb",
    "requirements.txt",
    "requirements-dev.txt",
    "pipfile",
    "pipfile.lock",
    "pyproject.toml",
    "poetry.lock",
    "setup.py",
    "setup.cfg",
    "go.mod",
    "go.sum",
    "go.work",
    "cargo.toml",
    "cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "composer.json",
    "composer.lock",
    "gemfile",
    "gemfile.lock",
    ".gitlab-ci.yml",
}

INFRA_PATH_SNIPPETS = (".github/workflows/",)

DOCKERFILE_PREFIX = "dockerfile"

NODE_ENTRYPOINTS = (
    "src/main.tsx",
    "src/main.ts",
    "src/index.tsx",
    "src/index.ts",
    "src/main.jsx",
    "src/main.js",
    "src/index.jsx",
    "src/index.js",
)

PYTHON_ENTRYPOINTS = (
    "app/main.py",
    "main.py",
    "app.py",
    "__main__.py",
)

GO_ENTRYPOINTS = ("main.go",)

RUST_ENTRYPOINTS = ("src/main.rs",)

INFRA_HINT_FILES = (
    "Dockerfile",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "Pipfile",
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "composer.json",
    "Gemfile",
)


def is_infra_file(path: str | Path) -> bool:
    p = Path(path) if not isinstance(path, Path) else path
    name = p.name.lower()
    if name.startswith(DOCKERFILE_PREFIX):
        return True
    if name in INFRA_BASENAMES:
        return True
    posix = p.as_posix().lower()
    if any(snippet in posix for snippet in INFRA_PATH_SNIPPETS):
        return True
    return False


def _strip_inline_comment(line: str) -> str:
    if "#" not in line:
        return line
    if line.lstrip().startswith("#"):
        return ""
    return line.split("#", 1)[0].rstrip()


def _spec_from_rel(rel: str) -> str | None:
    rel = rel.replace("\\", "/").strip()
    if not rel:
        return None
    if rel.startswith(("http://", "https://", "git://")):
        return None
    if "$" in rel:
        return None
    if rel.startswith("~") or rel.startswith("$"):
        return None
    if rel.startswith("/"):
        return None
    if rel.startswith(("./", "../")):
        return rel
    return f"./{rel}"


def _spec_from_target(importer_dir: Path, target: Path) -> str | None:
    try:
        rel = os.path.relpath(target, importer_dir)
    except Exception:
        rel = str(target)
    return _spec_from_rel(rel)


def _expand_directory_targets(importer_dir: Path, target_dir: Path) -> list[str]:
    specs: list[str] = []
    for rel in INFRA_HINT_FILES:
        cand = target_dir / rel
        if cand.exists() and cand.is_file():
            spec = _spec_from_target(importer_dir, cand)
            if spec:
                specs.append(spec)
    for rel in NODE_ENTRYPOINTS + PYTHON_ENTRYPOINTS + GO_ENTRYPOINTS + RUST_ENTRYPOINTS:
        cand = target_dir / rel
        if cand.exists() and cand.is_file():
            spec = _spec_from_target(importer_dir, cand)
            if spec:
                specs.append(spec)
    return specs


class InfraIndexer:
    def language(self) -> str:
        return "infra"

    def parse_imports(self, file_path: Path, text: str) -> list[ImportRef]:
        name = file_path.name.lower()
        if name.startswith(DOCKERFILE_PREFIX):
            return self._parse_dockerfile(file_path, text)
        if name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
            return self._parse_compose(file_path, text)
        if name == "package.json":
            return self._parse_package_json(file_path, text)
        return self._parse_manifest_links(file_path, text)

    def parse_exports(self, file_path: Path, text: str) -> list[str]:
        return []

    def parse_symbols(self, file_path: Path, text: str) -> list[SymbolDef]:
        return []

    def naive_complexity(self, text: str) -> int:
        return 1

    def _parse_dockerfile(self, file_path: Path, text: str) -> list[ImportRef]:
        importer_dir = file_path.parent
        out: list[ImportRef] = []
        for line in text.splitlines():
            raw_line = line
            line = _strip_inline_comment(line.strip())
            if not line:
                continue
            if not DOCKER_COPY_RE.match(line):
                continue
            line = re.sub(r"^(?i)(add|copy)\s+", "", line).strip()
            if DOCKER_JSON_RE.match(raw_line.strip()):
                try:
                    arr = json.loads(re.sub(r"^(?i)(add|copy)\s+", "", raw_line.strip()))
                except Exception:
                    arr = None
                if isinstance(arr, list) and len(arr) >= 2:
                    sources = arr[:-1]
                else:
                    sources = []
            else:
                try:
                    parts = shlex.split(line)
                except Exception:
                    parts = line.split()
                sources = []
                for part in parts:
                    if part.startswith("--"):
                        continue
                    sources.append(part)
                if len(sources) >= 2:
                    sources = sources[:-1]
                else:
                    sources = []
            for src in sources:
                if any(ch in src for ch in ["*", "?", "["]):
                    continue
                spec = _spec_from_rel(src)
                if not spec:
                    continue
                abs_src = (importer_dir / spec).resolve()
                if abs_src.exists() and abs_src.is_dir():
                    for dir_spec in _expand_directory_targets(importer_dir, abs_src):
                        out.append(
                            ImportRef(raw=raw_line.strip(), spec=dir_spec, kind="docker-copy")
                        )
                else:
                    out.append(ImportRef(raw=raw_line.strip(), spec=spec, kind="docker-copy"))
        return out

    def _parse_compose(self, file_path: Path, text: str) -> list[ImportRef]:
        importer_dir = file_path.parent
        out: list[ImportRef] = []
        build_contexts: list[str] = []
        dockerfiles: list[str] = []
        env_files: list[str] = []
        volume_hosts: list[str] = []

        for line in text.splitlines():
            line = _strip_inline_comment(line.rstrip())
            if not line.strip():
                continue
            match = COMPOSE_KEY_RE.match(line)
            if match:
                key = match.group("key")
                value = match.group("value").strip().strip("'\"")
                if key == "build":
                    build_contexts.append(value)
                elif key == "context":
                    build_contexts.append(value)
                elif key == "dockerfile":
                    dockerfiles.append(value)
                elif key == "env_file":
                    env_files.append(value)
                continue
            list_match = COMPOSE_LIST_RE.match(line)
            if list_match:
                value = list_match.group("value").strip().strip("'\"")
                if value and (value.startswith(("./", "../", ".env")) or value.endswith(".env")):
                    env_files.append(value)
            vol_match = COMPOSE_VOLUME_RE.match(line)
            if vol_match:
                volume_hosts.append(vol_match.group("host").strip())

        def _add_paths(paths: list[str], kind: str) -> None:
            for pth in paths:
                spec = _spec_from_rel(pth)
                if not spec:
                    continue
                abs_path = (importer_dir / spec).resolve()
                if abs_path.exists() and abs_path.is_dir():
                    for dir_spec in _expand_directory_targets(importer_dir, abs_path):
                        out.append(ImportRef(raw=pth, spec=dir_spec, kind=kind))
                else:
                    out.append(ImportRef(raw=pth, spec=spec, kind=kind))

        _add_paths(build_contexts, "compose-build")
        _add_paths(dockerfiles, "compose-dockerfile")
        _add_paths(env_files, "compose-env")
        _add_paths(volume_hosts, "compose-volume")

        return out

    def _parse_package_json(self, file_path: Path, text: str) -> list[ImportRef]:
        out: list[ImportRef] = []
        importer_dir = file_path.parent
        try:
            data = json.loads(text)
        except Exception:
            data = {}
        if isinstance(data, dict):
            for key in ("main", "module", "types", "typings", "browser"):
                value = data.get(key)
                if isinstance(value, str):
                    spec = _spec_from_rel(value)
                    if spec:
                        out.append(ImportRef(raw=f"{key}: {value}", spec=spec, kind="manifest"))
            bin_field = data.get("bin")
            if isinstance(bin_field, str):
                spec = _spec_from_rel(bin_field)
                if spec:
                    out.append(ImportRef(raw=f"bin: {bin_field}", spec=spec, kind="manifest"))
            elif isinstance(bin_field, dict):
                for value in bin_field.values():
                    if isinstance(value, str):
                        spec = _spec_from_rel(value)
                        if spec:
                            out.append(ImportRef(raw=f"bin: {value}", spec=spec, kind="manifest"))
            exports_field = data.get("exports")
            if isinstance(exports_field, str):
                spec = _spec_from_rel(exports_field)
                if spec:
                    out.append(
                        ImportRef(raw=f"exports: {exports_field}", spec=spec, kind="manifest")
                    )
            elif isinstance(exports_field, dict):
                for value in exports_field.values():
                    if isinstance(value, str):
                        spec = _spec_from_rel(value)
                        if spec:
                            out.append(
                                ImportRef(raw=f"exports: {value}", spec=spec, kind="manifest")
                            )
                    elif isinstance(value, dict):
                        for sub_value in value.values():
                            if isinstance(sub_value, str):
                                spec = _spec_from_rel(sub_value)
                                if spec:
                                    out.append(
                                        ImportRef(
                                            raw=f"exports: {sub_value}", spec=spec, kind="manifest"
                                        )
                                    )
        for lock_name in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lockb"):
            lock_path = importer_dir / lock_name
            if lock_path.exists() and lock_path.is_file():
                spec = _spec_from_target(importer_dir, lock_path)
                if spec:
                    out.append(ImportRef(raw=lock_name, spec=spec, kind="manifest-lock"))
        for rel in NODE_ENTRYPOINTS:
            entry_path = importer_dir / rel
            if entry_path.exists() and entry_path.is_file():
                spec = _spec_from_target(importer_dir, entry_path)
                if spec:
                    out.append(ImportRef(raw=rel, spec=spec, kind="manifest-entry"))
        return out

    def _parse_manifest_links(self, file_path: Path, text: str) -> list[ImportRef]:
        importer_dir = file_path.parent
        name = file_path.name
        out: list[ImportRef] = []
        manifest_links = {
            "poetry.lock": "pyproject.toml",
            "pipfile.lock": "Pipfile",
            "cargo.lock": "Cargo.toml",
            "composer.lock": "composer.json",
            "gemfile.lock": "Gemfile",
            "go.sum": "go.mod",
            "package-lock.json": "package.json",
            "pnpm-lock.yaml": "package.json",
            "yarn.lock": "package.json",
            "bun.lockb": "package.json",
            "requirements-dev.txt": "requirements.txt",
        }
        peer = manifest_links.get(name.lower())
        if peer:
            peer_path = importer_dir / peer
            if peer_path.exists() and peer_path.is_file():
                spec = _spec_from_target(importer_dir, peer_path)
                if spec:
                    out.append(ImportRef(raw=peer, spec=spec, kind="manifest-peer"))

        entrypoints: Sequence[str] = ()
        lower_name = name.lower()
        if lower_name in {
            "requirements.txt",
            "requirements-dev.txt",
            "pipfile",
            "pipfile.lock",
            "pyproject.toml",
        }:
            entrypoints = PYTHON_ENTRYPOINTS
        elif lower_name in {"go.mod", "go.sum", "go.work"}:
            entrypoints = GO_ENTRYPOINTS
        elif lower_name in {"cargo.toml", "cargo.lock"}:
            entrypoints = RUST_ENTRYPOINTS

        for rel in entrypoints:
            entry_path = importer_dir / rel
            if entry_path.exists() and entry_path.is_file():
                spec = _spec_from_target(importer_dir, entry_path)
                if spec:
                    out.append(ImportRef(raw=rel, spec=spec, kind="manifest-entry"))
        return out
