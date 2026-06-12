"""Per-attempt pipeline telemetry.

Every stage attempt is logged with duration, status, and stage metrics
(DRC violation count, routing completion percent, retries). Backend is
ClickHouse when CLICKHOUSE_URL is set (a DSN for clickhouse-connect, e.g.
clickhouse://user:pass@host:8443/chatpcb?secure=true); otherwise rows append
to <artifacts>/telemetry.jsonl so the dashboard still works in local demos.
ClickHouse failures degrade to the JSONL sink instead of breaking a run.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

TABLE = "chatpcb_stage_attempts"
DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    ts DateTime64(3),
    run_id String,
    stage String,
    attempt UInt8,
    status String,
    duration_ms Float64,
    error String,
    drc_violations Int32,
    routing_completion_pct Float64,
    metrics String
) ENGINE = MergeTree ORDER BY (run_id, ts)
"""

_clients: dict[str, object] = {}  # CLICKHOUSE_URL -> initialized client


def _jsonl_path() -> Path:
    path = config.artifacts_dir() / "telemetry.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _clickhouse_client():
    url = config.env("CLICKHOUSE_URL")
    if not url:
        return None
    if url not in _clients:
        try:
            import clickhouse_connect

            client = clickhouse_connect.get_client(dsn=url)
            client.command(DDL)
            _clients[url] = client
        except Exception as exc:
            # Negative-cache the failure: an unreachable ClickHouse must not
            # stall every stage attempt for a connect timeout. Retried on
            # process restart.
            log.warning("clickhouse unavailable, using jsonl sink: %s", exc)
            _clients[url] = None
    return _clients[url]


def log_stage_attempt(
    run_id: str,
    stage: str,
    attempt: int,
    status: str,
    duration_ms: float,
    *,
    error: str | None = None,
    metrics: dict[str, float] | None = None,
) -> None:
    metrics = metrics or {}
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "stage": stage,
        "attempt": attempt,
        "status": status,
        "duration_ms": round(duration_ms, 2),
        "error": error or "",
        "drc_violations": int(metrics.get("drc_violations", -1)),
        "routing_completion_pct": float(metrics.get("routing_completion_pct", -1.0)),
        "metrics": json.dumps(metrics, sort_keys=True),
    }
    client = _clickhouse_client()
    if client is not None:
        try:
            client.insert(
                TABLE,
                [[
                    datetime.now(timezone.utc), row["run_id"], row["stage"],
                    row["attempt"], row["status"], row["duration_ms"],
                    row["error"], row["drc_violations"],
                    row["routing_completion_pct"], row["metrics"],
                ]],
                column_names=[
                    "ts", "run_id", "stage", "attempt", "status",
                    "duration_ms", "error", "drc_violations",
                    "routing_completion_pct", "metrics",
                ],
            )
            return
        except Exception as exc:
            log.warning("clickhouse insert failed, falling back to jsonl: %s", exc)
    with _jsonl_path().open("a") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _load_rows(limit: int = 10000) -> tuple[list[dict], str]:
    client = _clickhouse_client()
    if client is not None:
        try:
            result = client.query(
                f"SELECT run_id, stage, attempt, status, duration_ms, "
                f"drc_violations, routing_completion_pct FROM {TABLE} "
                f"ORDER BY ts DESC LIMIT {limit}"
            )
            rows = [dict(zip(result.column_names, r)) for r in result.result_rows]
            return rows, "clickhouse"
        except Exception as exc:
            log.warning("clickhouse query failed, reading jsonl: %s", exc)
    path = config.artifacts_dir() / "telemetry.jsonl"
    if not path.exists():
        return [], "jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return rows[-limit:], "jsonl"


def dashboard_summary() -> dict:
    """Aggregates for the frontend dashboard panel."""
    rows, backend = _load_rows()
    stages: dict[str, dict] = {}
    for row in rows:
        agg = stages.setdefault(
            row["stage"],
            {"attempts": 0, "ok": 0, "failed": 0, "total_duration_ms": 0.0},
        )
        agg["attempts"] += 1
        if row["status"] == "ok":
            agg["ok"] += 1
        elif row["status"] == "failed":
            agg["failed"] += 1
        agg["total_duration_ms"] += float(row["duration_ms"])
    for agg in stages.values():
        agg["avg_duration_ms"] = round(agg["total_duration_ms"] / agg["attempts"], 1)
        del agg["total_duration_ms"]

    drc = [r["drc_violations"] for r in rows if int(r.get("drc_violations", -1)) >= 0]
    routing = [
        r["routing_completion_pct"]
        for r in rows
        if float(r.get("routing_completion_pct", -1)) >= 0
    ]
    return {
        "backend": backend,
        "total_runs": len({r["run_id"] for r in rows}),
        "total_attempts": len(rows),
        "total_retries": sum(1 for r in rows if int(r["attempt"]) > 1),
        "stages": stages,
        "avg_drc_violations": round(sum(drc) / len(drc), 2) if drc else None,
        "avg_routing_completion_pct": (
            round(sum(routing) / len(routing), 1) if routing else None
        ),
    }
