"""SQLite audit log for review traceability.

Every review gets an immutable record: commit SHA, model, decisions, session IDs.
Two tables: reviews (one row per review) and verdicts (one row per specialist).
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import ReviewResult


def _default_db_path() -> Path:
    """Default audit DB location: ~/.vigil/audit.db"""
    return Path.home() / ".vigil" / "audit.db"


def _init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            commit_sha TEXT NOT NULL,
            pr_url TEXT NOT NULL,
            model TEXT NOT NULL,
            profile TEXT NOT NULL,
            decision TEXT NOT NULL,
            summary TEXT NOT NULL,
            total_findings INTEGER NOT NULL,
            total_observations INTEGER NOT NULL,
            lead_findings INTEGER NOT NULL,
            result_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS verdicts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id INTEGER NOT NULL REFERENCES reviews(id),
            persona TEXT NOT NULL,
            session_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            findings INTEGER NOT NULL,
            observations INTEGER NOT NULL,
            checks_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_reviews_commit ON reviews(commit_sha);
        CREATE INDEX IF NOT EXISTS idx_reviews_pr ON reviews(pr_url);
        CREATE INDEX IF NOT EXISTS idx_verdicts_review ON verdicts(review_id);
        CREATE INDEX IF NOT EXISTS idx_verdicts_session ON verdicts(session_id);
    """)


def write_audit_entry(
    result: ReviewResult,
    profile: str = "",
    db_path: Path | None = None,
) -> Path:
    """Write one audit record per review to the SQLite database.

    Inserts into `reviews` (one row) and `verdicts` (one row per specialist).
    The full ReviewResult JSON is stored in `result_json` for complete
    reproducibility.

    Returns the path to the database.
    """
    db_path = db_path or _default_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        _init_db(conn)

        now = datetime.now(timezone.utc).isoformat()
        total_findings = sum(len(v.findings) for v in result.specialist_verdicts) + len(result.lead_findings)

        cursor = conn.execute(
            """INSERT INTO reviews
               (timestamp, commit_sha, pr_url, model, profile, decision, summary,
                total_findings, total_observations, lead_findings, result_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                now,
                result.commit_sha,
                result.pr_url,
                result.model,
                profile,
                result.decision,
                result.summary,
                total_findings,
                len(result.observations),
                len(result.lead_findings),
                result.model_dump_json(),
            ),
        )
        review_id = cursor.lastrowid

        for v in result.specialist_verdicts:
            conn.execute(
                """INSERT INTO verdicts
                   (review_id, persona, session_id, decision, findings, observations, checks_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    review_id,
                    v.persona,
                    v.session_id,
                    v.decision,
                    len(v.findings),
                    len(v.observations),
                    json.dumps(v.checks),
                ),
            )

        conn.commit()
    finally:
        conn.close()

    return db_path
