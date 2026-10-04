import json
from pathlib import Path

from codemill.models import GitStatus, RunResult, RunStatus


def test_cli_runs_task_and_emits_starting_repository_state(monkeypatch, capsys, tmp_path):
    from codemill import cli

    class Tools:
        def __init__(self, root):
            self.root = Path(root).resolve()

        def git_status(self):
            return GitStatus("abc123", "main", True, ())

    class Harness:
        def __init__(self, model, tools, verifier):
            self.tools = tools

        def run(self, task):
            assert task.objective == "Add a greeting"
            assert task.acceptance_criteria == ("Ada gets Hello, Ada!", "Bob gets Hello, Bob!")
            assert task.constraints == ("Use standard library",)
            return RunResult(RunStatus.VERIFIED, 1, "run-1")

    monkeypatch.setattr(cli, "LocalRepositoryTools", Tools)
    monkeypatch.setattr(cli, "LlamaCppModelDriver", lambda: object())
    monkeypatch.setattr(cli, "PytestVerifier", lambda root: object())
    monkeypatch.setattr(cli, "CodingHarness", Harness)

    exit_code = cli.main(
        [
            "--repository",
            str(tmp_path),
            "--task",
            "Add a greeting",
            "--acceptance-criterion",
            "Ada gets Hello, Ada!",
            "--acceptance-criterion",
            "Bob gets Hello, Bob!",
            "--constraint",
            "Use standard library",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["repository"] == str(tmp_path.resolve())
    assert output["initial_git_status"]["commit"] == "abc123"
    assert output["task"]["acceptance_criteria"] == [
        "Ada gets Hello, Ada!",
        "Bob gets Hello, Bob!",
    ]
    assert output["result"]["status"] == RunStatus.VERIFIED.value


def test_cli_refuses_dirty_repository_before_creating_model(monkeypatch, capsys, tmp_path):
    from codemill import cli

    class Tools:
        def __init__(self, root):
            self.root = Path(root).resolve()

        def git_status(self):
            return GitStatus("abc123", "main", False, ("README.md",))

    def model_factory():
        raise AssertionError("model must not start for a dirty repository")

    monkeypatch.setattr(cli, "LocalRepositoryTools", Tools)
    monkeypatch.setattr(cli, "LlamaCppModelDriver", model_factory)

    exit_code = cli.main(
        ["--repository", str(tmp_path), "--task", "Change something"]
    )

    error = json.loads(capsys.readouterr().err)
    assert exit_code == 2
    assert "refuses dirty repositories" in error["error"]
    assert error["changed_paths"] == ["README.md"]


def test_cli_maps_terminal_statuses_to_exit_codes(monkeypatch, capsys, tmp_path):
    from codemill import cli

    class Tools:
        def __init__(self, root):
            self.root = Path(root).resolve()

        def git_status(self):
            return GitStatus("abc123", "main", True, ())

    class Harness:
        def __init__(self, model, tools, verifier):
            pass

        def run(self, task):
            return RunResult(RunStatus.ESCALATED, 0, "run-2")

    monkeypatch.setattr(cli, "LocalRepositoryTools", Tools)
    monkeypatch.setattr(cli, "LlamaCppModelDriver", lambda: object())
    monkeypatch.setattr(cli, "PytestVerifier", lambda root: object())
    monkeypatch.setattr(cli, "CodingHarness", Harness)

    exit_code = cli.main(["--repository", str(tmp_path), "--task", "Do a task"])

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out)["result"]["status"] == "escalated"
