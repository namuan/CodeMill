from codemill.context import RepositoryMap, summarize_repository
from codemill.repository_tools import LocalRepositoryTools


def test_summarizes_languages_roots_and_configuration(tmp_path):
    (tmp_path / "src" / "service").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "service" / "index.ts").write_text("export const value = 1\n")
    (tmp_path / "tests" / "test_service.py").write_text("def test_service(): pass\n")
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    (tmp_path / "package.json").write_text("{}\n")
    tools = LocalRepositoryTools(tmp_path)

    summary = summarize_repository(tools)

    assert summary == RepositoryMap(
        languages=("Python", "TypeScript"),
        source_roots=("src",),
        test_roots=("tests",),
        configuration_files=("package.json", "pyproject.toml"),
        tree=("docs/", "package.json", "pyproject.toml", "src/", "src/service/", "src/service/index.ts", "tests/", "tests/test_service.py"),
    )


def test_renders_compact_repository_map():
    summary = RepositoryMap(
        languages=("Python",),
        source_roots=("codemill",),
        test_roots=("tests",),
        configuration_files=("pyproject.toml",),
        tree=("codemill/", "tests/", "pyproject.toml"),
    )

    rendered = summary.render()

    assert "Languages: Python" in rendered
    assert "Source roots: codemill" in rendered
    assert "Test roots: tests" in rendered
    assert "Configuration: pyproject.toml" in rendered
    assert "Tree:\n- codemill/" in rendered
