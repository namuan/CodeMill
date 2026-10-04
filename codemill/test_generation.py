import ast
import re
from pathlib import PurePosixPath

from .tools import CodingTools


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


def _is_test_function(node: ast.AST) -> bool:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
        return True
    return isinstance(node, ast.ClassDef) and any(
        isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        and child.name.startswith("test_")
        for child in node.body
    )
