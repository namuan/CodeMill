from codemill.models import (
    VerificationFailureKind,
    VerificationPurpose,
    VerificationTarget,
)
from codemill.pytest_verifier import PytestVerifier


def test_classifies_focused_assertion_failure_as_expected_red(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_feature.py").write_text("def test_feature():\n    assert None == 3\n")
    verifier = PytestVerifier(tmp_path)

    result = verifier.verify(
        VerificationPurpose.RED,
        VerificationTarget(("tests/test_feature.py",)),
    )

    assert not result.ok
    assert result.failure_kind is VerificationFailureKind.EXPECTED_BEHAVIOR
    assert any("test_feature" in diagnostic for diagnostic in result.diagnostics)


def test_classifies_assertion_with_compact_pytest_trace_as_expected_red():
    output = (
        "FAILED tests/test_feature.py::test_feature - AssertionError\n"
        "tests/test_feature.py:2: AssertionError\nE assert 1 == 2"
    )

    assert PytestVerifier._is_assertion_failure(
        output,
        VerificationTarget(("tests/test_feature.py",)),
    )


def test_accepts_attribute_error_for_explicitly_requested_missing_method():
    output = (
        "FAILED tests/test_status.py::test_status - AttributeError\n"
        "tests/test_status.py:2: in test_status\n"
        "    tools.git_status()\n"
        "E   AttributeError: 'LocalRepositoryTools' object has no attribute 'git_status'"
    )

    assert PytestVerifier._is_assertion_failure(
        output,
        VerificationTarget(
            ("tests/test_status.py",),
            expected_missing_symbols=("LocalRepositoryTools.git_status",),
        ),
    )
    assert not PytestVerifier._is_assertion_failure(
        output,
        VerificationTarget(
            ("tests/test_status.py",),
            expected_missing_symbols=("LocalRepositoryTools.other_method",),
        ),
    )
    wrong_receiver = output.replace("'LocalRepositoryTools'", "'NoneType'")
    assert not PytestVerifier._is_assertion_failure(
        wrong_receiver,
        VerificationTarget(
            ("tests/test_status.py",),
            expected_missing_symbols=("LocalRepositoryTools.git_status",),
        ),
    )


def test_rejects_assertion_red_when_another_test_has_an_attribute_error():
    output = (
        "FAILED tests/test_feature.py::test_missing_method - AttributeError\n"
        "FAILED tests/test_feature.py::test_behavior - AssertionError\n"
        "tests/test_feature.py:3: in test_missing_method\n"
        "    subject.new_method()\n"
        "E   AttributeError: method is missing\n"
        "tests/test_feature.py:8: in test_behavior\n"
        "    assert actual == expected\n"
        "E   AssertionError: assert 1 == 2"
    )

    assert not PytestVerifier._is_assertion_failure(
        output,
        VerificationTarget(("tests/test_feature.py",)),
    )


def test_classifies_assertion_error_summary_as_expected_red():
    output = (
        "FAILED test_feature.py::test_feature - AssertionError\n"
        "test_feature.py:2: in test_feature\n"
        "    assert actual == expected\n"
        "E   AssertionError: assert 'actual' == 'expected'"
    )

    assert PytestVerifier._is_assertion_failure(
        output,
        VerificationTarget(("test_feature.py",)),
    )


def test_classifies_collection_error_as_unexpected_red(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_feature.py").write_text("def test_feature(:\n    assert True\n")
    verifier = PytestVerifier(tmp_path)

    result = verifier.verify(
        VerificationPurpose.RED,
        VerificationTarget(("tests/test_feature.py",)),
    )

    assert not result.ok
    assert result.failure_kind is VerificationFailureKind.OTHER
    assert any("SyntaxError" in diagnostic for diagnostic in result.diagnostics)


def test_does_not_classify_assertion_in_helper_as_behavioral_red(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tmp_path / "helper.py").write_text("def check():\n    assert None == 3\n")
    (tests / "test_feature.py").write_text(
        "from helper import check\n\ndef test_feature():\n    check()\n"
    )
    verifier = PytestVerifier(tmp_path)

    result = verifier.verify(
        VerificationPurpose.RED,
        VerificationTarget(("tests/test_feature.py",)),
    )

    assert not result.ok
    assert result.failure_kind is VerificationFailureKind.OTHER


def test_passes_focused_green_and_final_verification(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_feature.py").write_text("def test_feature():\n    assert 1 + 1 == 2\n")
    verifier = PytestVerifier(tmp_path)
    target = VerificationTarget(("tests/test_feature.py",))

    focused = verifier.verify(VerificationPurpose.GREEN, target)
    no_change = verifier.verify(VerificationPurpose.NO_CHANGE, target)
    final = verifier.verify(VerificationPurpose.FINAL)

    assert focused.ok
    assert no_change.ok
    assert no_change.command[-1] == "tests/test_feature.py"
    assert final.ok
    assert focused.command[1:4] == ("-B", "-m", "pytest")
    assert focused.exit_code == 0
    assert focused.duration_seconds >= 0


def test_requires_target_for_focused_verification(tmp_path):
    verifier = PytestVerifier(tmp_path)

    result = verifier.verify(VerificationPurpose.RED)

    assert not result.ok
    assert result.failure_kind is VerificationFailureKind.OTHER
    assert "focused verification requires a test target" in result.diagnostics[0]


def test_rejects_test_targets_outside_repository(tmp_path):
    verifier = PytestVerifier(tmp_path)

    result = verifier.verify(
        VerificationPurpose.GREEN,
        VerificationTarget(("../outside_test.py",)),
    )

    assert not result.ok
    assert "escapes repository root" in result.diagnostics[0]
