import json

import chatpcb.llm as llm
from chatpcb import config
from chatpcb.pipeline import run_pipeline


def test_full_pipeline_mocked(mock_env):
    state = run_pipeline("mic ble battery recorder")

    assert state.status == "done"
    assert [r.status for r in state.stages] == ["ok"] * 5
    assert state.spec is not None and state.bom is not None

    out = config.artifacts_dir() / state.run_id
    for artifact in ("spec.json", "bom.csv", "netlist.json",
                     "gerbers_pcbway.zip", "pick_and_place.csv",
                     "drc_report.json"):
        assert (out / artifact).exists(), artifact

    export = next(r for r in state.stages if r.name == "export")
    assert export.artifacts["bom.csv"].startswith("/artifacts/")

    # telemetry recorded an attempt for every stage
    rows = [
        json.loads(line)
        for line in (config.artifacts_dir() / "telemetry.jsonl")
        .read_text().splitlines()
    ]
    assert {r["stage"] for r in rows} == {"spec", "parts", "schematic",
                                          "layout", "export"}
    layout_rows = [r for r in rows if r["stage"] == "layout"]
    assert layout_rows[0]["routing_completion_pct"] == 0.0  # placed, unrouted


def test_layout_failure_keeps_partial_results(mock_env, monkeypatch):
    monkeypatch.setenv("CHATPCB_FAIL_STAGE", "layout")
    state = run_pipeline("mic ble battery recorder")

    assert state.status == "partial"
    layout = next(r for r in state.stages if r.name == "layout")
    assert layout.status == "failed"
    assert layout.attempts == 3          # exhausted per-stage attempts
    assert state.revision_count == 2     # one revision between each attempt

    out = config.artifacts_dir() / state.run_id
    assert (out / "spec.json").exists()
    assert (out / "bom.csv").exists()
    assert not (out / "gerbers_pcbway.zip").exists()

    export = next(r for r in state.stages if r.name == "export")
    assert export.status == "ok"
    assert "spec.json" in export.artifacts
    assert state.bom is not None  # parts succeeded, bom survives layout failure

    # revision LLM calls are visible in telemetry
    rows = [
        json.loads(line)
        for line in (config.artifacts_dir() / "telemetry.jsonl")
        .read_text().splitlines()
    ]
    assert any(r["stage"] == "spec_revision" for r in rows)


def test_spec_failure_skips_everything(mock_env, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "garbage")
    state = run_pipeline("mic ble battery recorder")
    assert state.status == "failed"
    assert [r.status for r in state.stages] == \
        ["failed", "skipped", "skipped", "skipped", "skipped"]


def test_needs_clarification_skips_build(mock_env, monkeypatch):
    data = json.loads((config.DATA_DIR / "mock_spec.json").read_text())
    data["status"] = "needs_clarification"
    data["clarification_questions"] = ["Battery powered or mains powered?"]
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps(data))

    state = run_pipeline("ambiguous gadget")

    assert state.status == "partial"
    statuses = {r.name: r.status for r in state.stages}
    assert statuses["parts"] == "skipped"
    assert statuses["schematic"] == "skipped"
    assert statuses["layout"] == "skipped"
    assert statuses["export"] == "ok"  # spec.json still exported
    assert any("Battery powered" in e for e in state.events)


def test_outdoor_spec_gets_jua_climate_notes(mock_env, monkeypatch):
    data = json.loads((config.DATA_DIR / "mock_spec.json").read_text())
    data["constraints"]["environment"] = "outdoor"
    monkeypatch.setattr(llm, "complete", lambda *a, **k: json.dumps(data))
    state = run_pipeline("outdoor solar sensor")
    assert any("Outdoor deployment" in a for a in state.spec.assumptions)
