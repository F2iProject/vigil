"""Tests for cross_specialist_dedup: merging findings from multiple specialists."""

import pytest

from vigil.cross_specialist_dedup import (
    MergedFinding,
    merge_specialist_findings,
    format_merged_finding_comment,
    _severity_rank,
)
from vigil.models import Finding, PersonaVerdict, Severity


class TestSeverityRank:
    """Test severity ranking."""

    def test_critical_highest(self):
        assert _severity_rank(Severity.critical) > _severity_rank(Severity.high)

    def test_high_greater_medium(self):
        assert _severity_rank(Severity.high) > _severity_rank(Severity.medium)

    def test_medium_greater_low(self):
        assert _severity_rank(Severity.medium) > _severity_rank(Severity.low)

    def test_ranking_order(self):
        ranks = [_severity_rank(s) for s in [Severity.critical, Severity.high,
                                              Severity.medium, Severity.low]]
        assert ranks == sorted(ranks, reverse=True)


class TestMergeSpecialistFindings:
    """Test merging findings across specialists."""

    def test_single_specialist_no_merge(self):
        f1 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                    category="SQL Injection", message="Dangerous SQL")
        v1 = PersonaVerdict(
            persona="Security",
            session_id="VGL-abc123",
            decision="REQUEST_CHANGES",
            checks={},
            findings=[f1],
            observations=[],
        )
        deduped, merged = merge_specialist_findings([v1])
        assert len(deduped) == 1
        assert len(merged) == 0

    def test_two_specialists_same_finding(self):
        """Two specialists flagging identical issue should merge."""
        f1 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                    category="SQL Injection", message="Dangerous SQL")
        f2 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                    category="SQL Injection", message="Dangerous SQL")
        v1 = PersonaVerdict(
            persona="Security",
            session_id="VGL-111111",
            decision="REQUEST_CHANGES",
            checks={},
            findings=[f1],
            observations=[],
        )
        v2 = PersonaVerdict(
            persona="Logic",
            session_id="VGL-222222",
            decision="REQUEST_CHANGES",
            checks={},
            findings=[f2],
            observations=[],
        )
        deduped, merged = merge_specialist_findings([v1, v2])
        # Should merge into 1 finding
        assert len(deduped) == 1
        assert len(merged) == 1
        assert merged[0].count == 2
        assert set(merged[0].specialists) == {"Security", "Logic"}

    def test_two_specialists_different_findings(self):
        """Two specialists with different findings should not merge."""
        f1 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                    category="SQL Injection", message="Dangerous SQL")
        f2 = Finding(file="src/auth.py", line=50, severity=Severity.high,
                    category="SQL Injection", message="Different SQL issue")
        v1 = PersonaVerdict(
            persona="Security",
            session_id="VGL-111111",
            decision="REQUEST_CHANGES",
            checks={},
            findings=[f1],
            observations=[],
        )
        v2 = PersonaVerdict(
            persona="Logic",
            session_id="VGL-222222",
            decision="REQUEST_CHANGES",
            checks={},
            findings=[f2],
            observations=[],
        )
        deduped, merged = merge_specialist_findings([v1, v2])
        # Different findings — no merge
        assert len(deduped) == 2
        assert len(merged) == 0

    def test_highest_severity_chosen_as_representative(self):
        """When merging, highest severity should be representative."""
        f_low = Finding(file="src/auth.py", line=42, severity=Severity.low,
                       category="DX", message="Issue")
        f_high = Finding(file="src/auth.py", line=42, severity=Severity.high,
                        category="DX", message="Issue")
        v1 = PersonaVerdict(
            persona="DX",
            session_id="VGL-111111",
            decision="APPROVE",
            checks={},
            findings=[f_low],
            observations=[],
        )
        v2 = PersonaVerdict(
            persona="Testing",
            session_id="VGL-222222",
            decision="REQUEST_CHANGES",
            checks={},
            findings=[f_high],
            observations=[],
        )
        deduped, merged = merge_specialist_findings([v1, v2])
        assert len(merged) == 1
        # Representative should be the high severity one
        assert merged[0].finding.severity == Severity.high

    def test_multiple_findings_partial_merge(self):
        """Multiple findings with some merging and some unique."""
        # Two specialists find same SQL issue
        sql_f1 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                        category="SQL Injection", message="Dangerous SQL")
        sql_f2 = Finding(file="src/auth.py", line=42, severity=Severity.high,
                        category="SQL Injection", message="Dangerous SQL")
        
        # Different finding from another specialist
        design_f = Finding(file="src/api.py", line=10, severity=Severity.medium,
                          category="Design", message="Missing validation")
        
        v1 = PersonaVerdict(
            persona="Security",
            session_id="VGL-111111",
            decision="REQUEST_CHANGES",
            checks={},
            findings=[sql_f1],
            observations=[],
        )
        v2 = PersonaVerdict(
            persona="Logic",
            session_id="VGL-222222",
            decision="REQUEST_CHANGES",
            checks={},
            findings=[sql_f2, design_f],
            observations=[],
        )
        deduped, merged = merge_specialist_findings([v1, v2])
        # 2 findings in result: 1 merged SQL + 1 unique Design
        assert len(deduped) == 2
        assert len(merged) == 1  # Only the SQL was merged
        assert merged[0].count == 2


class TestFormatMergedFindingComment:
    """Test formatting merged findings for inline comments."""

    def test_basic_merged_format(self):
        f = Finding(file="src/auth.py", line=42, severity=Severity.high,
                   category="SQL Injection", message="Dangerous SQL")
        result = format_merged_finding_comment(f, ["Security", "Logic"])
        assert "🟠" in result  # High severity emoji (orange circle)
        assert "[HIGH]" in result
        assert "[SQL Injection]" in result
        assert "Flagged by:" in result
        assert "Security" in result
        assert "Logic" in result

    def test_format_with_suggestion(self):
        f = Finding(file="src/auth.py", line=42, severity=Severity.high,
                   category="SQL Injection", message="Dangerous SQL",
                   suggestion="Use parameterized queries")
        result = format_merged_finding_comment(f, ["Security"])
        assert "Suggestion:" in result
        assert "parameterized" in result

    def test_format_includes_session_ids(self):
        f = Finding(file="src/auth.py", line=42, severity=Severity.high,
                   category="SQL Injection", message="Dangerous SQL")
        session_ids = {"Security": "VGL-abc123", "Logic": "VGL-def456"}
        result = format_merged_finding_comment(f, ["Security", "Logic"], session_ids)
        assert "VGL-abc123" in result
        assert "VGL-def456" in result

    def test_critical_severity_icon(self):
        f = Finding(file="src/config.py", line=1, severity=Severity.critical,
                   category="Secrets", message="API key exposed")
        result = format_merged_finding_comment(f, ["Security"])
        assert "[CRITICAL]" in result

    def test_medium_severity_icon(self):
        f = Finding(file="src/db.py", line=20, severity=Severity.medium,
                   category="Performance", message="N+1 query")
        result = format_merged_finding_comment(f, ["Performance"])
        assert "[MEDIUM]" in result

    def test_low_severity_icon(self):
        f = Finding(file="src/errors.py", line=5, severity=Severity.low,
                   category="DX", message="Confusing message")
        result = format_merged_finding_comment(f, ["DX"])
        assert "[LOW]" in result


class TestMergedFindingNamedTuple:
    """Test MergedFinding data structure."""

    def test_merged_finding_creation(self):
        f = Finding(file="src/auth.py", line=42, severity=Severity.high,
                   category="SQL Injection", message="Dangerous SQL")
        f_copy = Finding(file="src/auth.py", line=42, severity=Severity.high,
                        category="SQL Injection", message="Dangerous SQL")
        mf = MergedFinding(
            finding=f,
            specialists=["Security", "Logic"],
            count=2,
            original_findings=[f, f_copy],
        )
        assert mf.finding == f
        assert mf.count == 2
        assert len(mf.specialists) == 2
        assert len(mf.original_findings) == 2
