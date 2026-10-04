import ast
import re
from pathlib import PurePosixPath

from .models import SubTask
from .tools import CodingTools


def requested_class_methods(
    task: SubTask,
    tools: CodingTools | None = None,
) -> tuple[tuple[str, str], ...]:
    task_text = " ".join((task.objective, *task.acceptance_criteria))
    explicit = tuple(
        dict.fromkeys(re.findall(r"\b([A-Z][A-Za-z_0-9]*)\.([A-Za-z_][A-Za-z_0-9]*)", task_text))
    )
    if explicit or tools is None:
        return explicit
    methods = tuple(
        dict.fromkeys(re.findall(r"\b([a-z_][A-Za-z_0-9]*)\s*\(", task.objective))
    )
    paths = re.findall(r"\b([A-Za-z0-9_./-]+\.py)\b", task_text)
    for path in paths:
        if path.startswith("/") or ".." in PurePosixPath(path).parts:
            continue
        try:
            module = ast.parse(tools.read_file(path))
        except (SyntaxError, ValueError):
            continue
        classes = [node for node in ast.walk(module) if isinstance(node, ast.ClassDef)]
        if len(classes) == 1:
            return tuple((classes[0].name, method) for method in methods)
    return ()


def prepare_test_module(
    source: str,
    task: SubTask,
    tools: CodingTools | None = None,
) -> tuple[str, tuple[str, ...]]:
    try:
        module = ast.parse(source)
    except SyntaxError as error:
        raise ValueError(f"test module has invalid Python syntax: {error}") from error

    requested_methods = requested_class_methods(task, tools)
    source = _normalize_guard_messages(source, module, requested_methods)
    module = ast.parse(source)
    source_lines = source.splitlines(keepends=True)
    if source_lines and not source_lines[-1].endswith(("\n", "\r")):
        source_lines[-1] += "\n"
    insertions: dict[int, list[str]] = {}
    guarded_symbols = set()
    for class_name, method_name in requested_methods:
        for function in ast.walk(module):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or not function.name.startswith(
                "test_"
            ):
                continue
            for statement in function.body:
                call = next(
                    (
                        node
                        for node in ast.walk(statement)
                        if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == method_name
                    ),
                    None,
                )
                if call is None:
                    continue
                receiver = call.func.value
                if isinstance(receiver, ast.Call) and isinstance(receiver.func, (ast.Name, ast.Attribute)):
                    receiver = receiver.func
                receiver_text = ast.get_source_segment(source, receiver)
                if not receiver_text:
                    continue
                line_index = statement.lineno - 1
                indentation = source_lines[line_index][: len(source_lines[line_index]) - len(source_lines[line_index].lstrip())]
                guard = (
                    f"{indentation}assert callable(getattr({receiver_text}, {method_name!r}, None)), "
                    f"{class_name}.{method_name} is missing\n"
                )
                insertions.setdefault(line_index, []).append(guard)
                guarded_symbols.add(f"{class_name}.{method_name}")
                break

    for line_index in sorted(insertions, reverse=True):
        source_lines[line_index:line_index] = insertions[line_index]

    uses_pytest = any(isinstance(node, ast.Name) and node.id == "pytest" for node in ast.walk(module))
    imports_pytest = any(
        isinstance(node, ast.Import)
        and any(alias.name == "pytest" and alias.asname in {None, "pytest"} for alias in node.names)
        for node in ast.walk(module)
    )
    if uses_pytest and not imports_pytest:
        insertion_index = _pytest_import_line(module)
        source_lines.insert(insertion_index, "import pytest\n")

    prepared = "".join(source_lines)
    try:
        ast.parse(prepared)
    except SyntaxError as error:
        raise ValueError(f"prepared test module has invalid Python syntax: {error}") from error
    return prepared, tuple(sorted(guarded_symbols))


def build_test_file_patch(source: str, subtask_id: str, tools: CodingTools) -> str:
    if not isinstance(source, str) or not source.strip():
        raise ValueError("test module source must not be empty")
    try:
        module = ast.parse(source)
    except SyntaxError as error:
        raise ValueError(f"test module has invalid Python syntax: {error}") from error
    if not any(_is_test_function(node) for node in ast.walk(module)):
        raise ValueError("test module must define at least one test function")

    path = _new_test_path(subtask_id, tools)
    lines = source.rstrip("\n").splitlines()
    return "\n".join(
        (
            f"diff --git a/{path} b/{path}",
            "new file mode 100644",
            "--- /dev/null",
            f"+++ b/{path}",
            f"@@ -0,0 +1,{len(lines)} @@",
            *(f"+{line}" for line in lines),
            "",
        )
    )


def _new_test_path(subtask_id: str, tools: CodingTools) -> str:
    tree = tools.list_tree(".", depth=4)
    test_directories = [
        entry.rstrip("/")
        for entry in tree
        if entry.endswith("/") and PurePosixPath(entry.rstrip("/")).name.lower() in {"test", "tests"}
    ]
    if test_directories:
        root = min(
            test_directories,
            key=lambda path: (
                0 if PurePosixPath(path).name.lower() == "tests" else 1,
                len(PurePosixPath(path).parts),
                path,
            ),
        )
        root_entries = tools.list_tree(root, depth=1)
    else:
        root = ""
        root_entries = tree

    slug = re.sub(r"[^a-z0-9]+", "_", subtask_id.lower()).strip("_") or "slice"
    existing = {
        f"{root}/{entry}" if root else entry
        for entry in root_entries
        if not entry.endswith("/")
    }
    base = f"test_codemill_{slug}"
    suffix = 1
    while True:
        filename = f"{base}.py" if suffix == 1 else f"{base}_{suffix}.py"
        path = f"{root}/{filename}" if root else filename
        if path not in existing:
            return path
        suffix += 1


def _normalize_guard_messages(
    source: str,
    module: ast.Module,
    requested_methods: tuple[tuple[str, str], ...],
) -> str:
    owners = {method: class_name for class_name, method in requested_methods}
    replacements = []
    for node in ast.walk(module):
        if not isinstance(node, ast.Assert) or node.msg is None:
            continue
        method = _assert_guard_method(node.test)
        if method not in owners or (
            isinstance(node.msg, ast.Constant) and isinstance(node.msg.value, str)
        ):
            continue
        start = _source_offset(source, node.msg.lineno, node.msg.col_offset)
        end = _source_offset(source, node.msg.end_lineno, node.msg.end_col_offset)
        replacements.append((start, end, repr(f"{owners[method]}.{method} is missing")))
    for start, end, replacement in sorted(replacements, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source


def _assert_guard_method(node: ast.AST) -> str | None:
    for call in ast.walk(node):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        if call.func.id != "callable" or not call.args:
            continue
        lookup = call.args[0]
        if (
            isinstance(lookup, ast.Call)
            and isinstance(lookup.func, ast.Name)
            and lookup.func.id == "getattr"
            and len(lookup.args) > 1
            and isinstance(lookup.args[1], ast.Constant)
            and isinstance(lookup.args[1].value, str)
        ):
            return lookup.args[1].value
    return None


def _source_offset(source: str, line: int, column: int) -> int:
    return sum(len(content) for content in source.splitlines(keepends=True)[: line - 1]) + column


def _pytest_import_line(module: ast.Module) -> int:
    body = module.body
    insertion_index = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            insertion_index = body[0].end_lineno
    for node in body:
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            insertion_index = max(insertion_index, node.end_lineno)
    return insertion_index


def _is_test_function(node: ast.AST) -> bool:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
        return True
    return isinstance(node, ast.ClassDef) and any(
        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        and child.name.startswith("test_")
        for child in node.body
    )
