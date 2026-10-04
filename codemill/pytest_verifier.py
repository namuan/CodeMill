import re
import subprocess
import sys
import time
from pathlib import Path

from .models import (
    VerificationFailureKind,
    VerificationPurpose,
    VerificationResult,
    VerificationTarget,
)


class PytestVerifier:
    def __init__(
        self,
        root: str | Path,
        timeout: float = 120.0,
        max_output_chars: int = 20_000,
    ):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("repository root must be a directory")
        self.timeout = timeout
        self.max_output_chars = max_output_chars

    def verify(
        self,
        purpose: VerificationPurpose,
        target: VerificationTarget | None = None,
    ) -> VerificationResult:
        started = time.monotonic()
        try:
            command = self._command(purpose, target)
        except ValueError as error:
            return VerificationResult(
                False,
                (str(error),),
                VerificationFailureKind.OTHER,
                duration_seconds=time.monotonic() - started,
            )

        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return VerificationResult(
                False,
                (f"pytest timed out after {self.timeout:g} seconds",),
                VerificationFailureKind.OTHER,
                tuple(command),
                None,
                time.monotonic() - started,
            )
        except OSError as error:
            return VerificationResult(
                False,
                (f"pytest could not be started: {error}",),
                VerificationFailureKind.OTHER,
                tuple(command),
                None,
                time.monotonic() - started,
            )

        output = self._bounded_output(result.stdout, result.stderr)
        duration = time.monotonic() - started
        if result.returncode == 0:
            return VerificationResult(
                True,
                ("pytest passed",),
                command=tuple(command),
                exit_code=result.returncode,
                duration_seconds=duration,
            )

        diagnostics = (
            f"pytest exited with status {result.returncode}",
            output or "pytest produced no diagnostic output",
        )
        failure_kind = VerificationFailureKind.OTHER
        if purpose is VerificationPurpose.RED and self._is_assertion_failure(output, target):
            failure_kind = VerificationFailureKind.EXPECTED_BEHAVIOR
        return VerificationResult(
            False,
            diagnostics,
            failure_kind,
            tuple(command),
            result.returncode,
            duration,
        )

    def _command(
        self,
        purpose: VerificationPurpose,
        target: VerificationTarget | None,
    ) -> list[str]:
        command = [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "--tb=short",
        ]
        if purpose in (
            VerificationPurpose.RED,
            VerificationPurpose.GREEN,
            VerificationPurpose.NO_CHANGE,
        ):
            if target is None or not target.paths:
                raise ValueError("focused verification requires a test target")
            test_paths = tuple(self._resolve_target(path) for path in target.paths)
            if target.selectors:
                command.extend(
                    f"{path}::{selector}"
                    for path in test_paths
                    for selector in target.selectors
                )
            else:
                command.extend(test_paths)
        return command

    def _resolve_target(self, path: str) -> str:
        relative_path = Path(path)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("test target escapes repository root")
        try:
            resolved = (self.root / relative_path).resolve(strict=True)
        except FileNotFoundError as error:
            raise ValueError(f"test target does not exist: {path}") from error
        try:
            resolved.relative_to(self.root)
        except ValueError as error:
            raise ValueError("test target escapes repository root") from error
        if not resolved.is_file():
            raise ValueError(f"test target is not a file: {path}")
        return resolved.relative_to(self.root).as_posix()

    def _bounded_output(self, stdout: str, stderr: str) -> str:
        output = (stdout + "\n" + stderr).strip()
        if len(output) <= self.max_output_chars:
            return output
        half = self.max_output_chars // 2
        return output[:half] + "\n[pytest output truncated]\n" + output[-half:]

    @staticmethod
    def _is_assertion_failure(
        output: str,
        target: VerificationTarget | None,
    ) -> bool:
        has_failed_test = re.search(r"(?m)^FAILED\s+.+::", output) is not None
        if target is None or not has_failed_test:
            return False
        frames = re.findall(r"(?m)^(.+\.py):\d+:(?: in .+| .*)?$", output)
        last_frame = Path(frames[-1]).as_posix() if frames else ""
        test_assertion = any(
            last_frame.endswith(Path(path).as_posix())
            for path in target.paths
        ) and re.search(r"(?m)^E\s+(?:assert\b|AssertionError\b)", output) is not None
        did_not_raise = "DID NOT RAISE" in output and any(
            path in output for path in target.paths
        )
        has_collection_error = re.search(r"(?m)^ERROR\s+collecting", output) is not None
        error_types = re.findall(
            r"(?m)^E\s+([A-Za-z_][A-Za-z_0-9]*(?:Error|Exception)):",
            output,
        )
        missing_api_names = tuple(
            f"{class_name}.{method_name}"
            for class_name, method_name in re.findall(
                r"AttributeError: '([^']+)' object has no attribute '([^']+)'",
                output,
            )
        )
        missing_api_red = (
            target is not None
            and bool(missing_api_names)
            and bool(target.expected_missing_symbols)
            and all(name in target.expected_missing_symbols for name in missing_api_names)
            and bool(error_types)
            and all(error_type == "AttributeError" for error_type in error_types)
            and "DID NOT RAISE" not in output
        )
        has_non_assertion_error = any(error_type != "AssertionError" for error_type in error_types)
        return (
            (test_assertion or did_not_raise or missing_api_red)
            and not has_collection_error
            and (not has_non_assertion_error or missing_api_red)
        )
