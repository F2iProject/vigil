"""Webhook server for Vigil — receives GitHub events and triggers reviews.

Run with: vigil serve --port 8000
Expects WEBHOOK_SECRET env var for signature verification.
"""

import hashlib
import hmac
import logging
import os
import re
from threading import Thread

from dotenv import load_dotenv

load_dotenv(override=True)

log = logging.getLogger(__name__)


def _verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify the GitHub webhook HMAC-SHA256 signature."""
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)


def _extract_pr_url_from_event(event_type: str, payload: dict) -> str | None:
    """Extract the PR URL from a webhook event payload."""
    if event_type == "pull_request":
        pr = payload.get("pull_request", {})
        return pr.get("html_url")
    elif event_type == "issue_comment":
        issue = payload.get("issue", {})
        # issue_comment events on PRs have a pull_request key
        if issue.get("pull_request"):
            return issue["pull_request"].get("html_url")
    return None


def _should_review(event_type: str, payload: dict) -> bool:
    """Decide whether this event should trigger a Vigil review."""
    if event_type == "pull_request":
        action = payload.get("action", "")
        if action not in ("opened", "reopened", "ready_for_review"):
            return False
        pr = payload.get("pull_request", {})
        if pr.get("draft"):
            return False
        # Skip bot PRs
        sender = payload.get("sender", {}).get("login", "")
        if sender.endswith("[bot]"):
            return False
        return True

    elif event_type == "issue_comment":
        action = payload.get("action", "")
        if action != "created":
            return False
        # Must be on a PR
        issue = payload.get("issue", {})
        if not issue.get("pull_request"):
            return False
        # Must contain /vigil review
        body = payload.get("comment", {}).get("body", "")
        if "/vigil review" not in body:
            return False
        return True

    return False


def _should_dismiss(event_type: str, payload: dict) -> bool:
    """Decide whether this event should trigger dismiss-resolved."""
    if event_type != "issue_comment":
        return False
    action = payload.get("action", "")
    if action != "created":
        return False
    issue = payload.get("issue", {})
    if not issue.get("pull_request"):
        return False
    body = payload.get("comment", {}).get("body", "").strip()
    if "/vigil review" in body.lower():
        return False  # review takes priority
    # Use the same resolution detection as the comment manager
    from .comment_manager import _is_resolution_reply
    return _is_resolution_reply(body)


def _run_review(pr_url: str, model: str, lead_model: str | None, profile: str):
    """Run a Vigil review in a background thread."""
    try:
        from .cli import review as review_cmd
        from typer.testing import CliRunner
        from .cli import app as cli_app

        runner = CliRunner()
        args = [pr_url, "--model", model, "--profile", profile, "--post"]
        if lead_model:
            args.extend(["--lead-model", lead_model])
        result = runner.invoke(cli_app, ["review"] + args)
        if result.exit_code != 0:
            log.error("Review failed (exit %d): %s", result.exit_code, result.output)
        else:
            log.info("Review completed for %s", pr_url)
    except Exception as e:
        log.error("Review thread failed for %s: %s", pr_url, e)


def _run_dismiss(pr_url: str):
    """Run dismiss-resolved in a background thread."""
    try:
        from typer.testing import CliRunner
        from .cli import app as cli_app

        runner = CliRunner()
        result = runner.invoke(cli_app, ["dismiss-resolved", pr_url])
        if result.exit_code != 0:
            log.error("Dismiss failed (exit %d): %s", result.exit_code, result.output)
        else:
            log.info("Dismiss completed for %s", pr_url)
    except Exception as e:
        log.error("Dismiss thread failed for %s: %s", pr_url, e)


def create_app(
    webhook_secret: str | None = None,
    model: str = "gemini/gemini-2.5-flash",
    lead_model: str | None = None,
    profile: str = "default",
):
    """Create and return the FastAPI application.

    Args:
        webhook_secret: GitHub webhook secret for signature verification.
                       If None, signature verification is skipped (dev only!).
        model: LLM model for specialist reviewers.
        lead_model: LLM model for lead reviewer (defaults to model).
        profile: Review profile name.
    """
    try:
        from fastapi import FastAPI, Request, HTTPException
        from fastapi.responses import JSONResponse
    except ImportError:
        raise ImportError(
            "FastAPI is required for the webhook server. "
            "Install with: pip install 'vigil[webhook]'"
        )

    app = FastAPI(
        title="Vigil Webhook Server",
        description="Receives GitHub webhook events and triggers AI-powered PR reviews.",
        version="0.1.0",
    )

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "ok", "service": "vigil-webhook"}

    @app.post("/webhook")
    async def webhook(request: Request):
        """Handle GitHub webhook events."""
        body = await request.body()

        # Verify signature if secret is configured
        if webhook_secret:
            signature = request.headers.get("X-Hub-Signature-256", "")
            if not _verify_signature(body, signature, webhook_secret):
                raise HTTPException(status_code= 401, detail="Invalid signature")

        event_type = request.headers.get("X-GitHub-Event", "")
        if event_type == "ping":
            return {"status": "pong"}

        payload = await request.json()

        # Check for dismiss-resolved first
        if _should_dismiss(event_type, payload):
            pr_url = _extract_pr_url_from_event(event_type, payload)
            if not pr_url:
                return {"status": "skipped", "reason": "could not extract PR URL"}
            log.info("Dismiss-resolved triggered for %s", pr_url)
            thread = Thread(target=_run_dismiss, args=(pr_url,), daemon=True)
            thread.start()
            return {"status": "accepted", "action": "dismiss-resolved", "pr_url": pr_url}

        # Check for review trigger
        if _should_review(event_type, payload):
            pr_url = _extract_pr_url_from_event(event_type, payload)
            if not pr_url:
                return {"status": "skipped", "reason": "could not extract PR URL"}
            log.info("Review triggered for %s", pr_url)
            thread = Thread(
                target=_run_review,
                args=(pr_url, model, lead_model, profile),
                daemon=True,
            )
            thread.start()
            return {"status": "accepted", "action": "review", "pr_url": pr_url}

        return {"status": "skipped", "reason": f"unhandled event: {event_type}"}

    return app
