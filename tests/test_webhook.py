"""Tests for webhook server: signature verification, event routing, payload handling."""

import hashlib
import hmac
import json

import pytest

from vigil.webhook import (
    _extract_pr_url_from_event,
    _should_dismiss,
    _should_review,
    _verify_signature,
)


# ---------- _verify_signature ----------

class TestVerifySignature:

    def _sign(self, payload: bytes, secret: str) -> str:
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return f"sha256={sig}"

    def test_valid_signature(self):
        payload = b'{"hello": "world"}'
        secret = "test-secret"
        sig = self._sign(payload, secret)
        assert _verify_signature(payload, sig, secret) is True

    def test_invalid_signature(self):
        payload = b'{"hello": "world"}'
        assert _verify_signature(payload, "sha256=badbadbad", "test-secret") is False

    def test_missing_sha256_prefix(self):
        payload = b'{"hello": "world"}'
        secret = "test-secret"
        raw_sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        assert _verify_signature(payload, raw_sig, secret) is False

    def test_empty_signature(self):
        assert _verify_signature(b"data", "", "secret") is False

    def test_different_payload(self):
        secret = "test-secret"
        sig = self._sign(b"original", secret)
        assert _verify_signature(b"tampered", sig, secret) is False


# ---------- _extract_pr_url_from_event ----------

class TestExtractPrUrl:

    def test_pull_request_event(self):
        payload = {
            "pull_request": {
                "html_url": "https://github.com/owner/repo/pull/42"
            }
        }
        assert _extract_pr_url_from_event("pull_request", payload) == "https://github.com/owner/repo/pull/42"

    def test_issue_comment_on_pr(self):
        payload = {
            "issue": {
                "pull_request": {
                    "html_url": "https://github.com/owner/repo/pull/42"
                }
            }
        }
        assert _extract_pr_url_from_event("issue_comment", payload) == "https://github.com/owner/repo/pull/42"

    def test_issue_comment_not_on_pr(self):
        payload = {
            "issue": {
                "title": "Just an issue"
            }
        }
        assert _extract_pr_url_from_event("issue_comment", payload) is None

    def test_unknown_event(self):
        assert _extract_pr_url_from_event("push", {"ref": "refs/heads/main"}) is None

    def test_empty_payload(self):
        assert _extract_pr_url_from_event("pull_request", {}) is None


# ---------- _should_review ----------

class TestShouldReview:

    def test_pr_opened(self):
        payload = {
            "action": "opened",
            "pull_request": {"draft": False},
            "sender": {"login": "developer"},
        }
        assert _should_review("pull_request", payload) is True

    def test_pr_reopened(self):
        payload = {
            "action": "reopened",
            "pull_request": {"draft": False},
            "sender": {"login": "developer"},
        }
        assert _should_review("pull_request", payload) is True

    def test_pr_ready_for_review(self):
        payload = {
            "action": "ready_for_review",
            "pull_request": {"draft": False},
            "sender": {"login": "developer"},
        }
        assert _should_review("pull_request", payload) is True

    def test_pr_synchronize_ignored(self):
        payload = {
            "action": "synchronize",
            "pull_request": {"draft": False},
            "sender": {"login": "developer"},
        }
        assert _should_review("pull_request", payload) is False

    def test_pr_closed_ignored(self):
        payload = {
            "action": "closed",
            "pull_request": {"draft": False},
            "sender": {"login": "developer"},
        }
        assert _should_review("pull_request", payload) is False

    def test_draft_pr_ignored(self):
        payload = {
            "action": "opened",
            "pull_request": {"draft": True},
            "sender": {"login": "developer"},
        }
        assert _should_review("pull_request", payload) is False

    def test_bot_pr_ignored(self):
        payload = {
            "action": "opened",
            "pull_request": {"draft": False},
            "sender": {"login": "dependabot[bot]"},
        }
        assert _should_review("pull_request", payload) is False

    def test_comment_vigil_review(self):
        payload = {
            "action": "created",
            "issue": {"pull_request": {"html_url": "..."}},
            "comment": {"body": "/vigil review"},
        }
        assert _should_review("issue_comment", payload) is True

    def test_comment_vigil_review_with_extra_text(self):
        payload = {
            "action": "created",
            "issue": {"pull_request": {"html_url": "..."}},
            "comment": {"body": "Please /vigil review this PR"},
        }
        assert _should_review("issue_comment", payload) is True

    def test_comment_without_command(self):
        payload = {
            "action": "created",
            "issue": {"pull_request": {"html_url": "..."}},
            "comment": {"body": "Looks good to me"},
        }
        assert _should_review("issue_comment", payload) is False

    def test_comment_on_issue_not_pr(self):
        payload = {
            "action": "created",
            "issue": {"title": "Bug report"},
            "comment": {"body": "/vigil review"},
        }
        assert _should_review("issue_comment", payload) is False

    def test_comment_edited_ignored(self):
        payload = {
            "action": "edited",
            "issue": {"pull_request": {"html_url": "..."}},
            "comment": {"body": "/vigil review"},
        }
        assert _should_review("issue_comment", payload) is False

    def test_unknown_event(self):
        assert _should_review("push", {}) is False


# ---------- _should_dismiss ----------

class TestShouldDismiss:

    def test_resolved_comment(self):
        payload = {
            "action": "created",
            "issue": {"pull_request": {"html_url": "..."}},
            "comment": {"body": "resolved"},
        }
        assert _should_dismiss("issue_comment", payload) is True

    def test_resolve_comment(self):
        payload = {
            "action": "created",
            "issue": {"pull_request": {"html_url": "..."}},
            "comment": {"body": "Resolve"},
        }
        assert _should_dismiss("issue_comment", payload) is True

    def test_fixed_comment(self):
        payload = {
            "action": "created",
            "issue": {"pull_request": {"html_url": "..."}},
            "comment": {"body": "Fixed"},
        }
        assert _should_dismiss("issue_comment", payload) is True

    def test_issue_link_comment(self):
        payload = {
            "action": "created",
            "issue": {"pull_request": {"html_url": "..."}},
            "comment": {"body": "#45"},
        }
        assert _should_dismiss("issue_comment", payload) is True

    def test_resolved_with_issue_link(self):
        payload = {
            "action": "created",
            "issue": {"pull_request": {"html_url": "..."}},
            "comment": {"body": "Resolved in #123"},
        }
        assert _should_dismiss("issue_comment", payload) is True

    def test_vigil_review_takes_priority(self):
        payload = {
            "action": "created",
            "issue": {"pull_request": {"html_url": "..."}},
            "comment": {"body": "/vigil review"},
        }
        assert _should_dismiss("issue_comment", payload) is False

    def test_random_comment_not_dismiss(self):
        payload = {
            "action": "created",
            "issue": {"pull_request": {"html_url": "..."}},
            "comment": {"body": "This looks great!"},
        }
        assert _should_dismiss("issue_comment", payload) is False

    def test_not_on_pr(self):
        payload = {
            "action": "created",
            "issue": {"title": "Bug"},
            "comment": {"body": "resolved"},
        }
        assert _should_dismiss("issue_comment", payload) is False

    def test_wrong_event(self):
        assert _should_dismiss("pull_request", {}) is False

    def test_edited_ignored(self):
        payload = {
            "action": "edited",
            "issue": {"pull_request": {"html_url": "..."}},
            "comment": {"body": "resolved"},
        }
        assert _should_dismiss("issue_comment", payload) is False


# ---------- create_app integration tests ----------

class TestCreateApp:

    @pytest.fixture
    def client(self):
        """Create a test client for the webhook app."""
        from fastapi.testclient import TestClient
        from vigil.webhook import create_app

        app = create_app(webhook_secret=None, model="test-model", profile="default")
        return TestClient(app)

    @pytest.fixture
    def signed_client(self):
        """Create a test client with signature verification enabled."""
        from fastapi.testclient import TestClient
        from vigil.webhook import create_app

        secret = "test-webhook-secret"
        app = create_app(webhook_secret=secret, model="test-model", profile="default")
        return TestClient(app), secret

    def test_health_check(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_ping_event(self, client):
        resp = client.post(
            "/webhook",
            json={"zen": "Keep it logically awesome."},
            headers={"X-GitHub-Event": "ping"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pong"

    def test_skips_unhandled_event(self, client):
        resp = client.post(
            "/webhook",
            json={"ref": "refs/heads/main"},
            headers={"X-GitHub-Event": "push"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

    def test_skips_pr_synchronize(self, client):
        payload = {
            "action": "synchronize",
            "pull_request": {"draft": False, "html_url": "https://github.com/o/r/pull/1"},
            "sender": {"login": "dev"},
        }
        resp = client.post(
            "/webhook",
            json=payload,
            headers={"X-GitHub-Event": "pull_request"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "skipped"

    def test_invalid_signature_rejected(self, signed_client):
        client, secret = signed_client
        resp = client.post(
            "/webhook",
            content=b'{"action":"opened"}',
            headers={
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": "sha256=invalid",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401

    def test_valid_signature_accepted(self, signed_client):
        client, secret = signed_client
        payload = json.dumps({"zen": "Keep it simple."}).encode()
        sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        resp = client.post(
            "/webhook",
            content=payload,
            headers={
                "X-GitHub-Event": "ping",
                "X-Hub-Signature-256": sig,
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "pong"

    def test_pr_opened_accepted(self, client):
        """PR opened event should be accepted (review runs in background thread)."""
        payload = {
            "action": "opened",
            "pull_request": {
                "draft": False,
                "html_url": "https://github.com/owner/repo/pull/42",
            },
            "sender": {"login": "developer"},
        }
        resp = client.post(
            "/webhook",
            json=payload,
            headers={"X-GitHub-Event": "pull_request"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["action"] == "review"
        assert data["pr_url"] == "https://github.com/owner/repo/pull/42"

    def test_dismiss_resolved_accepted(self, client):
        payload = {
            "action": "created",
            "issue": {
                "pull_request": {
                    "html_url": "https://github.com/owner/repo/pull/42"
                }
            },
            "comment": {"body": "resolved"},
        }
        resp = client.post(
            "/webhook",
            json=payload,
            headers={"X-GitHub-Event": "issue_comment"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["action"] == "dismiss-resolved"
