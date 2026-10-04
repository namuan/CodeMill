import subprocess

import pytest

from codemill.models import ScopeViolationError
from codemill.repository_tools import LocalRepositoryTools


def initialize_repository(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "tests@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "CodeMill Tests"], check=True)
    (path / "src").mkdir()
    (path / "src" / "module.py").write_text("value = 1\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "initial"], check=True)


@pytest.mark.parametrize("path", (".env", "config/credentials.yml", "secrets/token.txt", "id_rsa"))
def test_rejects_mutations_to_sensitive_paths(tmp_path, path):
    initialize_repository(tmp_path)
    tools = LocalRepositoryTools(tmp_path)
    patch = f"""diff --git a/{path} b/{path}
new file mode 100644
index 0000000..0000000
--- /dev/null
+++ b/{path}
@@ -0,0 +1 @@
+secret-value
"""

    with pytest.raises(ScopeViolationError, match="sensitive path"):
        tools.apply_test_patch(patch)

    assert tools.git_status().clean


def test_refuses_to_read_sensitive_files(tmp_path):
    initialize_repository(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "credentials.yml").write_text("token: private\n")
    (tmp_path / ".env").write_text("API_TOKEN=private\n")
    tools = LocalRepositoryTools(tmp_path)

    with pytest.raises(PermissionError, match="sensitive path"):
        tools.read_file(".env")
    with pytest.raises(PermissionError, match="sensitive path"):
        tools.read_file("config/credentials.yml")


def test_structural_search_excludes_sensitive_directories(tmp_path):
    initialize_repository(tmp_path)
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "credentials.py").write_text(
        "def expose_token():\n    return 'private'\n"
    )
    tools = LocalRepositoryTools(tmp_path)
    if tools.ast_grep_path is None:
        pytest.skip("ast-grep is unavailable")

    assert tools.find_definitions("expose_token") == "[]"


def test_text_search_excludes_common_sensitive_files(tmp_path):
    initialize_repository(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "credentials.yml").write_text("API_TOKEN=private\n")
    (tmp_path / "notes.txt").write_text("API_TOKEN is a variable name\n")
    tools = LocalRepositoryTools(tmp_path)

    output = tools.search_text("API_TOKEN")

    assert "notes.txt" in output
    assert "credentials.yml" not in output
