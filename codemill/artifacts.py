import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import GitStatus, RunResult, RunStatus, Task, VerificationPurpose


class ArtifactWriterError(RuntimeError):
    pass


class ArtifactWriter:
    def __init__(self, output_root: str | Path):
        self.output_root = Path(output_root).expanduser().resolve()

    def write(
        self,
        task: Task,
        result: RunResult,
        initial_git_status: GitStatus,
        final_git_status: GitStatus,
        final_diff: str,
    ) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", result.run_id):
            raise ArtifactWriterError("unsafe run id")
        self.output_root.mkdir(parents=True, exist_ok=True)
        run_directory = self.output_root / result.run_id
        lock_path = self.output_root / f".{result.run_id}.lock"
        try:
            lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as error:
            raise ArtifactWriterError("run artifact bundle already exists or is being written") from error

        temporary_directory = None
        try:
            if run_directory.exists():
                raise ArtifactWriterError(f"run artifact bundle already exists: {run_directory}")
            temporary_directory = Path(
                tempfile.mkdtemp(prefix=f".{result.run_id}-", dir=self.output_root)
            )
            self._write_contents(
                temporary_directory,
                task,
                result,
                initial_git_status,
                final_git_status,
                final_diff,
            )
            os.rename(temporary_directory, run_directory)
            temporary_directory = None
            return run_directory
        except ArtifactWriterError:
            raise
        except OSError as error:
            raise ArtifactWriterError(f"could not write run artifacts: {error}") from error
        finally:
            os.close(lock_descriptor)
            lock_path.unlink(missing_ok=True)
            if temporary_directory is not None:
                shutil.rmtree(temporary_directory, ignore_errors=True)

    def _write_contents(
        self,
        directory: Path,
        task: Task,
        result: RunResult,
        initial_git_status: GitStatus,
        final_git_status: GitStatus,
        final_diff: str,
    ) -> None:
        self._write_json(
            directory / "run.json",
            {
                "format_version": 1,
                "run_id": result.run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": result.status.value,
                "attempts": result.attempts,
                "diagnostics": result.diagnostics,
                "task": asdict(task),
                "initial_git_status": asdict(initial_git_status),
                "final_git_status": asdict(final_git_status),
            },
        )
        self._write_json(
            directory / "plan.json",
            {"subtasks": [asdict(subtask) for subtask in result.planned_subtasks]},
        )
        trace = "".join(
            json.dumps(asdict(event), ensure_ascii=False) + "\n"
            for event in result.events
        )
        (directory / "trace.jsonl").write_text(trace, encoding="utf-8")
        self._write_json(
            directory / "verified-slices.json",
            {"slices": [asdict(item) for item in result.verified_slices]},
        )
        self._write_json(
            directory / "verification.json",
            {
                "records": [
                    {
                        "purpose": record.purpose.value,
                        "target": asdict(record.target) if record.target is not None else None,
                        "result": asdict(record.result),
                    }
                    for record in result.verifications
                ]
            },
        )
        self._write_json(
            directory / "changed-files.json",
            {
                "changed_paths": final_git_status.changed_paths,
                "verified_slice_paths": tuple(
                    sorted(
                        {
                            path
                            for record in result.verified_slices
                            for path in record.changed_files
                        }
                    )
                ),
            },
        )
        repair_events = [
            asdict(event)
            for event in result.events
            if event.name in {"repair_started", "repair_patch_applied", "repair_budget_exhausted"}
        ]
        unresolved = [
            {
                "subtask_id": subtask.subtask_id,
                "status": subtask.status.value,
                "diagnostics": subtask.diagnostics,
            }
            for subtask in result.subtasks
            if subtask.status is not RunStatus.VERIFIED
        ]
        if result.status is not RunStatus.VERIFIED and not unresolved:
            unresolved.append({"subtask_id": None, "status": result.status.value, "diagnostics": result.diagnostics})
        self._write_json(
            directory / "repairs.json",
            {"attempts": repair_events, "unresolved_issues": unresolved},
        )
        (directory / "final.diff").write_text(final_diff, encoding="utf-8")
        (directory / "result.md").write_text(self._render_result(task, result), encoding="utf-8")
        hashes = {}
        for artifact in sorted(directory.iterdir(), key=lambda path: path.name):
            if artifact.is_file():
                content = artifact.read_bytes()
                hashes[artifact.name] = {
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
        self._write_json(directory / "manifest.json", {"artifacts": hashes})

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    @staticmethod
    def _render_result(task: Task, result: RunResult) -> str:
        lines = [
            f"# CodeMill run {result.run_id}",
            "",
            f"- Status: **{result.status.value}**",
            f"- Attempts: {result.attempts}",
            f"- Task: {task.objective}",
            f"- Verified slices: {len(result.verified_slices)} / {len(result.planned_subtasks)}",
            "",
        ]
        if any(
            record.purpose is VerificationPurpose.NO_CHANGE
            for record in result.pre_final_verifications
        ):
            lines.insert(6, "- Outcome: Already satisfied; existing acceptance tests passed without changes")
        if result.diagnostics:
            lines.extend(("## Diagnostics", "", *[f"- {item}" for item in result.diagnostics], ""))
        if result.status is not RunStatus.VERIFIED:
            lines.extend(("## Unresolved", "", "Run did not reach verified status.", ""))
        return "\n".join(lines)
