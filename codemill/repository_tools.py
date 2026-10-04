import ast
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .models import (
    ExpectedScope,
    GitStatus,
    ProtectedTestMutationError,
    ProtectedTests,
    ScopeViolationError,
    VerificationTarget,
)


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
        self.git_path = shutil.which("git")
        if self.rg_path is None:
            raise RuntimeError("ripgrep executable 'rg' is required")
        self._initial_clean_checked = False
        self._active_test_patch: tuple[str, tuple[str, ...]] | None = None
        self._test_paths: set[str] = set()
        self._protected_tests: ProtectedTests | None = None
        self._patch_log: list[tuple[str, str]] = []

    def apply_test_patch(
        self,
        patch: str,
        scope: ExpectedScope | None = None,
        checkpoint: int | None = None,
        task_scope: ExpectedScope | None = None,
        task_checkpoint: int | None = None,
    ) -> VerificationTarget:
        if self._active_test_patch is not None:
            raise RuntimeError("a test patch is already awaiting RED verification")
        self._ensure_clean_git_repository()
        paths = self._parse_patch_paths(patch)
        if any(not self._is_test_path(path) for path in paths):
            raise ValueError("test patch may only modify test files")
        if self._test_paths.intersection(paths):
            raise ProtectedTestMutationError("test patch may not modify an already protected test")
        self._validate_scope(patch, scope, checkpoint)
        self._validate_scope(patch, task_scope, task_checkpoint)
        self._apply_git_patch(patch)
        self._active_test_patch = (patch, paths)
        self._patch_log.append(("test", patch))
        return VerificationTarget(paths)

    def discard_test_patch(self) -> None:
        if self._active_test_patch is None:
            raise RuntimeError("there is no unaccepted test patch to discard")
        patch, _ = self._active_test_patch
        self._apply_git_patch(patch, reverse=True)
        self._patch_log.pop()
        self._active_test_patch = None

    def freeze_tests(self) -> ProtectedTests:
        if self._active_test_patch is None:
            raise RuntimeError("there is no RED-confirmed test patch to freeze")
        _, paths = self._active_test_patch
        self._test_paths.update(paths)
        protected = ProtectedTests(
            tuple(sorted(self._test_paths)),
            self._fingerprint(self._test_paths),
        )
        self._protected_tests = protected
        self._active_test_patch = None
        return protected

    def apply_production_patch(
        self,
        patch: str,
        protected_tests: ProtectedTests,
        scope: ExpectedScope | None = None,
        checkpoint: int | None = None,
        task_scope: ExpectedScope | None = None,
        task_checkpoint: int | None = None,
    ) -> None:
        if self._protected_tests is None or protected_tests != self._protected_tests:
            raise PermissionError("protected test set does not match the active run")
        if self._fingerprint(protected_tests.paths) != protected_tests.fingerprint:
            raise ProtectedTestMutationError("protected test fingerprint changed before patching")
        paths = self._parse_patch_paths(patch)
        if any(self._is_test_path(path) for path in paths):
            raise ProtectedTestMutationError("production patch may not modify test files")
        self._validate_scope(patch, scope, checkpoint)
        self._validate_scope(patch, task_scope, task_checkpoint)
        self._apply_git_patch(patch)
        if self._fingerprint(protected_tests.paths) != protected_tests.fingerprint:
            self._apply_git_patch(patch, reverse=True)
            raise ProtectedTestMutationError("production patch modified a protected test")
        self._patch_log.append(("production", patch))

    def git_status(self) -> GitStatus:
        self._require_git()
        root = self._git_output("rev-parse", "--show-toplevel").strip()
        if Path(root).resolve() != self.root:
            raise ValueError("repository root must be the Git worktree root")
        head_result = subprocess.run(
            [self.git_path, "-C", str(self.root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=self.search_timeout,
        )
        commit = head_result.stdout.strip() if head_result.returncode == 0 else None
        branch = self._git_output("branch", "--show-current").strip()
        raw_status = self._git_output(
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "-z",
        )
        records = raw_status.split("\0")
        paths = []
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            paths.append(record[3:])
            if record[:2].strip() in {"R", "C"} and index < len(records):
                paths.append(records[index])
                index += 1
        changed_paths = tuple(sorted(set(paths)))
        return GitStatus(commit, branch, not changed_paths, changed_paths)

    def git_diff(self) -> str:
        tracked_diff = self._git_output("diff", "--no-ext-diff", "--no-color", "--")
        untracked_result = self._git_output(
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        )
        untracked_diffs = []
        for path in filter(None, untracked_result.split("\0")):
            result = subprocess.run(
                [
                    self.git_path,
                    "-C",
                    str(self.root),
                    "diff",
                    "--no-index",
                    "--no-ext-diff",
                    "--no-color",
                    "--",
                    os.devnull,
                    path,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.search_timeout,
            )
            if result.returncode not in {0, 1}:
                raise RuntimeError(result.stderr.strip() or "could not diff untracked file")
            if result.stdout:
                untracked_diffs.append(result.stdout)
        return "".join((tracked_diff, *untracked_diffs))

    def patch_checkpoint(self) -> int:
        return len(self._patch_log)

    def changed_files_since(self, checkpoint: int) -> tuple[str, ...]:
        if isinstance(checkpoint, bool) or not isinstance(checkpoint, int):
            raise ValueError("patch checkpoint must be an integer")
        if checkpoint < 0 or checkpoint > len(self._patch_log):
            raise ValueError("patch checkpoint is outside the current run")
        paths = {
            path
            for _, patch in self._patch_log[checkpoint:]
            for path in self._parse_patch_paths(patch)
        }
        return tuple(sorted(paths))

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
                    *self._sensitive_glob_arguments(),
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

    def find_calls(self, name: str) -> str:
        if not name.isidentifier():
            raise ValueError("name must be a Python identifier")
        results = []
        for pattern in (f"{name}($$$ARGS)", f"$OBJ.{name}($$$ARGS)"):
            results.extend(json.loads(self.find_structural(pattern)))
        unique = {
            (item["path"], item["start_line"], item["end_line"], item["text"]): item
            for item in results
        }
        return json.dumps(list(unique.values()))

    def find_tests_for(self, symbol_or_path: str) -> str:
        value = symbol_or_path.strip()
        if not value:
            raise ValueError("symbol or path must not be empty")
        if "/" in value or Path(value).suffix:
            source = ast.parse(self.read_file(value))
            symbols = {
                node.name
                for node in ast.walk(source)
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            }
        else:
            symbols = {value}
        if any(not symbol.isidentifier() for symbol in symbols):
            raise ValueError("symbol must be a Python identifier or repository-relative file path")
        matches = [
            match
            for symbol in sorted(symbols)
            for match in json.loads(self.find_calls(symbol))
        ]
        tests = [match for match in matches if self._is_test_path(match["path"])]
        return json.dumps(tests)

    def find_imports(self, name: str) -> str:
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
                    "--items",
                    "imports",
                    "--color",
                    "never",
                    *self._sensitive_glob_arguments(),
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
                signature = item.get("signature", "")
                if item.get("name") == name or re.search(
                    rf"(?<!\w){re.escape(name)}(?!\w)", signature
                ):
                    matches.append(
                        {
                            "path": Path(file_result["path"]).as_posix(),
                            "name": name,
                            "symbol": item.get("name", ""),
                            "signature": signature,
                            "line": item["range"]["start"]["line"] + 1,
                        }
                    )
        output = json.dumps(matches)
        if len(output) > self.max_search_output_chars:
            raise RuntimeError("structural search output exceeded the configured limit")
        return output

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
                    *self._sensitive_glob_arguments(),
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
        if result.returncode == 1:
            return "[]"
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
                    "--glob",
                    "!**/.env*",
                    "--glob",
                    "!**/*secret*",
                    "--glob",
                    "!**/*credential*",
                    "--glob",
                    "!**/*.pem",
                    "--glob",
                    "!**/*.key",
                    "--glob",
                    "!**/*.p12",
                    "--glob",
                    "!**/*.pfx",
                    "--glob",
                    "!**/*.tfstate",
                    "--glob",
                    "!**/id_rsa",
                    "--glob",
                    "!**/id_ed25519",
                    "--glob",
                    "!**/id_ecdsa",
                    "--glob",
                    "!**/id_dsa",
                    "--glob",
                    "!**/.ssh/**",
                    "--glob",
                    "!**/.aws/**",
                    "--glob",
                    "!**/.gnupg/**",
                    "--glob",
                    "!**/.netrc",
                    "--glob",
                    "!**/.npmrc",
                    "--glob",
                    "!**/.pypirc",
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

    def _require_git(self) -> None:
        if self.git_path is None:
            raise RuntimeError("git executable 'git' is required for repository status")

    def _git_output(self, *arguments: str) -> str:
        self._require_git()
        result = subprocess.run(
            [self.git_path, "-C", str(self.root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=self.search_timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "git command failed")
        return result.stdout

    def _ensure_clean_git_repository(self) -> None:
        if self._initial_clean_checked:
            return
        if self.git_path is None:
            raise RuntimeError("git executable 'git' is required for patch operations")
        root_result = subprocess.run(
            [self.git_path, "-C", str(self.root), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=self.search_timeout,
        )
        if root_result.returncode != 0:
            raise RuntimeError("repository root must be inside a Git worktree")
        if Path(root_result.stdout.strip()).resolve() != self.root:
            raise ValueError("repository root must be the Git worktree root")
        status = subprocess.run(
            [
                self.git_path,
                "-C",
                str(self.root),
                "status",
                "--porcelain",
                "--untracked-files=all",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=self.search_timeout,
        )
        if status.returncode != 0:
            raise RuntimeError(status.stderr.strip() or "could not inspect Git status")
        if status.stdout.strip():
            raise RuntimeError("repository must be clean before CodeMill patching")
        self._initial_clean_checked = True

    def _validate_scope(
        self,
        patch: str,
        scope: ExpectedScope | None,
        checkpoint: int | None,
    ) -> None:
        if scope is None:
            return
        if checkpoint is None:
            checkpoint = len(self._patch_log)
        if isinstance(checkpoint, bool) or not isinstance(checkpoint, int):
            raise ValueError("patch checkpoint must be an integer")
        if checkpoint < 0 or checkpoint > len(self._patch_log):
            raise ValueError("patch checkpoint is outside the current run")
        candidate_patches = [existing for _, existing in self._patch_log[checkpoint:]] + [patch]
        changed_paths = set()
        changed_lines = 0
        dependency_files = {
            "cargo.toml",
            "gemfile",
            "go.mod",
            "package.json",
            "pyproject.toml",
            "requirements.txt",
            "setup.cfg",
            "uv.lock",
            "poetry.lock",
            "package-lock.json",
            "yarn.lock",
        }
        for candidate in candidate_patches:
            paths = self._parse_patch_paths(candidate)
            changed_paths.update(paths)
            changed_lines += self._changed_line_count(candidate)
            for path in paths:
                if scope.planned_paths and not any(
                    fnmatch.fnmatchcase(path, pattern) for pattern in scope.planned_paths
                ):
                    raise ScopeViolationError(f"patch path is outside planned scope: {path}")
                lowered = path.casefold()
                filename = Path(path).name.casefold()
                if not scope.allow_dependencies and (
                    filename in dependency_files or filename.startswith("requirements")
                ):
                    raise ScopeViolationError("patch exceeds dependency-change permission")
                if not scope.allow_schema_changes and (
                    "schema" in lowered
                    or "migration" in lowered
                    or lowered.endswith((".proto", ".sql"))
                ):
                    raise ScopeViolationError("patch exceeds schema-change permission")
            if not scope.allow_public_api:
                current_path = None
                for line in candidate.splitlines():
                    header = re.match(r"^diff --git a/.+ b/(.+)$", line)
                    if header:
                        current_path = header.group(1)
                        continue
                    if (
                        current_path is None
                        or self._is_test_path(current_path)
                        or not line.startswith(("+", "-"))
                        or line.startswith(("+++", "---"))
                    ):
                        continue
                    match = re.match(
                        r"^[+-]\s*(?:async\s+)?(?:def|class)\s+([A-Za-z][A-Za-z0-9_]*)",
                        line,
                    )
                    if match and not match.group(1).startswith("_"):
                        raise ScopeViolationError("patch exceeds public-API-change permission")

        if len(changed_paths) > scope.max_files:
            raise ScopeViolationError(
                f"patch exceeds file budget: {len(changed_paths)} > {scope.max_files}"
            )
        if changed_lines > scope.max_changed_lines:
            raise ScopeViolationError(
                f"patch exceeds changed-line budget: {changed_lines} > {scope.max_changed_lines}"
            )

    @staticmethod
    def _changed_line_count(patch: str) -> int:
        changed = 0
        for line in patch.splitlines():
            if line.startswith(("+++", "---")):
                continue
            if line.startswith(("+", "-")):
                changed += 1
        return changed

    def _parse_patch_paths(self, patch: str) -> tuple[str, ...]:
        if not isinstance(patch, str) or not patch.strip():
            raise ValueError("patch must not be empty")
        if "GIT binary patch" in patch or "new mode 120000" in patch or "old mode 120000" in patch:
            raise ValueError("binary and symlink patches are not allowed")
        headers = re.findall(r"^diff --git a/(.+) b/(.+)$", patch, re.MULTILINE)
        old_labels = re.findall(r"^--- (.+)$", patch, re.MULTILINE)
        new_labels = re.findall(r"^\+\+\+ (.+)$", patch, re.MULTILINE)
        if not headers or len(headers) != len(old_labels) or len(headers) != len(new_labels):
            raise ValueError("patch must contain matching unified diff file headers")
        paths = []
        for (old_path, new_path), old_label, new_label in zip(
            headers, old_labels, new_labels, strict=True
        ):
            old_label = old_label.split("\t", 1)[0]
            new_label = new_label.split("\t", 1)[0]
            if old_label == "/dev/null":
                old_label_path = None
            elif old_label.startswith("a/"):
                old_label_path = old_label[2:]
            else:
                raise ValueError("patch contains an invalid old file path")
            if new_label == "/dev/null":
                new_label_path = None
            elif new_label.startswith("b/"):
                new_label_path = new_label[2:]
            else:
                raise ValueError("patch contains an invalid new file path")
            if old_label_path is not None and old_label_path != old_path:
                raise ValueError("patch file headers do not match")
            if new_label_path is not None and new_label_path != new_path:
                raise ValueError("patch file headers do not match")
            if old_label_path is not None and new_label_path is not None:
                if old_label_path != new_label_path:
                    raise ValueError("renames and copies are not allowed")
            changed_path = old_label_path or new_label_path
            if changed_path is None:
                raise ValueError("patch may not delete /dev/null")
            self._validate_patch_path(changed_path)
            paths.append(changed_path)
        if len(paths) != len(set(paths)):
            raise ValueError("patch contains duplicate file paths")
        return tuple(paths)

    def _validate_patch_path(self, path: str) -> None:
        if (
            not re.fullmatch(r"[A-Za-z0-9._/-]+", path)
            or path.startswith("/")
            or ".." in Path(path).parts
        ):
            raise ValueError("patch path escapes repository root or uses unsupported characters")
        if self._is_sensitive_path(path):
            raise ScopeViolationError("patch targets a sensitive path")
        candidate = (self.root / path).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as error:
            raise ValueError("patch path escapes repository root") from error

    @staticmethod
    def _sensitive_glob_arguments() -> tuple[str, ...]:
        globs = (
            "!**/.env*",
            "!**/*secret*",
            "!**/*credential*",
            "!**/*.pem",
            "!**/*.key",
            "!**/*.p12",
            "!**/*.pfx",
            "!**/*.tfstate",
            "!**/id_rsa",
            "!**/id_ed25519",
            "!**/id_ecdsa",
            "!**/id_dsa",
            "!**/.ssh/**",
            "!**/.aws/**",
            "!**/.gnupg/**",
            "!**/.netrc",
            "!**/.npmrc",
            "!**/.pypirc",
        )
        return tuple(argument for glob in globs for argument in ("--globs", glob))

    @staticmethod
    def _is_sensitive_path(path: str) -> bool:
        parts = tuple(part.casefold() for part in Path(path).parts)
        filename = parts[-1]
        sensitive_directories = {".aws", ".gnupg", ".ssh", "credentials", "secrets"}
        sensitive_names = {
            ".netrc",
            ".npmrc",
            ".pypirc",
            "id_dsa",
            "id_ed25519",
            "id_ecdsa",
            "id_rsa",
        }
        sensitive_suffixes = {".key", ".pem", ".p12", ".pfx", ".tfstate"}
        return (
            any(part in sensitive_directories for part in parts[:-1])
            or filename in sensitive_names
            or filename == ".env"
            or filename.startswith(".env.")
            or "secret" in filename
            or "credential" in filename
            or "service-account" in filename
            or Path(filename).suffix in sensitive_suffixes
        )

    @staticmethod
    def _is_test_path(path: str) -> bool:
        parts = tuple(part.casefold() for part in Path(path).parts)
        filename = parts[-1]
        return (
            any(part in {"test", "tests", "__tests__"} for part in parts[:-1])
            or filename.startswith("test_")
            or "_test." in filename
            or ".test." in filename
            or ".spec." in filename
        )

    def _apply_git_patch(self, patch: str, reverse: bool = False) -> None:
        if self.git_path is None:
            raise RuntimeError("git executable 'git' is required for patch operations")
        arguments = [self.git_path, "-C", str(self.root), "apply", "--check"]
        if reverse:
            arguments.append("--reverse")
        checked = subprocess.run(
            [*arguments, "-"],
            input=patch,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.search_timeout,
        )
        if checked.returncode != 0:
            raise RuntimeError(checked.stderr.strip() or "patch validation failed")
        arguments = [self.git_path, "-C", str(self.root), "apply"]
        if reverse:
            arguments.append("--reverse")
        applied = subprocess.run(
            [*arguments, "-"],
            input=patch,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.search_timeout,
        )
        if applied.returncode != 0:
            raise RuntimeError(applied.stderr.strip() or "patch application failed")

    def _fingerprint(self, paths: tuple[str, ...] | set[str]) -> str:
        digest = hashlib.sha256()
        for path in sorted(paths):
            digest.update(path.encode("utf-8"))
            file_path = self.root / path
            if not file_path.exists():
                digest.update(b"<missing>")
            else:
                digest.update(file_path.read_bytes())
        return digest.hexdigest()

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
        if self._is_sensitive_path(relative_path.as_posix()):
            raise PermissionError("refusing to read a sensitive path")
        return resolved
