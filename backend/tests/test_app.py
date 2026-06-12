from fastapi.testclient import TestClient


def test_run_api_end_to_end(mock_env):
    from chatpcb.app import app

    client = TestClient(app)

    res = client.post("/api/runs", json={"idea": "ble mic with battery"})
    assert res.status_code == 200
    run_id = res.json()["run_id"]

    # TestClient executes background tasks before returning, so the run is done
    state = client.get(f"/api/runs/{run_id}").json()
    assert state["status"] == "done"
    export = next(s for s in state["stages"] if s["name"] == "export")
    assert export["artifacts"]

    # artifact download via the API
    bom_url = export["artifacts"]["bom.csv"]
    assert client.get(bom_url).status_code == 200

    dash = client.get("/api/dashboard").json()
    assert dash["total_runs"] >= 1
    assert "spec" in dash["stages"]

    assert client.get("/").status_code == 200
    assert client.get("/api/runs/nope").status_code == 404


def test_empty_idea_rejected(mock_env):
    from chatpcb.app import app

    client = TestClient(app)
    assert client.post("/api/runs", json={"idea": "  "}).status_code == 400


def test_artifact_route_rejects_non_run_ids(mock_env):
    from chatpcb.app import app

    client = TestClient(app)
    # write a file at the artifacts root that must NOT be servable
    from chatpcb import config
    config.artifacts_dir().mkdir(parents=True, exist_ok=True)
    (config.artifacts_dir() / "telemetry.jsonl").write_text("{}\n")

    for run_id in (".", "..", "%2e", "zz", "TELEMETRY"):
        res = client.get(f"/artifacts/{run_id}/telemetry.jsonl")
        assert res.status_code == 404, run_id
