import json
import shutil
import subprocess
from pathlib import Path


class LocalRepositoryTools:
    def __init__(
        self,
        root: str | Path,
        search_timeout: float = 5.0,
        max_search_output_chars: int = 100_000,
    ):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("repository root must be a directory")
        self.search_timeout = search_timeout
        self.max_search_output_chars = max_search_output_chars
        self.rg_path = shutil.which("rg")
        self.ast_grep_path = shutil.which("ast-grep")
        if self.rg_path is None:
            raise RuntimeError("ripgrep executable 'rg' is required")

    def list_tree(self, path: str = ".", depth: int = 2) -> tuple[str, ...]:
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
            raise ValueError("depth must be a non-negative integer")
        directory = self._resolve_directory(path)
        entries: list[str] = []
        excluded_directories = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"}

        def visit(current: Path, level: int) -> None:
            if level >= depth:
                return
            for child in sorted(current.iterdir(), key=lambda entry: entry.name.casefold()):
                if child.is_dir() and not child.is_symlink() and child.name in excluded_directories:
                    continue
                relative = child.relative_to(directory).as_posix()
                is_directory = child.is_dir() and not child.is_symlink()
                entries.append(f"{relative}/" if is_directory else relative)
                if is_directory:
                    visit(child, level + 1)

        visit(directory, 0)
        return tuple(entries)

    def read_file(
        self,
        path: str,
        start: int | None = None,
        end: int | None = None,
    ) -> str:
        file_path = self._resolve_file(path)
        if start is not None and (not isinstance(start, int) or start < 1):
            raise ValueError("start must be a positive line number")
        if end is not None and (not isinstance(end, int) or end < 1):
            raise ValueError("end must be a positive line number")
        if start is not None and end is not None and end < start:
            raise ValueError("end must not precede start")

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("file is not valid UTF-8 text") from error

        lines = content.splitlines(keepends=True)
        first = 0 if start is None else start - 1
        last = len(lines) if end is None else end
        return "".join(lines[first:last])

    def find_definitions(self, name: str) -> str:
        if not name.strip():
            raise ValueError("name must not be empty")
        if self.ast_grep_path is None:
            raise RuntimeError("ast-grep executable 'ast-grep' is required")
        try:
            result = subprocess.run(
                [
                    self.ast_grep_path,
                    "outline",
                    "-l",
                    "python",
                    "--json=compact",
                    "--view=expanded",
                    "--color",
                    "never",
                    ".",
                ],
                cwd=self.root,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.search_timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("structural search timed out") from error
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "structural search failed")

        try:
            files = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as error:
            raise RuntimeError("ast-grep returned invalid JSON") from error

        matches = []
        for file_result in files:
            for item in file_result.get("items", []):
                for candidate in self._outline_items(item):
                    if candidate.get("name") == name:
                        matches.append(
                            {
                                "path": Path(file_result["path"]).as_posix(),
                                "name": candidate["name"],
                                "kind": candidate.get("symbolType", ""),
                                "signature": candidate.get("signature", ""),
                                "line": candidate["range"]["start"]["line"] + 1,
                            }
                        )
        return json.dumps(matches)

    def find_structural(self, pattern: str, language: str = "python") -> str:
        if not pattern.strip():
            raise ValueError("pattern must not be empty")
        if language != "python":
            raise ValueError("language must be python")
        if self.ast_grep_path is None:
            raise RuntimeError("ast-grep executable 'ast-grep' is required")
        try:
            result = subprocess.run(
                [
                    self.ast_grep_path,
                    "run",
                    "--json=compact",
                    "--color",
                    "never",
                    "--pattern",
                    pattern,
                    "--lang",
                    language,
                    ".",
                ],
                cwd=self.root,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.search_timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("structural search timed out") from error
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "structural search failed")

        try:
            raw_matches = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as error:
            raise RuntimeError("ast-grep returned invalid JSON") from error
        matches = [
            {
                "path": Path(match["file"]).as_posix(),
                "text": match["text"],
                "start_line": match["range"]["start"]["line"] + 1,
                "end_line": match["range"]["end"]["line"] + 1,
            }
            for match in raw_matches
        ]
        output = json.dumps(matches)
        if len(output) > self.max_search_output_chars:
            raise RuntimeError("structural search output exceeded the configured limit")
        return output

    def search_text(self, query: str) -> str:
        if not query.strip():
            raise ValueError("query must not be empty")
        try:
            result = subprocess.run(
                [
                    self.rg_path,
                    "--line-number",
                    "--no-heading",
                    "--color",
                    "never",
                    "--fixed-strings",
                    "--max-count",
                    "500",
                    "--max-columns",
                    "300",
                    "--max-columns-preview",
                    "--",
                    query,
                    ".",
                ],
                cwd=self.root,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.search_timeout,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("text search timed out") from error
        if result.returncode == 1:
            return ""
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "text search failed")
        output = result.stdout
        if len(output) > self.max_search_output_chars:
            return output[: self.max_search_output_chars] + "\n[output truncated]"
        return output

    @classmethod
    def _outline_items(cls, item: dict) -> tuple[dict, ...]:
        children = tuple(
            candidate
            for member in item.get("members", [])
            for candidate in cls._outline_items(member)
        )
        return (item, *children)

    def _resolve_directory(self, path: str) -> Path:
        relative_path = Path(path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("path escapes repository root")
        try:
            resolved = (self.root / relative_path).resolve(strict=True)
        except FileNotFoundError as error:
            raise ValueError("directory does not exist") from error
        try:
            resolved.relative_to(self.root)
        except ValueError as error:
            raise ValueError("path escapes repository root") from error
        if not resolved.is_dir():
            raise ValueError("path is not a directory")
        return resolved

    def _resolve_file(self, path: str) -> Path:
        relative_path = Path(path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("path escapes repository root")
        try:
            resolved = (self.root / relative_path).resolve(strict=True)
        except FileNotFoundError as error:
            raise ValueError("file does not exist") from error
        try:
            resolved.relative_to(self.root)
        except ValueError as error:
            raise ValueError("path escapes repository root") from error
        if not resolved.is_file():
            raise ValueError("path is not a regular file")
        return resolved
