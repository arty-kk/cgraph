#backend/app/indexers/python_indexer.py
from __future__ import annotations

import ast
from pathlib import Path
from .base import ImportRef, SymbolDef

_TYPE_CHECKING_MODULES = {"typing", "typing_extensions"}
_IMPORTLIB_MODULES = {"importlib"}

def _is_type_checking_test(
    test: ast.AST,
    *,
    typing_names: set[str],
    type_checking_names: set[str],
) -> bool:
    if isinstance(test, ast.Name) and test.id in type_checking_names:
        return True
    if isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING":
        v = test.value
        if isinstance(v, ast.Name) and v.id in typing_names:
            return True
    return False

def _collect_type_checking_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    typing_names = set(_TYPE_CHECKING_MODULES)
    type_checking_names = {"TYPE_CHECKING"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = getattr(alias, "name", "")
                if name in _TYPE_CHECKING_MODULES:
                    typing_names.add(alias.asname or name)
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "") in _TYPE_CHECKING_MODULES:
                for alias in node.names:
                    if getattr(alias, "name", "") != "TYPE_CHECKING":
                        continue
                    type_checking_names.add(alias.asname or "TYPE_CHECKING")

    return typing_names, type_checking_names

def _collect_importlib_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    module_names = set(_IMPORTLIB_MODULES)
    import_module_names = {"import_module"}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = getattr(alias, "name", "")
                if name in _IMPORTLIB_MODULES:
                    module_names.add(alias.asname or name)
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "") in _IMPORTLIB_MODULES:
                for alias in node.names:
                    if getattr(alias, "name", "") == "import_module":
                        import_module_names.add(alias.asname or "import_module")

    return module_names, import_module_names

def _collect_assigned_names(t: ast.AST) -> list[str]:
    if isinstance(t, ast.Name):
        return [t.id]
    if isinstance(t, (ast.Tuple, ast.List)):
        out: list[str] = []
        for elt in t.elts:
            out.extend(_collect_assigned_names(elt))
        return out
    return []

def _literal_str_seq(node: ast.AST) -> list[str] | None:
    try:
        v = ast.literal_eval(node)
    except Exception:
        return None
    if not isinstance(v, (list, tuple)):
        return None
    out: list[str] = []
    for x in v:
        if not isinstance(x, str):
            return None
        out.append(x)
    return out

def _literal_str(node: ast.AST) -> str | None:
    try:
        v = ast.literal_eval(node)
    except Exception:
        return None
    return v if isinstance(v, str) else None

def _extract_dunder_all(tree: ast.Module) -> list[str] | None:
    # Only return when we can confidently evaluate __all__ as literals.
    values: list[str] | None = None

    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "__all__" for t in stmt.targets):
                seq = _literal_str_seq(stmt.value)
                if seq is not None:
                    values = list(seq)
        elif isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name) and stmt.target.id == "__all__" and stmt.value is not None:
                seq = _literal_str_seq(stmt.value)
                if seq is not None:
                    values = list(seq)
        elif isinstance(stmt, ast.AugAssign):
            if (
                values is not None
                and isinstance(stmt.target, ast.Name)
                and stmt.target.id == "__all__"
                and isinstance(stmt.op, ast.Add)
            ):
                seq = _literal_str_seq(stmt.value)
                if seq is not None:
                    values.extend(seq)
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            if values is None:
                continue
            call = stmt.value
            func = call.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "__all__"):
                continue
            if func.attr == "extend" and call.args:
                seq = _literal_str_seq(call.args[0])
                if seq is not None:
                    values.extend(seq)
            elif func.attr == "append" and call.args:
                s = _literal_str(call.args[0])
                if s is not None:
                    values.append(s)

    if values is None:
        return None
    seen: set[str] = set()
    out: list[str] = []
    for x in values:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def _safe_unparse(node: ast.AST) -> str:
    unparse = getattr(ast, "unparse", None)
    if callable(unparse):
        try:
            return str(unparse(node))
        except Exception:
            return ""
    return ""

def _dynamic_kind(kind: str) -> str:
    return "type_dynamic" if kind == "type" else "dynamic"

def _format_function_signature(node: ast.AST) -> str:

    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return ""
    args = node.args

    def fmt_arg(a: ast.arg) -> str:
        s = a.arg
        if a.annotation is not None:
            ann = _safe_unparse(a.annotation)
            if ann:
                s += f": {ann}"
        return s

    parts: list[str] = []
    pos = list(args.posonlyargs or []) + list(args.args or [])
    defaults = list(args.defaults or [])
    default_start = len(pos) - len(defaults)
    for i, a in enumerate(pos):
        s = fmt_arg(a)
        if i >= default_start and (i - default_start) < len(defaults):
            dv = defaults[i - default_start]
            dd = _safe_unparse(dv)
            s += f"={dd}" if dd else "=..."
        parts.append(s)
        if args.posonlyargs and i == (len(args.posonlyargs) - 1):
            parts.append("/")

    if args.vararg is not None:
        s = "*" + fmt_arg(args.vararg)
        parts.append(s)
    elif args.kwonlyargs:
        parts.append("*")

    kw_defaults = list(args.kw_defaults or [])
    for i, a in enumerate(list(args.kwonlyargs or [])):
        s = fmt_arg(a)
        if i < len(kw_defaults) and kw_defaults[i] is not None:
            dd = _safe_unparse(kw_defaults[i])
            s += f"={dd}" if dd else "=..."
        parts.append(s)

    if args.kwarg is not None:
        parts.append("**" + fmt_arg(args.kwarg))

    ret = ""
    if getattr(node, "returns", None) is not None:
        rr = _safe_unparse(node.returns)  # type: ignore[arg-type]
        if rr:
            ret = f" -> {rr}"
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return f"{prefix}{node.name}({', '.join([p for p in parts if p])}){ret}"

def _format_class_signature(node: ast.AST) -> str:
    if not isinstance(node, ast.ClassDef):
        return ""
    bases = []
    for b in list(node.bases or []):
        u = _safe_unparse(b)
        if u:
            bases.append(u)
    if bases:
        return f"{node.name}({', '.join(bases)})"
    return node.name

class PythonIndexer:
    def language(self) -> str:
        return "python"

    def parse_imports(self, file_path: Path, text: str) -> list[ImportRef]:
        imports: list[ImportRef] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return imports
        typing_names, type_checking_names = _collect_type_checking_aliases(tree)
        importlib_module_names, import_module_names = _collect_importlib_aliases(tree)

        def _walk(n: ast.AST, *, kind: str) -> None:
            # Mark imports under TYPE_CHECKING as type-only edges.
            if isinstance(n, ast.If) and _is_type_checking_test(
                n.test,
                typing_names=typing_names,
                type_checking_names=type_checking_names,
            ):
                for ch in n.body:
                    _walk(ch, kind="type")
                for ch in n.orelse:
                    _walk(ch, kind=kind)
                return

            if isinstance(n, ast.Import):
                for alias in n.names:
                    if alias.name:
                        imports.append(ImportRef(raw=f"import {alias.name}", spec=alias.name, kind=kind))
                return

            if isinstance(n, ast.ImportFrom):
                module = n.module or ""
                level = n.level or 0
                prefix = "." * level
                if module:
                    spec = prefix + module
                    imports.append(ImportRef(raw=f"from {spec} import ...", spec=spec, kind=kind))
                else:
                    for alias in getattr(n, "names", []) or []:
                        name = getattr(alias, "name", "") or ""
                        if not name:
                            continue
                        if name == "*":
                            spec = prefix or "."
                            imports.append(ImportRef(raw=f"from {spec} import *", spec=spec, kind=kind))
                        else:
                            spec = prefix + name
                            raw_prefix = (prefix or ".")
                            imports.append(ImportRef(raw=f"from {raw_prefix} import {name}", spec=spec, kind=kind))
                return

            if isinstance(n, ast.Call):
                func = n.func
                spec = _literal_str(n.args[0]) if n.args else None
                if spec:
                    if isinstance(func, ast.Name):
                        if func.id in import_module_names or func.id == "__import__":
                            raw = _safe_unparse(n) or f"{func.id}(...)"
                            imports.append(ImportRef(raw=raw, spec=spec, kind=_dynamic_kind(kind)))
                    elif isinstance(func, ast.Attribute):
                        if func.attr == "import_module":
                            v = func.value
                            if isinstance(v, ast.Name) and v.id in importlib_module_names:
                                raw = _safe_unparse(n) or "importlib.import_module(...)"
                                imports.append(ImportRef(raw=raw, spec=spec, kind=_dynamic_kind(kind)))

            for ch in ast.iter_child_nodes(n):
                _walk(ch, kind=kind)

        _walk(tree, kind="runtime")
        return imports

    def parse_module_doc(self, file_path: Path, text: str) -> str:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return ""
        return (ast.get_docstring(tree) or "").strip()

    def parse_exports(self, file_path: Path, text: str) -> list[str]:
        exports: list[str] = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return exports

        all_list = _extract_dunder_all(tree)
        if all_list is not None:
            return all_list

        for node in tree.body:
            TypeAlias = getattr(ast, "TypeAlias", None)
            if TypeAlias is not None and isinstance(node, TypeAlias):
                name = getattr(node, "name", None)
                if isinstance(name, ast.Name):
                    exports.append(name.id)
                elif isinstance(name, str):
                    exports.append(name)
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                exports.append(node.name)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    exports.extend(_collect_assigned_names(t))
            elif isinstance(node, ast.AnnAssign):
                exports.extend(_collect_assigned_names(node.target))
        seen = set()
        out: list[str] = []
        for e in exports:
            if e not in seen and not e.startswith("_"):
                seen.add(e)
                out.append(e)
        return out

    def parse_symbols(self, file_path: Path, text: str) -> list[SymbolDef]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []

        MAX_DOC = 800
        out: list[SymbolDef] = []
        seen: set[tuple[str, str, int, int]] = set()

        def add(sym: SymbolDef) -> None:
            if not sym.name:
                return
            k = (sym.kind, sym.name, int(sym.start_line), int(sym.end_line))
            if k in seen:
                return
            seen.add(k)
            out.append(sym)

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = (ast.get_docstring(node) or "").strip()
                start = int(getattr(node, "lineno", 0) or 0)
                end = int(getattr(node, "end_lineno", start) or start)
                add(
                    SymbolDef(
                        name=node.name,
                        kind="function",
                        signature=_format_function_signature(node),
                        doc=doc[:MAX_DOC],
                        start_line=start,
                        end_line=end,
                    )
                )
                continue

            if isinstance(node, ast.ClassDef):
                doc = (ast.get_docstring(node) or "").strip()
                start = int(getattr(node, "lineno", 0) or 0)
                end = int(getattr(node, "end_lineno", start) or start)
                add(
                    SymbolDef(
                        name=node.name,
                        kind="class",
                        signature=_format_class_signature(node),
                        doc=doc[:MAX_DOC],
                        start_line=start,
                        end_line=end,
                    )
                )
                continue

            TypeAlias = getattr(ast, "TypeAlias", None)
            if TypeAlias is not None and isinstance(node, TypeAlias):
                name = getattr(node, "name", None)
                if isinstance(name, ast.Name):
                    nm = name.id
                elif isinstance(name, str):
                    nm = name
                else:
                    nm = ""
                start = int(getattr(node, "lineno", 0) or 0)
                end = int(getattr(node, "end_lineno", start) or start)
                add(SymbolDef(name=nm, kind="type", signature=nm, doc="", start_line=start, end_line=end))
                continue

            if isinstance(node, ast.Assign):
                start = int(getattr(node, "lineno", 0) or 0)
                end = int(getattr(node, "end_lineno", start) or start)
                for t in node.targets:
                    for nm in _collect_assigned_names(t):
                        add(SymbolDef(name=nm, kind="variable", signature=nm, doc="", start_line=start, end_line=end))
                continue

            if isinstance(node, ast.AnnAssign):
                start = int(getattr(node, "lineno", 0) or 0)
                end = int(getattr(node, "end_lineno", start) or start)
                for nm in _collect_assigned_names(node.target):
                    add(SymbolDef(name=nm, kind="variable", signature=nm, doc="", start_line=start, end_line=end))

        filtered = [s for s in out if s.name and not s.name.startswith("_")]
        return filtered

    def naive_complexity(self, text: str) -> int:
        keywords = ["if ", "for ", "while ", " and ", " or ", "elif ", "except ", "case "]
        c = 1
        low = text.lower()
        for k in keywords:
            c += low.count(k)
        return c
