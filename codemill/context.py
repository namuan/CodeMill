import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from .models import SubTask, VerificationTarget
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
STOP_WORDS = {
    "acceptance",
    "add",
    "after",
    "all",
    "and",
    "are",
    "behavior",
    "by",
    "for",
    "from",
    "implement",
    "into",
    "is",
    "it",
    "new",
    "of",
    "return",
    "returns",
    "should",
    "the",
    "this",
    "values",
    "when",
}


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


@dataclass(frozen=True)
class ContextFragment:
    kind: str
    text: str
    why_selected: str
    source: str
    score: int
    path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    symbols: tuple[str, ...] = ()
    required: bool = False

    def render(self) -> str:
        location = self.path or "run state"
        if self.start_line is not None:
            location += f":{self.start_line}"
            if self.end_line is not None and self.end_line != self.start_line:
                location += f"-{self.end_line}"
        return (
            f"### {self.kind} [{location}; source={self.source}; score={self.score}]\n"
            f"Why selected: {self.why_selected}\n{self.text}"
        )


@dataclass(frozen=True)
class ContextPack:
    stage: str
    subtask_id: str
    fragments: tuple[ContextFragment, ...]
    char_budget: int

    def render(self) -> str:
        sections = [f"## {self.stage} context for {self.subtask_id}"]
        sections.extend(fragment.render() for fragment in self.fragments)
        return "\n\n".join(sections)

    @property
    def char_count(self) -> int:
        return len(self.render())


class ContextBuilder:
    def __init__(self, tools: CodingTools):
        self.tools = tools

    def build_locate_context(
        self,
        subtask: SubTask,
        char_budget: int = 12_000,
    ) -> ContextPack:
        fragments = [self._subtask_fragment(subtask)]
        summary = summarize_repository(self.tools)
        fragments.append(
            ContextFragment(
                "repository_map",
                summary.render(),
                "Orient structural search across source and test roots.",
                "list_tree",
                20,
            )
        )
        evidence_count = 0
        for symbol in self._symbols(" ".join((subtask.objective, *subtask.acceptance_criteria))):
            definitions = json.loads(self.tools.find_definitions(symbol))
            for definition in definitions:
                path = definition["path"]
                line = definition["line"]
                start = max(1, line - 6)
                end = line + 16
                text = self.tools.read_file(path, start, end)
                actual_end = start + max(0, len(text.splitlines()) - 1)
                fragments.append(
                    ContextFragment(
                        "candidate_definition",
                        text,
                        f"Structural definition matching requested symbol '{symbol}'.",
                        "ast_grep_find_definitions",
                        70,
                        path,
                        start,
                        actual_end,
                        (symbol,),
                    )
                )
                evidence_count += 1
                if evidence_count >= 4:
                    break
            if evidence_count >= 4:
                break
        return self._pack("locate", subtask, fragments, char_budget)

    def build_test_context(
        self,
        subtask: SubTask,
        char_budget: int = 12_000,
    ) -> ContextPack:
        fragments = [self._subtask_fragment(subtask)]
        summary = summarize_repository(self.tools)
        fragments.append(
            ContextFragment(
                "repository_map",
                summary.render(),
                "Provide lightweight repository and test-layout orientation.",
                "list_tree",
                20,
            )
        )

        symbols = self._symbols(" ".join((subtask.objective, *subtask.acceptance_criteria)))
        interface_count = 0
        for symbol in symbols:
            definitions = json.loads(self.tools.find_definitions(symbol))
            for definition in definitions:
                if definition["kind"] not in {"class", "function", "method"}:
                    continue
                signature = definition.get("signature", "").strip()
                if not signature:
                    continue
                fragments.append(
                    ContextFragment(
                        "behavioral_interface",
                        signature,
                        f"Existing interface for requested symbol '{symbol}'; use as test-facing API evidence.",
                        "ast_grep_find_definitions",
                        75,
                        definition["path"],
                        definition["line"],
                        definition["line"],
                        (symbol,),
                    )
                )
                interface_count += 1
                if interface_count >= 3:
                    break
            if interface_count >= 3:
                break

        evidence_count = 0
        for symbol in symbols:
            results = json.loads(self.tools.find_tests_for(symbol))
            for match in results:
                path = match["path"]
                start = max(1, match["start_line"] - 5)
                end = match["end_line"] + 8
                text = self.tools.read_file(path, start, end)
                actual_end = start + max(0, len(text.splitlines()) - 1)
                fragments.append(
                    ContextFragment(
                        "test_convention",
                        text,
                        f"Nearby test references the requested symbol '{symbol}'.",
                        "ast_grep_find_tests",
                        60,
                        path,
                        start,
                        actual_end,
                        (symbol,),
                    )
                )
                evidence_count += 1
                if evidence_count >= 3:
                    break
            if evidence_count >= 3:
                break

        return self._pack("test", subtask, fragments, char_budget)

    def build_implementation_context(
        self,
        subtask: SubTask,
        accepted_test: VerificationTarget,
        red_diagnostics: tuple[str, ...],
        char_budget: int = 12_000,
    ) -> ContextPack:
        fragments = [
            self._subtask_fragment(subtask),
            ContextFragment(
                "red_diagnostics",
                "\n".join(red_diagnostics),
                "The accepted RED result is the strongest retrieval signal for implementation.",
                "red_verifier",
                95,
                required=True,
            ),
        ]
        test_sources = []
        for path in accepted_test.paths:
            text = self.tools.read_file(path)
            test_sources.append(text)
            fragments.append(
                ContextFragment(
                    "accepted_test",
                    text,
                    "Immutable failing test defines the behavior to implement.",
                    "verification_target",
                    90,
                    path,
                    1,
                    max(1, len(text.splitlines())),
                    required=True,
                )
            )

        symbols = self._symbols("\n".join(test_sources))
        definition_count = 0
        for symbol in symbols:
            definitions = json.loads(self.tools.find_definitions(symbol))
            for definition in definitions:
                path = definition["path"]
                if path in accepted_test.paths or definition["kind"] not in {
                    "class",
                    "function",
                    "method",
                }:
                    continue
                start = max(1, definition["line"] - 4)
                end = definition["line"] + 10
                text = self.tools.read_file(path, start, end)
                fragments.append(
                    ContextFragment(
                        "implicated_definition",
                        text,
                        f"Current definition of test-referenced symbol '{symbol}'.",
                        "ast_grep_find_definitions",
                        70,
                        path,
                        start,
                        end,
                        (symbol,),
                    )
                )
                definition_count += 1
                if definition_count >= 4:
                    break
            if definition_count >= 4:
                break

        summary = summarize_repository(self.tools)
        fragments.append(
            ContextFragment(
                "repository_map",
                summary.render(),
                "Provide lightweight orientation around the failing test and source.",
                "list_tree",
                20,
            )
        )
        return self._pack("implementation", subtask, fragments, char_budget)

    def _subtask_fragment(self, subtask: SubTask) -> ContextFragment:
        lines = [f"Objective: {subtask.objective}", "Acceptance criteria:"]
        lines.extend(f"- {criterion}" for criterion in subtask.acceptance_criteria)
        lines.append("Constraints:")
        lines.extend(f"- {constraint}" for constraint in subtask.constraints)
        return ContextFragment(
            "subtask",
            "\n".join(lines),
            "Required behavioral specification for this model operation.",
            "run_state",
            100,
            required=True,
        )

    def _pack(
        self,
        stage: str,
        subtask: SubTask,
        fragments: list[ContextFragment],
        char_budget: int,
    ) -> ContextPack:
        if isinstance(char_budget, bool) or not isinstance(char_budget, int) or char_budget < 1:
            raise ValueError("character budget must be a positive integer")
        fragments = self._deduplicate(fragments)
        selected: list[ContextFragment] = []
        required = [fragment for fragment in fragments if fragment.required]
        optional = sorted(
            (fragment for fragment in fragments if not fragment.required),
            key=lambda fragment: fragment.score,
            reverse=True,
        )
        header_length = len(f"## {stage} context for {subtask.id}")
        for fragment in required:
            selected.append(fragment)
            if self._render_length(stage, subtask.id, selected) > char_budget:
                raise ValueError("required context exceeds character budget")
        for fragment in optional:
            candidate = [*selected, fragment]
            if self._render_length(stage, subtask.id, candidate) <= char_budget:
                selected.append(fragment)
        ordered = tuple(sorted(selected, key=lambda fragment: fragment.score, reverse=True))
        pack = ContextPack(stage, subtask.id, ordered, char_budget)
        if pack.char_count > char_budget or header_length > char_budget:
            raise ValueError("required context exceeds character budget")
        return pack

    @staticmethod
    def _deduplicate(fragments: list[ContextFragment]) -> list[ContextFragment]:
        deduplicated: list[ContextFragment] = []
        for fragment in fragments:
            match_index = next(
                (
                    index
                    for index, existing in enumerate(deduplicated)
                    if fragment.path is not None
                    and fragment.path == existing.path
                    and fragment.kind == existing.kind
                    and fragment.start_line is not None
                    and existing.start_line is not None
                    and fragment.end_line is not None
                    and existing.end_line is not None
                    and max(fragment.start_line, existing.start_line)
                    <= min(fragment.end_line, existing.end_line)
                ),
                None,
            )
            if match_index is None:
                deduplicated.append(fragment)
                continue

            existing = deduplicated[match_index]
            start = min(existing.start_line, fragment.start_line)
            end = max(existing.end_line, fragment.end_line)
            lines = {}
            for item in (existing, fragment):
                for offset, line in enumerate(item.text.splitlines(keepends=True)):
                    lines.setdefault(item.start_line + offset, line)
            text = "".join(lines[line] for line in range(start, end + 1) if line in lines)
            deduplicated[match_index] = ContextFragment(
                existing.kind,
                text,
                "; ".join(sorted({existing.why_selected, fragment.why_selected})),
                existing.source,
                max(existing.score, fragment.score),
                existing.path,
                start,
                end,
                tuple(sorted(set(existing.symbols) | set(fragment.symbols))),
                existing.required or fragment.required,
            )
        return deduplicated

    @staticmethod
    def _render_length(stage: str, subtask_id: str, fragments: list[ContextFragment]) -> int:
        return len(ContextPack(stage, subtask_id, tuple(fragments), 1).render())

    @staticmethod
    def _symbols(text: str) -> tuple[str, ...]:
        seen = set()
        symbols = []
        for symbol in re.findall(r"\b[A-Za-z_][A-Za-z_0-9]*\b", text):
            if symbol.lower() in STOP_WORDS or symbol.startswith("test_") or len(symbol) < 3:
                continue
            if symbol not in seen:
                seen.add(symbol)
                symbols.append(symbol)
        return tuple(symbols[:8])


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
