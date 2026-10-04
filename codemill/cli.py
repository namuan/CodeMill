import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence, TextIO

from .artifacts import ArtifactWriter
from .harness import CodingHarness
from .llama_cpp import LlamaCppModelDriver
from .models import RunStatus, Task
from .pytest_verifier import PytestVerifier
from .repository_tools import LocalRepositoryTools


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codemill")
    parser.add_argument("--repository", required=True, help="path to a clean Git repository")
    parser.add_argument("--task", required=True, help="task objective")
    parser.add_argument(
        "--output-directory",
        required=True,
        help="directory outside the repository for the run artifact bundle",
    )
    parser.add_argument(
        "--acceptance-criterion",
        action="append",
        default=[],
        help="observable acceptance criterion; may be repeated",
    )
    parser.add_argument(
        "--constraint",
        action="append",
        default=[],
        help="task constraint; may be repeated",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        tools = LocalRepositoryTools(arguments.repository)
        initial_status = tools.git_status()
    except (OSError, RuntimeError, ValueError) as error:
        _write_json(
            sys.stderr,
            {"error": f"{type(error).__name__}: {error}"},
        )
        return 2

    if not initial_status.clean:
        _write_json(
            sys.stderr,
            {
                "error": "CodeMill refuses dirty repositories; commit, stash, or discard changes first.",
                "commit": initial_status.commit,
                "branch": initial_status.branch,
                "changed_paths": initial_status.changed_paths,
            },
        )
        return 2

    output_root = Path(arguments.output_directory).expanduser().resolve()
    try:
        output_root.relative_to(tools.root)
    except ValueError:
        pass
    else:
        _write_json(
            sys.stderr,
            {"error": "artifact output directory must be outside the repository"},
        )
        return 2

    task = Task(
        arguments.task,
        tuple(arguments.acceptance_criterion),
        tuple(arguments.constraint),
    )
    try:
        harness = CodingHarness(
            LlamaCppModelDriver(),
            tools,
            PytestVerifier(tools.root),
        )
        result = harness.run(task)
        final_status = tools.git_status()
        final_diff = tools.git_diff()
        artifact_directory = ArtifactWriter(output_root).write(
            task,
            result,
            initial_status,
            final_status,
            final_diff,
        )
    except Exception as error:
        _write_json(
            sys.stderr,
            {"error": f"{type(error).__name__}: {error}"},
        )
        return 1

    _write_json(
        sys.stdout,
        {
            "repository": str(tools.root),
            "initial_git_status": asdict(initial_status),
            "task": asdict(task),
            "result": asdict(result),
            "artifact_directory": str(artifact_directory),
        },
    )
    if result.status is RunStatus.VERIFIED:
        return 0
    if result.status is RunStatus.ESCALATED:
        return 2
    return 1


def _write_json(stream: TextIO, value: dict[str, object]) -> None:
    stream.write(json.dumps(value, indent=2) + "\n")
