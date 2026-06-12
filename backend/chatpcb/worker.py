"""Layout worker: pulls heavy routing jobs from Redis, runs stage 4.

Dockerized via docker/worker.Dockerfile. Run it anywhere with network access
to the same Redis as the API: a Render background worker for normal load, or
a beefy Nebius instance for heavy autorouting jobs; nothing else changes.

No shared filesystem is assumed: the worker routes into a local temp dir and
returns artifact contents inside the Redis result payload; the API writes
them into the run's artifacts dir. Fine for mock-sized text files; TODO hand
off via S3 once real Gerber-scale outputs exist.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path

from . import config
from .models import Spec
from .stages import StageError
from .stages.layout import QUEUE_KEY, RESULT_PREFIX, run_local

RESULT_TTL_S = 3600


def handle_job(raw: bytes | str) -> tuple[str, dict]:
    """Returns (result_key, payload). Raises only if the job envelope itself
    is malformed (no job_id to reply to); stage errors become error payloads."""
    job = json.loads(raw)
    job_id = job["job_id"]
    try:
        spec = Spec.model_validate(job["spec"])
        out_dir = Path(tempfile.mkdtemp(prefix="chatpcb-layout-"))
        result = run_local(spec, out_dir)
        body = dataclasses.asdict(result)
        body.pop("remote", None)
        files = {
            Path(result.board_path).name: Path(result.board_path).read_text(),
            Path(result.drc_report_path).name:
                Path(result.drc_report_path).read_text(),
        }
        payload = {"status": "ok", "result": body, "files": files}
    except StageError as exc:
        payload = {
            "status": "error",
            "error": str(exc),
            "llm_feedback": exc.llm_feedback,
            "metrics": exc.metrics,
        }
    except Exception as exc:
        payload = {"status": "error", "error": str(exc), "llm_feedback": None}
    return f"{RESULT_PREFIX}{job_id}", payload


def main() -> None:
    import redis

    url = config.env("REDIS_URL")
    if not url:
        raise SystemExit("REDIS_URL is required to run the worker")
    client = redis.Redis.from_url(url)
    print(f"chatpcb layout worker listening on {QUEUE_KEY}")
    while True:
        _, raw = client.brpop(QUEUE_KEY)
        try:
            result_key, payload = handle_job(raw)
        except Exception as exc:
            print(f"dropping malformed job: {exc}")
            continue
        client.lpush(result_key, json.dumps(payload))
        client.expire(result_key, RESULT_TTL_S)
        print(f"job done -> {result_key}: {payload['status']}")


if __name__ == "__main__":
    main()
