from dataclasses import dataclass
from pathlib import PurePosixPath

from .tools import CodingTools


LANGUAGES = {
    ".c": "C",
    ".cpp": "C++",
    ".cs": "C#",
    ".go": "Go",
    ".h": "C",
    ".java": "Java",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".kt": "Kotlin",
    ".py": "Python",
    ".rb": "Ruby",
    ".rs": "Rust",
    ".sh": "Shell",
    ".swift": "Swift",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
}

CONFIGURATION_NAMES = {
    "Cargo.toml",
    "go.mod",
    "package.json",
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    "pytest.ini",
}
TEST_DIRECTORY_NAMES = {"test", "tests", "__tests__"}


@dataclass(frozen=True)
class RepositoryMap:
    languages: tuple[str, ...]
    source_roots: tuple[str, ...]
    test_roots: tuple[str, ...]
    configuration_files: tuple[str, ...]
    tree: tuple[str, ...]

    def render(self) -> str:
        lines = [
            f"Languages: {', '.join(self.languages) or 'unknown'}",
            f"Source roots: {', '.join(self.source_roots) or 'unknown'}",
            f"Test roots: {', '.join(self.test_roots) or 'unknown'}",
            f"Configuration: {', '.join(self.configuration_files) or 'none detected'}",
            "Tree:",
        ]
        lines.extend(f"- {path}" for path in self.tree)
        return "\n".join(lines)


def summarize_repository(tools: CodingTools, depth: int = 3) -> RepositoryMap:
    tree = tools.list_tree(".", depth)
    files = tuple(path for path in tree if not path.endswith("/"))
    languages = set()
    source_roots = set()
    test_roots = set()
    configurations = set()

    for path in files:
        relative = PurePosixPath(path)
        language = LANGUAGES.get(relative.suffix.lower())
        if language is None:
            continue
        languages.add(language)
        parts = relative.parts
        test_index = next(
            (index for index, part in enumerate(parts[:-1]) if part.lower() in TEST_DIRECTORY_NAMES),
            None,
        )
        if test_index is not None:
            test_roots.add("/".join(parts[: test_index + 1]))
        else:
            source_roots.add(parts[0] if len(parts) > 1 else ".")

    for path in tree:
        if PurePosixPath(path).name in CONFIGURATION_NAMES:
            configurations.add(path)

    for path in tree:
        if not path.endswith("/"):
            continue
        parts = PurePosixPath(path).parts
        if parts and parts[-1].rstrip("/").lower() in TEST_DIRECTORY_NAMES:
            test_roots.add("/".join(parts))

    return RepositoryMap(
        tuple(sorted(languages)),
        tuple(sorted(source_roots)),
        tuple(sorted(test_roots)),
        tuple(sorted(configurations)),
        tree,
    )
