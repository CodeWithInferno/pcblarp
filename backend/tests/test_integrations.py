import json

import chatpcb.llm as llm
from chatpcb import config
from chatpcb.integrations import composio_actions, guild_tracking, senso_kb
from chatpcb.integrations.airbyte_lcsc import seed_sqlite
from chatpcb.models import Spec
from chatpcb.pipeline import run_pipeline
from chatpcb.stages import spec as spec_stage
from chatpcb.stages.parts import load_parts_table


# --- Senso knowledge layer -------------------------------------------------

def test_senso_local_fallback_ranks_relevant_sections(monkeypatch):
    monkeypatch.delenv("SENSO_API_KEY", raising=False)
    context = senso_kb.design_rules_context("minimum trace width and spacing")
    assert "Trace width" in context
    assert len(context) <= 1800


def test_design_rules_injected_into_spec_prompt(mock_env, monkeypatch):
    captured = {}
    good = (config.DATA_DIR / "mock_spec.json").read_text()

    def fake_complete(system, messages, **kwargs):
        captured["system"] = system
        return good

    monkeypatch.setattr(llm, "complete", fake_complete)
    spec_stage.generate_spec(
        "tiny BLE antenna board", log_attempt=lambda *a, **k: None
    )
    assert "<design_rules>" in captured["system"]
    assert "</design_rules>" in captured["system"]


def test_unmatched_parts_get_kb_notes(mock_spec_data, monkeypatch):
    monkeypatch.delenv("SENSO_API_KEY", raising=False)
    from chatpcb.stages.parts import match_parts

    spec = Spec.model_validate(mock_spec_data)
    table = [r for r in load_parts_table()
             if r["catalog_block"] != "sensor_mic_i2s_mems"]
    result = match_parts(spec, table=table)
    assert result.unmatched_blocks == ["mic"]
    assert result.kb_notes  # local KB fallback still supplies context


def test_kb_notes_reach_revision_prompt(mock_env, monkeypatch):
    # unmatched mic -> kb_notes populated; layout failure -> revision pass;
    # the revision feedback must carry the knowledge-layer notes.
    from chatpcb.stages import parts as parts_stage
    from chatpcb.stages import spec as spec_mod

    monkeypatch.setenv("CHATPCB_FAIL_STAGE", "layout")
    no_mic = [r for r in parts_stage.load_parts_table()
              if r["catalog_block"] != "sensor_mic_i2s_mems"]
    monkeypatch.setattr(parts_stage, "load_parts_table",
                        lambda path=None: no_mic)

    captured = []

    def fake_revise(spec, stage, error, log_attempt=None):
        captured.append(error)
        return spec

    monkeypatch.setattr(spec_mod, "revise_spec_with_error", fake_revise)
    run_pipeline("ble mic")
    assert captured
    assert any("knowledge-layer notes" in error for error in captured)


# --- Composio share ---------------------------------------------------------

def test_share_skips_gracefully_without_key(mock_env):
    state = run_pipeline("ble mic")
    result = composio_actions.share_run(
        state, config.artifacts_dir() / state.run_id
    )
    assert result == {"status": "skipped", "reason": "COMPOSIO_API_KEY not set"}


def test_share_endpoint(mock_env):
    from fastapi.testclient import TestClient

    from chatpcb.app import app

    client = TestClient(app)
    run_id = client.post("/api/runs", json={"idea": "ble mic"}).json()["run_id"]
    res = client.post(f"/api/runs/{run_id}/share")
    assert res.status_code == 200
    assert res.json()["status"] == "skipped"
    assert client.post("/api/runs/nope/share").status_code == 404


# --- Guild.ai tracking -------------------------------------------------------

def test_run_is_tracked_to_experiments_jsonl(mock_env):
    state = run_pipeline("ble mic")
    path = config.artifacts_dir() / "experiments.jsonl"
    assert path.exists()  # guildai not installed -> jsonl fallback
    record = json.loads(path.read_text().splitlines()[-1])
    assert record["run_id"] == state.run_id
    assert record["scalars"]["routing_completion_pct"] == 100.0
    assert record["scalars"]["drc_violations"] == 0.0
    assert record["flags"]["prompt_version"].startswith("dev-")
    assert record["flags"]["placement_optimizer"] == "mock-grid"


def test_failed_runs_are_tracked_too(mock_env, monkeypatch):
    monkeypatch.setattr(llm, "complete", lambda *a, **k: "garbage")
    state = run_pipeline("ble mic")
    assert state.status == "failed"
    path = config.artifacts_dir() / "experiments.jsonl"
    record = json.loads(path.read_text().splitlines()[-1])
    assert record["scalars"]["run_ok"] == 0.0


# --- Airbyte parts table ------------------------------------------------------

def test_parts_db_roundtrip(mock_env, tmp_path, monkeypatch):
    db_path = tmp_path / "parts.db"
    count = seed_sqlite(db_path)
    assert count == len(load_parts_table())  # CSV fallback as reference

    monkeypatch.setenv("PARTS_DB_URL", f"sqlite:///{db_path}")
    rows = load_parts_table()
    assert len(rows) == count
    assert any(r["mpn"] == "ESP32-C3-MINI-1-N4" for r in rows)
    # numeric columns come back typed; the matcher tolerates both
    esp = next(r for r in rows if r["mpn"] == "ESP32-C3-MINI-1-N4")
    assert float(esp["unit_price_usd"]) == 1.80


def test_parts_db_failure_falls_back_to_csv(mock_env, monkeypatch):
    monkeypatch.setenv("PARTS_DB_URL", "sqlite:///does/not/exist.db")
    rows = load_parts_table()
    assert any(r["mpn"] == "INMP441" for r in rows)


def test_pipeline_uses_db_parts_table(mock_env, tmp_path, monkeypatch):
    db_path = tmp_path / "parts.db"
    seed_sqlite(db_path)
    monkeypatch.setenv("PARTS_DB_URL", f"sqlite:///{db_path}")
    state = run_pipeline("ble mic")
    assert state.status == "done"
    assert state.bom is not None and state.bom.total_cost_usd > 0
