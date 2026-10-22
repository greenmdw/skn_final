"""Local pipeline normalizes peripheral kinds before shared review scoring."""
from src.dto import PeripheralResult, PipelineResult, Slots
import src.pipeline as pipeline


def test_pipeline_passes_only_requested_kinds_to_shared_review_scorer(monkeypatch):
    result = PipelineResult(
        scenario="test", category="computer", input_text="",
        slots=Slots(category="computer", mode="build", objective_text="",
                    values={"peripherals": "mouse,speaker"}),
    )
    all_candidates = {"mouse": ["mouse-candidate"], "speaker": ["speaker-candidate"],
                      "monitor": ["unrequested-monitor"]}
    observed = {}
    monkeypatch.setattr(pipeline, "_load_peripheral_catalog", lambda *_a, **_k: all_candidates)

    def score(_conn, candidates, _values, *, catalog_source):
        observed["candidate_kinds"] = list(candidates)
        observed["catalog_source"] = catalog_source

    monkeypatch.setattr("src.services.review_ranking.score_peripheral_candidates", score)
    monkeypatch.setattr("src.engine.peripheral_select.run_peripherals",
                        lambda values, candidates, _log, **kwargs: observed.update(
                            runner_kinds=list(candidates), strict=kwargs["require_review_details"])
                        or PeripheralResult(status="skipped"))

    pipeline._run_peripherals({}, result, lambda _message: None, catalog_source="mock")

    assert observed == {
        "candidate_kinds": ["mouse", "speaker"], "catalog_source": "mock",
        "runner_kinds": ["mouse", "speaker", "monitor"], "strict": True,
    }
