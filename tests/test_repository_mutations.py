import json
import subprocess

from codemill.harness import CodingHarness
from codemill.models import (
    RunStatus,
    Task,
    VerificationFailureKind,
    VerificationPurpose,
    VerificationResult,
    VerificationTarget,
)
from codemill.pytest_verifier import PytestVerifier
from codemill.repository_tools import LocalRepositoryTools


def initialize_repository(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "tests@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "CodeMill Tests"], check=True)
    (path / "src").mkdir()
    (path / "src" / "example.py").write_text("value = 1\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "initial"], check=True)


def test_reports_repository_revision_and_clean_status(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)

    status = tools.git_status()

    assert status.clean
    assert status.commit
    assert status.changed_paths == ()


def test_reports_modified_paths_in_repository_status(tmp_path):
    initialize_repository(tmp_path)
    (tmp_path / "src" / "example.py").write_text("value = 2\n")
    tools = LocalRepositoryTools(tmp_path)

    status = tools.git_status()

    assert not status.clean
    assert status.changed_paths == ("src/example.py",)


def test_already_satisfied_task_runs_existing_acceptance_test_without_changes(tmp_path):
    initialize_repository(tmp_path)
    (tmp_path / "src" / "example.py").write_text("def value(): return 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_example.py").write_text(
        "from src.example import value\n\ndef test_value(): assert value() == 1\n"
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "add acceptance test"], check=True)

    class Model:
        def decompose(self, task, tools):
            return '{"subtasks": []}'

        def review_decomposition(self, task, subtasks, tools):
            return json.dumps(
                {
                    "accepted": True,
                    "findings": [],
                    "already_satisfied": True,
                    "evidence": ["test_value asserts the requested result"],
                    "test_target": {
                        "paths": ["tests/test_example.py"],
                        "selectors": ["test_value"],
                    },
                }
            )

    tools = LocalRepositoryTools(tmp_path)
    result = CodingHarness(Model(), tools, PytestVerifier(tmp_path)).run(
        Task("return one", ("value() returns 1",))
    )

    assert result.status is RunStatus.VERIFIED
    assert tuple(record.purpose for record in result.verifications) == (
        VerificationPurpose.NO_CHANGE,
        VerificationPurpose.FINAL,
    )
    assert result.verifications[0].result.command[-1] == "tests/test_example.py::test_value"
    assert tools.git_status().clean
    assert tools.git_diff() == ""


def test_harness_completes_tdd_cycle_with_local_tools_and_pytest(tmp_path):
    initialize_repository(tmp_path)
    (tmp_path / "src" / "example.py").write_text(
        "def add(left, right):\n    return None\n"
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "add stub"], check=True)

    class Model:
        def decompose(self, task, tools):
            return json.dumps(
                {
                    "subtasks": [
                        {
                            "id": "add",
                            "objective": "Return the sum of two integers",
                            "acceptance_criteria": ["add(2, 3) returns 5"],
                            "constraints": [],
                            "depends_on": [],
                            "expected_scope": {
                                "max_files": 2,
                                "max_changed_lines": 20,
                                "allow_dependencies": False,
                                "allow_public_api": False,
                                "allow_schema_changes": False,
                                "planned_paths": [],
                            },
                        }
                    ]
                }
            )

        def review_decomposition(self, task, subtasks, tools):
            return '{"accepted": true, "findings": []}'

        def locate_and_plan(self, task, tools):
            return "Add the observable integer addition behavior."

        def create_test_patch(self, task, plan, tools):
            return """diff --git a/tests/test_example.py b/tests/test_example.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_example.py
@@ -0,0 +1,4 @@
+from src.example import add
+
+def test_add():
+    assert add(2, 3) == 5
+"""

        def create_patch(self, task, plan, tools, test_target, red_diagnostics):
            return """diff --git a/src/example.py b/src/example.py
index 0000000..0000000 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1,2 +1,2 @@
 def add(left, right):
-    return None
+    return left + right
"""

        def review_implementation(self, task, diff, tools, test_target):
            return '{"accepted": true, "findings": []}'

        def repair_patch(self, task, diagnostics, tools, test_target):
            raise AssertionError("repair should not be needed")

    tools = LocalRepositoryTools(tmp_path)
    result = CodingHarness(Model(), tools, PytestVerifier(tmp_path)).run(
        Task("add two integers")
    )

    assert result.status.value == "verified"
    assert result.subtasks[0].attempts == 1
    assert result.verified_slices == (result.subtasks[0].verified_slice,)
    verified_slice = result.subtasks[0].verified_slice
    assert verified_slice.accepted_test_paths == ("tests/test_example.py",)
    assert verified_slice.changed_files == ("src/example.py", "tests/test_example.py")
    assert (tmp_path / "src" / "example.py").read_text() == (
        "def add(left, right):\n    return left + right\n"
    )
    assert "return left + right" in tools.git_diff()
    assert result.events[-1].name == "run_verified"
    assert tuple(record.purpose for record in result.verifications) == (
        VerificationPurpose.RED,
        VerificationPurpose.GREEN,
        VerificationPurpose.REGRESSION,
        VerificationPurpose.FINAL,
    )
    assert result.verifications[0].result.exit_code != 0
    assert all(record.result.exit_code == 0 for record in result.verifications[1:])
    assert all(record.result.command[1:4] == ("-B", "-m", "pytest") for record in result.verifications)


def test_applies_test_patch_and_returns_focused_verification_target(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    patch = """diff --git a/tests/test_example.py b/tests/test_example.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_example.py
@@ -0,0 +1,2 @@
+from src.example import value
+assert value == 1
"""

    target = tools.apply_test_patch(patch)

    assert target == VerificationTarget(("tests/test_example.py",))
    assert (tmp_path / "tests" / "test_example.py").read_text() == (
        "from src.example import value\nassert value == 1\n"
    )


def test_rejects_test_patch_that_changes_production_code(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    patch = """diff --git a/src/example.py b/src/example.py
index 0000000..0000000 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1 +1,2 @@
 value = 1
+value += 1
"""

    try:
        tools.apply_test_patch(patch)
    except ValueError as error:
        assert "test patch may only modify test files" in str(error)
    else:
        raise AssertionError("production file patch was accepted as a test patch")

    assert (tmp_path / "src" / "example.py").read_text() == "value = 1\n"


def test_discards_unaccepted_test_patch(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    patch = """diff --git a/tests/test_example.py b/tests/test_example.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_example.py
@@ -0,0 +1,1 @@
+assert True
"""

    tools.apply_test_patch(patch)
    tools.discard_test_patch()

    assert not (tmp_path / "tests" / "test_example.py").exists()
    assert tools.git_diff() == ""


def test_refuses_to_patch_a_dirty_repository(tmp_path):
    initialize_repository(tmp_path)
    (tmp_path / "src" / "example.py").write_text("uncommitted change\n")
    tools = LocalRepositoryTools(tmp_path)
    patch = """diff --git a/tests/test_example.py b/tests/test_example.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_example.py
@@ -0,0 +1,1 @@
+assert True
"""

    try:
        tools.apply_test_patch(patch)
    except RuntimeError as error:
        assert "repository must be clean" in str(error)
    else:
        raise AssertionError("dirty repository was accepted for mutation")

    assert not (tmp_path / "tests" / "test_example.py").exists()


def test_protects_frozen_tests_while_applying_production_patches(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    test_patch = """diff --git a/tests/test_example.py b/tests/test_example.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_example.py
@@ -0,0 +1,1 @@
+assert True
"""
    target = tools.apply_test_patch(test_patch)
    protected = tools.freeze_tests()
    implementation_patch = """diff --git a/src/example.py b/src/example.py
index 0000000..0000000 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

    assert target.paths == protected.paths
    tools.apply_production_patch(implementation_patch, protected)

    assert (tmp_path / "src" / "example.py").read_text() == "value = 2\n"
    assert "assert True" in tools.git_diff()
    assert "value = 2" in tools.git_diff()


def test_rejects_production_patch_if_protected_test_fingerprint_changed(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    test_patch = """diff --git a/tests/test_example.py b/tests/test_example.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_example.py
@@ -0,0 +1 @@
+assert True
"""
    tools.apply_test_patch(test_patch)
    protected = tools.freeze_tests()
    (tmp_path / "tests" / "test_example.py").write_text("assert False\n")
    production_patch = """diff --git a/src/example.py b/src/example.py
index 0000000..0000000 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

    try:
        tools.apply_production_patch(production_patch, protected)
    except PermissionError as error:
        assert "fingerprint changed" in str(error)
    else:
        raise AssertionError("mutated protected test was accepted")

    assert (tmp_path / "src" / "example.py").read_text() == "value = 1\n"


def test_rejects_production_patch_that_changes_a_test_file(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    test_patch = """diff --git a/tests/test_example.py b/tests/test_example.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_example.py
@@ -0,0 +1 @@
+assert True
"""
    tools.apply_test_patch(test_patch)
    protected = tools.freeze_tests()
    production_patch = """diff --git a/tests/test_example.py b/tests/test_example.py
--- a/tests/test_example.py
+++ b/tests/test_example.py
@@ -1 +1 @@
-assert True
+assert False
"""

    try:
        tools.apply_production_patch(production_patch, protected)
    except PermissionError as error:
        assert "may not modify test files" in str(error)
    else:
        raise AssertionError("production patch modified a protected test")

    assert (tmp_path / "tests" / "test_example.py").read_text() == "assert True\n"


def test_rejects_mismatched_diff_and_file_headers(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    patch = """diff --git a/tests/test_example.py b/tests/test_example.py
new file mode 100644
--- /dev/null
+++ b/../outside.py
@@ -0,0 +1 @@
+value = 1
"""

    try:
        tools.apply_test_patch(patch)
    except ValueError as error:
        assert "headers do not match" in str(error)
    else:
        raise AssertionError("mismatched diff headers were accepted")

    assert not (tmp_path.parent / "outside.py").exists()


def test_git_diff_reports_final_worktree_state_not_patch_history(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    test_patch = """diff --git a/tests/test_example.py b/tests/test_example.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_example.py
@@ -0,0 +1 @@
+def test_value(): assert True
"""
    tools.apply_test_patch(test_patch)
    protected = tools.freeze_tests()
    first_patch = """diff --git a/src/example.py b/src/example.py
index 0000000..0000000 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1 +1 @@
-value = 1
+value = 2
"""
    second_patch = """diff --git a/src/example.py b/src/example.py
index 0000000..0000000 100644
--- a/src/example.py
+++ b/src/example.py
@@ -1 +1 @@
-value = 2
+value = 3
"""
    tools.apply_production_patch(first_patch, protected)
    tools.apply_production_patch(second_patch, protected)

    diff = tools.git_diff()

    assert "+++ b/tests/test_example.py" in diff
    assert "+value = 3" in diff
    assert "+value = 2" not in diff
    assert diff.count("diff --git a/src/example.py") == 1


def test_harness_records_attempt_to_mutate_protected_test(tmp_path):
    initialize_repository(tmp_path)

    class Model:
        def decompose(self, task, tools):
            return json.dumps(
                {
                    "subtasks": [
                        {
                            "id": "scope",
                            "objective": "keep a protected test unchanged",
                            "acceptance_criteria": ["test remains immutable"],
                            "constraints": [],
                            "depends_on": [],
                            "expected_scope": {
                                "max_files": 2,
                                "max_changed_lines": 20,
                                "allow_dependencies": False,
                                "allow_public_api": False,
                                "allow_schema_changes": False,
                                "planned_paths": ["tests/**"],
                            },
                        }
                    ]
                }
            )

        def review_decomposition(self, task, subtasks, tools):
            return '{"accepted": true, "findings": []}'

        def locate_and_plan(self, task, tools):
            return "test plan"

        def create_test_patch(self, task, plan, tools):
            return """diff --git a/tests/test_scope.py b/tests/test_scope.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_scope.py
@@ -0,0 +1 @@
+def test_scope(): pass
"""

        def create_patch(self, task, plan, tools, test_target, red_diagnostics):
            return """diff --git a/tests/test_scope.py b/tests/test_scope.py
--- a/tests/test_scope.py
+++ b/tests/test_scope.py
@@ -1 +1 @@
-def test_scope(): pass
+def test_scope(): assert True
"""

        def review_implementation(self, task, diff, tools, test_target):
            raise AssertionError("review must not run after a protected-test violation")

        def repair_patch(self, task, diagnostics, tools, test_target):
            raise AssertionError("repair must not run after a protected-test violation")

    class Verifier:
        def verify(self, purpose, target=None):
            if purpose is VerificationPurpose.RED:
                return VerificationResult(
                    False,
                    ("missing behavior",),
                    VerificationFailureKind.EXPECTED_BEHAVIOR,
                )
            return VerificationResult(True)

    tools = LocalRepositoryTools(tmp_path)
    result = CodingHarness(Model(), tools, Verifier()).run(Task("protect test"))

    assert result.status is RunStatus.FAILED
    assert "protected_test_mutation_attempt" in [event.name for event in result.events]
    assert (tmp_path / "tests" / "test_scope.py").read_text() == "def test_scope(): pass\n"


def test_rejects_paths_outside_repository_in_patch(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    patch = """diff --git a/../outside.py b/../outside.py
new file mode 100644
--- /dev/null
+++ b/../outside.py
@@ -0,0 +1 @@
+value = 1
"""

    try:
        tools.apply_test_patch(patch)
    except ValueError as error:
        assert "escapes repository root" in str(error)
    else:
        raise AssertionError("path traversal patch was accepted")
