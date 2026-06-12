"""Composio actions: share a finished run via GitHub + Gmail.

Triggered by the Share button in the UI (POST /api/runs/{id}/share):
(a) create a GitHub repo named after the project and push the design files,
(b) optionally email the order summary via Gmail.

Isolation guarantee: no-ops gracefully when COMPOSIO_API_KEY is unset or the
composio package is not installed (install with `pip install -e ".[sponsors]"`).
Env vars:
  COMPOSIO_API_KEY       required to do anything
  COMPOSIO_USER_ID       Composio entity/user id (default "default")
  COMPOSIO_GITHUB_OWNER  GitHub login owning the new repo (needed for pushes)
  COMPOSIO_GMAIL_TO      recipient; unset = skip the email
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from .. import config
from ..models import RunState
from ..stages import slugify

log = logging.getLogger(__name__)

# TODO: verify action slugs against the Composio toolkit catalog.
ACTION_CREATE_REPO = "GITHUB_CREATE_A_REPOSITORY_FOR_THE_AUTHENTICATED_USER"
ACTION_PUT_FILE = "GITHUB_CREATE_OR_UPDATE_FILE_CONTENTS"
ACTION_SEND_EMAIL = "GMAIL_SEND_EMAIL"


def share_run(run: RunState, artifacts_dir: Path) -> dict:
    """Returns a status dict; never raises (the UI renders whatever we say)."""
    if not config.env("COMPOSIO_API_KEY"):
        return {"status": "skipped", "reason": "COMPOSIO_API_KEY not set"}
    try:
        from composio import Composio
    except ImportError:
        return {
            "status": "skipped",
            "reason": "composio not installed (pip install -e \".[sponsors]\")",
        }

    client = Composio(api_key=config.env("COMPOSIO_API_KEY"))
    user_id = config.env("COMPOSIO_USER_ID", "default")

    result: dict = {"status": "shared"}
    result["github"] = _push_to_github(client, user_id, run, artifacts_dir)
    if config.env("COMPOSIO_GMAIL_TO"):
        result["gmail"] = _send_summary(client, user_id, run)
    else:
        result["gmail"] = {"status": "skipped", "reason": "COMPOSIO_GMAIL_TO not set"}
    if "error" in (result["github"].get("status"), result["gmail"].get("status")):
        result["status"] = "partial"
    return result


def _repo_name(run: RunState) -> str:
    base = slugify(run.spec.project.name) if run.spec else run.run_id
    return f"chatpcb-{base}"


def _push_to_github(client, user_id: str, run: RunState,
                    artifacts_dir: Path) -> dict:
    repo = _repo_name(run)
    try:
        client.tools.execute(
            ACTION_CREATE_REPO,
            user_id=user_id,
            arguments={
                "name": repo,
                "description": (run.spec.project.summary if run.spec
                                else "ChatPCB design files"),
                "private": False,
            },
        )
        owner = config.env("COMPOSIO_GITHUB_OWNER")
        pushed = 0
        if owner:
            for path in sorted(artifacts_dir.glob("*")):
                if not path.is_file():
                    continue
                client.tools.execute(
                    ACTION_PUT_FILE,
                    user_id=user_id,
                    arguments={
                        "owner": owner,
                        "repo": repo,
                        "path": path.name,
                        "message": f"Add {path.name} (ChatPCB run {run.run_id})",
                        "content": base64.b64encode(path.read_bytes()).decode(),
                    },
                )
                pushed += 1
        else:
            log.warning("COMPOSIO_GITHUB_OWNER not set; repo created, no files pushed")
        return {
            "status": "ok",
            "repo": repo,
            "repo_url": f"https://github.com/{owner}/{repo}" if owner else None,
            "files_pushed": pushed,
        }
    except Exception as exc:
        log.warning("composio github share failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _send_summary(client, user_id: str, run: RunState) -> dict:
    try:
        lines = [f"ChatPCB run {run.run_id}: {run.status}"]
        if run.spec:
            lines.append(f"Project: {run.spec.project.name}")
            lines.append(f"Summary: {run.spec.project.summary}")
        if run.bom:
            lines.append(
                f"BOM: {len(run.bom.bom)} lines, "
                f"est. ${run.bom.total_cost_usd:.2f}/unit"
            )
        export = next((s for s in run.stages if s.name == "export"), None)
        if export and export.artifacts:
            lines.append("Artifacts: " + ", ".join(sorted(export.artifacts)))
        client.tools.execute(
            ACTION_SEND_EMAIL,
            user_id=user_id,
            arguments={
                "recipient_email": config.env("COMPOSIO_GMAIL_TO"),
                "subject": f"ChatPCB order summary: {_repo_name(run)}",
                "body": "\n".join(lines),
            },
        )
        return {"status": "ok", "to": config.env("COMPOSIO_GMAIL_TO")}
    except Exception as exc:
        log.warning("composio gmail share failed: %s", exc)
        return {"status": "error", "error": str(exc)}
