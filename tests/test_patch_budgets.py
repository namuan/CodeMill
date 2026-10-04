import subprocess

import pytest

from codemill.models import ExpectedScope
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
