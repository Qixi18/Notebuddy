from contextlib import nullcontext

from app.workers import runner


def test_forest_job_runs_under_continuous_material_load(monkeypatch) -> None:
    processed: list[str] = []
    forest_pending = ["forest-1"]
    monkeypatch.setattr(runner, "_material_jobs_since_forest", 0)
    monkeypatch.setattr(runner, "_material_jobs_since_asset", 0)
    monkeypatch.setattr(runner, "_jobs_since_generation", 0)
    monkeypatch.setattr(runner, "claim_next_job", lambda: "material")
    monkeypatch.setattr(runner, "claim_next_asset_job", lambda: None)
    monkeypatch.setattr(runner, "claim_next_generation_job", lambda: None)
    monkeypatch.setattr(runner, "claim_next_forest_job", lambda: forest_pending.pop(0) if forest_pending else None)
    monkeypatch.setattr(runner, "process_material", lambda _id: processed.append("material"))
    monkeypatch.setattr(runner, "process_forest_job", lambda _id: processed.append("forest"))

    for _ in range(runner.FOREST_CHECK_INTERVAL + 1):
        assert runner.run_once()

    assert processed == ["material"] * runner.FOREST_CHECK_INTERVAL + ["forest"]


def test_runner_reconciles_persisted_generation_inputs_without_browser_callback(monkeypatch) -> None:
    reconciled: list[object] = []
    monkeypatch.setattr(runner, "SessionLocal", lambda: nullcontext(object()))
    monkeypatch.setattr(runner, "coordinate_generation_inputs", lambda db: reconciled.append(db))
    monkeypatch.setattr(runner.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(runner, "_last_generation_coordination", 0.0)
    monkeypatch.setattr(runner, "_jobs_since_generation", 0)
    monkeypatch.setattr(runner, "_material_jobs_since_asset", 0)
    monkeypatch.setattr(runner, "_material_jobs_since_forest", 0)
    monkeypatch.setattr(runner, "claim_next_job", lambda: None)
    monkeypatch.setattr(runner, "claim_next_asset_job", lambda: None)
    monkeypatch.setattr(runner, "claim_next_generation_job", lambda: None)
    monkeypatch.setattr(runner, "claim_next_forest_job", lambda: None)

    assert runner.run_once() is False
    assert len(reconciled) == 1
