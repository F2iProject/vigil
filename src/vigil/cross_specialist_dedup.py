"""Cross-specialist finding deduplication — merge overlapping findings in same round.

When multiple specialists flag the same code issue at the same location,
Vigil merges them into a single comment showing which specialists flagged it.
This prevents review spam while showing consensus.
"""

import logging
from typing import NamedTuple

from .context_manager import (
    FindingFingerprint,
    find_cross_specialist_duplicates,
    fingerprint_finding,
)
from .models import Finding, PersonaVerdict, Severity
from .utils import severity_emoji

log = logging.getLogger(__name__)


class MergedFinding(NamedTuple):
    """A finding that was flagged by multiple specialists, now merged."""

    finding: Finding  # Representative finding (highest severity)
    specialists: list[str]  # List of specialist names who flagged it
    count: int  # Number of specialists who flagged it (len(specialists))
    original_findings: list[Finding]  # All original findings before merge


def merge_specialist_findings(
    verdicts: list[PersonaVerdict],
) -> tuple[list[Finding], list[MergedFinding]]:
    """Merge findings from multiple specialists, grouping overlapping issues.

    When specialists flag the same issue (same file, line, category, message),
    they're merged into a single Finding with specialist attribution.

    Args:
        verdicts: List of PersonaVerdict objects from specialists

    Returns:
        (deduped_findings, merged_info) tuple:
        - deduped_findings: List of findings with cross-specialist duplicates merged
        - merged_info: List of MergedFinding info for each merged group
    """
    # Collect all specialist findings with attribution
    specialist_findings: list[tuple[str, Finding]] = []
    for v in verdicts:
        for f in v.findings:
            specialist_findings.append((v.persona, f))

    if not specialist_findings:
        return [], []

    # Group by fingerprint
    groups = find_cross_specialist_duplicates(specialist_findings)

    deduped_findings: list[Finding] = []
    merged_info: list[MergedFinding] = []

    for fp, group in groups.items():
        if len(group) == 1:
            # Single specialist — keep as-is
            _, finding = group[0]
            deduped_findings.append(finding)
        else:
            # Multiple specialists — merge
            specialists = [name for name, _ in group]
            findings = [f for _, f in group]

            # Representative finding: pick highest severity
            rep_finding = max(findings, key=lambda f: _severity_rank(f.severity))

            # Preserve the representative but track the merge
            deduped_findings.append(rep_finding)
            merged_info.append(
                MergedFinding(
                    finding=rep_finding,
                    specialists=specialists,
                    count=len(specialists),
                    original_findings=findings,
                )
            )

            log.info(
                "Merged %d specialist findings: %s:%s [%s] — %s",
                len(specialists),
                rep_finding.file,
                rep_finding.line,
                rep_finding.category,
                ", ".join(specialists),
            )

    return deduped_findings, merged_info


def _severity_rank(severity: Severity) -> int:
    """Map severity to a numeric rank for comparison. Higher = more severe."""
    rank_map = {
        Severity.critical: 4,
        Severity.high: 3,
        Severity.medium: 2,
        Severity.low: 1,
    }
    return rank_map.get(severity, 0)


def format_merged_finding_comment(
    finding: Finding,
    specialists: list[str],
    session_ids: dict[str, str] | None = None,
) -> str:
    """Format a merged finding for inline comment display.

    Shows which specialists flagged the issue, with their session IDs.

    Args:
        finding: The representative Finding
        specialists: List of specialist names who flagged it
        session_ids: Optional dict mapping specialist name -> session_id

    Returns:
        Formatted markdown for the merged finding
    """
    icon = severity_emoji(finding.severity)
    session_ids = session_ids or {}

    # Build specialist attribution with session IDs
    specialist_lines = []
    for spec in specialists:
        sid = session_ids.get(spec)
        if sid:
            specialist_lines.append(f"**{spec}** `{sid}`")
        else:
            specialist_lines.append(f"**{spec}**")
    specialist_text = ", ".join(specialist_lines)

    # Build the comment body
    suggestion = f"\n\n**Suggestion:** {finding.suggestion}" if finding.suggestion else ""

    return (
        f"{icon} **[{finding.severity.value.upper()}]** [{finding.category}]\n"
        f"🔍 Flagged by: {specialist_text}\n\n"
        f"{finding.message}{suggestion}"
    )


def annotate_findings_with_specialist_context(
    findings: list[Finding],
    merged_info: list[MergedFinding],
) -> list[dict]:
    """Annotate findings with specialist context for later formatting.

    Attaches metadata about which specialists flagged each finding,
    enabling formatted output to show consensus.

    Args:
        findings: The deduped findings list
        merged_info: List of MergedFinding objects

    Returns:
        List of dicts with finding + specialist metadata
    """
    # Build a lookup from finding ID to merged info
    merged_lookup: dict[int, MergedFinding] = {
        id(info.finding): info for info in merged_info
    }

    result = []
    for f in findings:
        if id(f) in merged_lookup:
            info = merged_lookup[id(f)]
            result.append({
                "finding": f,
                "is_merged": True,
                "specialists": info.specialists,
                "count": info.count,
            })
        else:
            result.append({
                "finding": f,
                "is_merged": False,
                "specialists": [],
                "count": 0,
            })
    return result
