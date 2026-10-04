import json
import subprocess

import pytest

from codemill.harness import CodingHarness
from codemill.models import (
    ExpectedScope,
    RunStatus,
    ScopeViolationError,
    Task,
    VerificationFailureKind,
    VerificationPurpose,
    VerificationResult,
)
from codemill.repository_tools import LocalRepositoryTools, ScopeViolationError


def initialize_repository(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "tests@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "CodeMill Tests"], check=True)
    (path / "src").mkdir()
    (path / "src" / "module.py").write_text("value = 1\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "initial"], check=True)


def test_rejects_patch_over_changed_line_budget_before_mutation(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    patch = """diff --git a/tests/test_scope.py b/tests/test_scope.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_scope.py
@@ -0,0 +1,3 @@
+def test_one():
+    assert True
+
"""

    with pytest.raises(ScopeViolationError, match="changed-line budget"):
        tools.apply_test_patch(
            patch,
            ExpectedScope(max_files=2, max_changed_lines=2),
            tools.patch_checkpoint(),
        )

    assert not (tmp_path / "tests" / "test_scope.py").exists()
    assert tools.git_status().clean


def test_enforces_cumulative_task_budget_across_slices(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    run_checkpoint = tools.patch_checkpoint()
    task_scope = ExpectedScope(max_files=3, max_changed_lines=2)
    first_patch = """diff --git a/tests/test_first.py b/tests/test_first.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_first.py
@@ -0,0 +1 @@
+def test_first(): pass
"""
    tools.apply_test_patch(
        first_patch,
        ExpectedScope(max_files=2, max_changed_lines=10),
        run_checkpoint,
        task_scope,
        run_checkpoint,
    )
    tools.freeze_tests()
    second_checkpoint = tools.patch_checkpoint()
    second_patch = """diff --git a/tests/test_second.py b/tests/test_second.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_second.py
@@ -0,0 +1,2 @@
+def test_second():
+    assert True
"""

    with pytest.raises(ScopeViolationError, match="changed-line budget"):
        tools.apply_test_patch(
            second_patch,
            ExpectedScope(max_files=2, max_changed_lines=10),
            second_checkpoint,
            task_scope,
            run_checkpoint,
        )

    assert not (tmp_path / "tests" / "test_second.py").exists()


def test_harness_escalates_when_slices_exceed_task_budget(tmp_path):
    initialize_repository(tmp_path)

    class Model:
        def decompose(self, task, tools):
            subtasks = []
            for identifier in ("first", "second"):
                subtasks.append(
                    {
                        "id": identifier,
                        "objective": f"complete {identifier}",
                        "acceptance_criteria": [f"{identifier} behavior works"],
                        "constraints": [],
                        "depends_on": [],
                        "expected_scope": {
                            "max_files": 2,
                            "max_changed_lines": 10,
                            "allow_dependencies": False,
                            "allow_public_api": False,
                            "allow_schema_changes": False,
                            "planned_paths": [],
                        },
                    }
                )
            return json.dumps({"subtasks": subtasks})

        def review_decomposition(self, task, subtasks, tools):
            return '{"accepted": true, "findings": []}'

        def locate_and_plan(self, task, tools):
            return task.id

        def create_test_patch(self, task, plan, tools):
            return f"""diff --git a/tests/test_{task.id}.py b/tests/test_{task.id}.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_{task.id}.py
@@ -0,0 +1 @@
+def test_{task.id}(): pass
"""

        def create_patch(self, task, plan, tools, test_target, red_diagnostics):
            return """diff --git a/src/module.py b/src/module.py
index 0000000..0000000 100644
--- a/src/module.py
+++ b/src/module.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

        def review_implementation(self, task, diff, tools, test_target):
            return '{"accepted": true, "findings": []}'

        def repair_patch(self, task, diagnostics, tools, test_target):
            raise AssertionError("repair should not be needed")

    class Verifier:
        def verify(self, purpose, target=None):
            if purpose is VerificationPurpose.RED:
                return VerificationResult(
                    False,
                    ("behavior absent",),
                    VerificationFailureKind.EXPECTED_BEHAVIOR,
                )
            return VerificationResult(True)

    result = CodingHarness(
        Model(),
        LocalRepositoryTools(tmp_path),
        Verifier(),
    ).run(
        Task(
            "complete two behaviors",
            expected_scope=ExpectedScope(max_files=3, max_changed_lines=3),
        )
    )

    assert result.status is RunStatus.ESCALATED
    assert result.subtasks[0].status is RunStatus.VERIFIED
    assert result.subtasks[1].status is RunStatus.ESCALATED
    assert result.subtasks[1].diagnostics == (
        "patch exceeds changed-line budget: 4 > 3",
    )
    assert not (tmp_path / "tests" / "test_second.py").exists()


def test_focused_test_path_can_differ_from_planned_production_paths(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    scope = ExpectedScope(planned_paths=("src/**",))
    test_patch = """diff --git a/test_scope.py b/test_scope.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/test_scope.py
@@ -0,0 +1 @@
+def test_scope(): pass
"""

    target = tools.apply_test_patch(test_patch, scope, tools.patch_checkpoint())

    assert target.paths == ("test_scope.py",)


def test_production_scope_ignores_prior_accepted_test_patch_paths(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    checkpoint = tools.patch_checkpoint()
    scope = ExpectedScope(
        max_files=1,
        max_changed_lines=2,
        planned_paths=("src/**",),
    )
    test_patch = """diff --git a/test_scope.py b/test_scope.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/test_scope.py
@@ -0,0 +1 @@
+def test_scope(): pass
"""
    tools.apply_test_patch(test_patch, scope, checkpoint)
    protected = tools.freeze_tests()
    production_patch = """diff --git a/src/module.py b/src/module.py
index 0000000..0000000 100644
--- a/src/module.py
+++ b/src/module.py
@@ -1 +1 @@
-value = 1
+value = 2
"""

    tools.apply_production_patch(production_patch, protected, scope, checkpoint)

    assert (tmp_path / "src" / "module.py").read_text() == "value = 2\n"


def test_rejects_patch_outside_planned_paths(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    checkpoint = tools.patch_checkpoint()
    scope = ExpectedScope(planned_paths=("src/**", "tests/**"))
    test_patch = """diff --git a/tests/test_scope.py b/tests/test_scope.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_scope.py
@@ -0,0 +1 @@
+def test_scope(): pass
"""
    tools.apply_test_patch(test_patch, scope, checkpoint)
    protected = tools.freeze_tests()
    out_of_scope = """diff --git a/docs/README.md b/docs/README.md
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/docs/README.md
@@ -0,0 +1 @@
+unrelated change
"""

    with pytest.raises(ScopeViolationError, match="outside planned scope"):
        tools.apply_production_patch(out_of_scope, protected, scope, checkpoint)

    assert not (tmp_path / "docs" / "README.md").exists()


def test_rejects_public_api_change_when_scope_disallows_it(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    checkpoint = tools.patch_checkpoint()
    test_patch = """diff --git a/tests/test_scope.py b/tests/test_scope.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_scope.py
@@ -0,0 +1 @@
+def test_scope(): pass
"""
    tools.apply_test_patch(test_patch, ExpectedScope(), checkpoint)
    protected = tools.freeze_tests()
    implementation = """diff --git a/src/module.py b/src/module.py
index 0000000..0000000 100644
--- a/src/module.py
+++ b/src/module.py
@@ -1 +1,3 @@
 value = 1
+def public_helper():
+    return 1
"""

    with pytest.raises(ScopeViolationError, match="public-API-change permission"):
        tools.apply_production_patch(
            implementation,
            protected,
            ExpectedScope(max_changed_lines=20),
            checkpoint,
        )

    assert (tmp_path / "src" / "module.py").read_text() == "value = 1\n"


def test_rejects_dependency_manifest_change_when_scope_disallows_it(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    checkpoint = tools.patch_checkpoint()
    test_patch = """diff --git a/tests/test_scope.py b/tests/test_scope.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_scope.py
@@ -0,0 +1 @@
+def test_scope(): pass
"""
    tools.apply_test_patch(test_patch, ExpectedScope(), checkpoint)
    protected = tools.freeze_tests()
    dependency_patch = """diff --git a/pyproject.toml b/pyproject.toml
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/pyproject.toml
@@ -0,0 +1 @@
+[project.optional-dependencies]
"""

    with pytest.raises(ScopeViolationError, match="dependency-change permission"):
        tools.apply_production_patch(
            dependency_patch,
            protected,
            ExpectedScope(max_changed_lines=20),
            checkpoint,
        )

    assert not (tmp_path / "pyproject.toml").exists()


def test_applies_patch_within_scope_budget(tmp_path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    patch = """diff --git a/tests/test_scope.py b/tests/test_scope.py
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/tests/test_scope.py
@@ -0,0 +1,2 @@
+def test_one():
+    assert True
"""

    target = tools.apply_test_patch(
        patch,
        ExpectedScope(max_files=1, max_changed_lines=2),
        tools.patch_checkpoint(),
    )

    assert target.paths == ("tests/test_scope.py",)
    assert (tmp_path / "tests" / "test_scope.py").exists()
