"""Tests for context_manager: fingerprinting, cross-round matching, cross-specialist dedup."""

import pytest

from vigil.context_manager import (
    FindingFingerprint,
    extract_finding_from_comment,
    filter_cross_round_duplicates,
    fingerprint_finding,
    fingerprints_match,
    _normalize_line_range,
    _line_ranges_overlap,
)
from vigil.models import Finding, Severity


class TestNormalizeLineRange:
    """Test line range normalization for fuzzy matching."""

    def test_none_line_returns_zero_range(self):
        result = _normalize_line_range(None)
        assert result == (0, 0)

    def test_zero_line_returns_zero_range(self):
        result = _normalize_line_range(0)
        assert result == (0, 0)

    def test_positive_line_creates_range(self):
        result = _normalize_line_range(50, context_lines=2)
        assert result == (48, 52)

    def test_small_lines_bounded_at_zero(self):
        result = _normalize_line_range(1, context_lines=5)
        assert result == (0, 6)  # Max(0, -4) = 0


class TestLineRangesOverlap:
    """Test line range overlap detection."""

    def test_unlocated_range_overlaps_any(self):
        assert _line_ranges_overlap((0, 0), (10, 20))
        assert _line_ranges_overlap((10, 20), (0, 0))

    def test_overlapping_ranges(self):
        assert _line_ranges_overlap((10, 20), (15, 25))
        assert _line_ranges_overlap((15, 25), (10, 20))

    def test_touching_ranges_overlap(self):
        assert _line_ranges_overlap((10, 20), (20, 30))

    def test_non_overlapping_ranges(self):
        assert not _line_ranges_overlap((10, 15), (20, 25))
        assert not _line_ranges_overlap((20, 25), (10, 15))


class TestFingerprintFinding:
    """Test finding fingerprint generation."""

    def test_same_finding_same_fingerprint(self):
        f1 = Finding(
            file="src/auth.py",
            line=42,
            severity=Severity.high,
            category="SQL Injection",
            message="Dangerous SQL concatenation",
        )
        f2 = Finding(
            file="src/auth.py",
            line=42,
            severity=Severity.high,
            category="SQL Injection",
            message="Dangerous SQL concatenation",
        )
        assert fingerprint_finding(f1) == fingerprint_finding(f2)

    def test_different_file_different_fingerprint(self):
        f1 = Finding(
            file="src/auth.py",
            line=42,
            severity=Severity.high,
            category="SQL Injection",
            message="Dangerous SQL concatenation",
        )
        f2 = Finding(
            file="src/other.py",
            line=42,
            severity=Severity.high,
            category="SQL Injection",
            message="Dangerous SQL concatenation",
        )
        assert fingerprint_finding(f1) != fingerprint_finding(f2)

    def test_different_category_different_fingerprint(self):
        f1 = Finding(
            file="src/auth.py",
            line=42,
            severity=Severity.high,
            category="SQL Injection",
            message="Dangerous SQL",
        )
        f2 = Finding(
            file="src/auth.py",
            line=42,
            severity=Severity.high,
            category="XSS",
            message="Dangerous SQL",
        )
        assert fingerprint_finding(f1) != fingerprint_finding(f2)

    def test_line_range_includes_context(self):
        f1 = Finding(
            file="src/auth.py",
            line=42,
            severity=Severity.high,
            category="Issue",
            message="Test",
        )
        fp1 = fingerprint_finding(f1)
        # Line range should include context
        assert fp1.line_range == (40, 44)  # 42 +/- 2


class TestFingerprintsMatch:
    """Test fingerprint matching logic."""

    def test_identical_fingerprints_match(self):
        f = Finding(
            file="src/auth.py",
            line=42,
            severity=Severity.high,
            category="SQL Injection",
            message="Dangerous SQL",
        )
        fp = fingerprint_finding(f)
        assert fingerprints_match(fp, fp)

    def test_different_files_dont_match(self):
        f1 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                     category="Issue", message="Test")
        f2 = Finding(file="src/other.py", line=42, severity=Severity.high,
                     category="Issue", message="Test")
        fp1, fp2 = fingerprint_finding(f1), fingerprint_finding(f2)
        assert not fingerprints_match(fp1, fp2)

    def test_different_categories_dont_match(self):
        f1 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                     category="SQL Injection", message="Test")
        f2 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                     category="XSS", message="Test")
        fp1, fp2 = fingerprint_finding(f1), fingerprint_finding(f2)
        assert not fingerprints_match(fp1, fp2)

    def test_different_message_hash_dont_match(self):
        f1 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                     category="Issue", message="Problem A")
        f2 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                     category="Issue", message="Problem B")
        fp1, fp2 = fingerprint_finding(f1), fingerprint_finding(f2)
        assert not fingerprints_match(fp1, fp2)

    def test_slightly_shifted_lines_match_fuzzy(self):
        """Lines that are close together should match (fuzzy mode)."""
        f1 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                     category="Issue", message="Test problem")
        f2 = Finding(file="src/auth.py", line=44, severity=Severity.high,
                     category="Issue", message="Test problem")
        fp1, fp2 = fingerprint_finding(f1), fingerprint_finding(f2)
        # 42 +/- 2 = [40, 44], 44 +/- 2 = [42, 46] — they overlap
        assert fingerprints_match(fp1, fp2, exact_line=False)

    def test_far_apart_lines_dont_match_fuzzy(self):
        """Lines far apart shouldn't match even in fuzzy mode."""
        f1 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                     category="Issue", message="Test problem")
        f2 = Finding(file="src/auth.py", line=100, severity=Severity.high,
                     category="Issue", message="Test problem")
        fp1, fp2 = fingerprint_finding(f1), fingerprint_finding(f2)
        assert not fingerprints_match(fp1, fp2, exact_line=False)

    def test_exact_line_mode_requires_same_range(self):
        """Exact line mode requires ranges to be identical."""
        f1 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                     category="Issue", message="Test")
        f2 = Finding(file="src/auth.py", line=44, severity=Severity.high,
                     category="Issue", message="Test")
        fp1, fp2 = fingerprint_finding(f1), fingerprint_finding(f2)
        assert not fingerprints_match(fp1, fp2, exact_line=True)


class TestExtractFindingFromComment:
    """Test extracting findings from Vigil comment bodies."""

    def test_extract_basic_finding(self):
        body = (
            "🔴 **[HIGH]** [SQL Injection] **Security** `VGL-abc123`\n\n"
            "Dangerous SQL concatenation in query\n\n"
            "**Suggestion:** Use parameterized queries"
        )
        result = extract_finding_from_comment(body, "src/auth.py", 42)
        assert result is not None
        assert result.file == "src/auth.py"
        assert result.line == 42
        assert result.severity == Severity.high
        assert result.category == "SQL Injection"
        assert "concatenation" in result.message

    def test_extract_critical_finding(self):
        body = "🔴 **[CRITICAL]** [Secrets Leak] Hardcoded API key"
        result = extract_finding_from_comment(body, "src/config.py", 10)
        assert result is not None
        assert result.severity == Severity.critical

    def test_extract_medium_finding(self):
        body = "🟡 **[MEDIUM]** [Design] Missing validation"
        result = extract_finding_from_comment(body, "src/handlers.py", 20)
        assert result is not None
        assert result.severity == Severity.medium

    def test_extract_low_finding(self):
        body = "🔵 **[LOW]** [DX] Confusing error message"
        result = extract_finding_from_comment(body, "src/errors.py", 5)
        assert result is not None
        assert result.severity == Severity.low

    def test_extract_with_file_path_fallback(self):
        """If file_path is None, should use 'unknown'."""
        body = "🔴 **[HIGH]** [Issue] Problem here"
        result = extract_finding_from_comment(body, None, 42)
        assert result is not None
        assert result.file == "unknown"

    def test_extract_invalid_severity_returns_none(self):
        """If severity tag not found, extraction should fail."""
        body = "Some comment without severity tag"
        result = extract_finding_from_comment(body, "src/file.py", 42)
        assert result is None

    def test_extract_category_from_bracket(self):
        body = "🔴 **[HIGH]** [My Custom Category] Some issue"
        result = extract_finding_from_comment(body, "src/file.py", 42)
        assert result is not None
        assert result.category == "My Custom Category"


class TestFilterCrossRoundDuplicates:
    """Test filtering findings against existing comments."""

    def test_empty_existing_returns_all_findings(self):
        findings = [
            Finding(file="src/auth.py", line=42, severity=Severity.high,
                   category="SQL Injection", message="Dangerous SQL"),
            Finding(file="src/api.py", line=10, severity=Severity.medium,
                   category="Design", message="Missing validation"),
        ]
        result = filter_cross_round_duplicates(findings, [])
        assert result == findings

    def test_filters_exact_match(self):
        findings = [
            Finding(file="src/auth.py", line=42, severity=Severity.high,
                   category="SQL Injection", message="Dangerous SQL"),
        ]
        existing = [
            {
                "path": "src/auth.py",
                "line": 42,
                "body": "🔴 **[HIGH]** [SQL Injection] Dangerous SQL",
            }
        ]
        result = filter_cross_round_duplicates(findings, existing)
        assert len(result) == 0

    def test_keeps_different_findings(self):
        findings = [
            Finding(file="src/auth.py", line=42, severity=Severity.high,
                   category="SQL Injection", message="New issue"),
        ]
        existing = [
            {
                "path": "src/auth.py",
                "line": 42,
                "body": "🔴 **[HIGH]** [SQL Injection] Old issue",
            }
        ]
        result = filter_cross_round_duplicates(findings, existing)
        # Different message hash — should be kept
        assert len(result) == 1

    def test_filters_by_category_and_file(self):
        findings = [
            Finding(file="src/auth.py", line=42, severity=Severity.high,
                   category="SQL Injection", message="SQL problem"),
        ]
        existing = [
            {
                "path": "src/other.py",
                "line": 42,
                "body": "🔴 **[HIGH]** [SQL Injection] SQL problem",
            }
        ]
        result = filter_cross_round_duplicates(findings, existing)
        # Different file — should be kept
        assert len(result) == 1

    def test_filters_unlocated_finding(self):
        """Finding with line=None should match if file and category match."""
        findings = [
            Finding(file="src/auth.py", line=None, severity=Severity.high,
                   category="SQL Injection", message="SQL problem"),
        ]
        existing = [
            {
                "path": "src/auth.py",
                "line": None,
                "body": "🔴 **[HIGH]** [SQL Injection] SQL problem",
            }
        ]
        result = filter_cross_round_duplicates(findings, existing)
        assert len(result) == 0
