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
    final = verifier.verify(VerificationPurpose.FINAL)

    assert focused.ok
    assert final.ok
    assert focused.command[1:3] == ("-m", "pytest")
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
