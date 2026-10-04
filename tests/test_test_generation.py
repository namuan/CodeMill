import pytest

from codemill.repository_tools import LocalRepositoryTools
from codemill.test_generation import build_test_file_patch


def test_builds_a_new_test_file_patch_at_a_harness_selected_path(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_existing.py").write_text("def test_existing():\n    assert True\n")
    tools = LocalRepositoryTools(tmp_path)

    patch = build_test_file_patch(
        "from package import value\n\ndef test_value():\n    assert value() == 1\n",
        "ST-001",
        tools,
    )

    assert "diff --git a/tests/test_codemill_st_001.py b/tests/test_codemill_st_001.py" in patch
    assert "new file mode 100644" in patch
    assert "--- /dev/null" in patch
    assert "+++ b/tests/test_codemill_st_001.py" in patch
    assert "+def test_value():" in patch


def test_avoids_existing_harness_generated_test_path(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_codemill_st_001.py").write_text("def test_old(): pass\n")
    tools = LocalRepositoryTools(tmp_path)

    patch = build_test_file_patch("def test_value():\n    assert True\n", "ST-001", tools)

    assert "tests/test_codemill_st_001_2.py" in patch


@pytest.mark.parametrize(
    "source",
    ("", "value = 1\n", "def test_broken(:\n    pass\n"),
)
def test_rejects_empty_invalid_or_non_test_modules(tmp_path, source):
    (tmp_path / "tests").mkdir()
    tools = LocalRepositoryTools(tmp_path)

    with pytest.raises(ValueError):
        build_test_file_patch(source, "ST-001", tools)
