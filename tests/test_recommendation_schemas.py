from fastapi import FastAPI

from src.dto import RecommendationCandidate, RecommendationEvidence, RecommendationResult
from src.schemas import (
    RecommendResultOut,
    RecommendationCandidateOut,
    recommendation_result_out,
)


def test_recommendation_response_is_explicit_in_openapi() -> None:
    app = FastAPI()

    @app.get("/result", response_model=RecommendResultOut)
    def result() -> dict:
        return {}

    schema = app.openapi()["components"]["schemas"]
    response = schema["RecommendResultOut"]
    assert {"recommendation_run_id", "list_id", "revision_id", "status", "candidates"} <= set(
        response["properties"]
    )
    assert response["properties"]["candidates"]["items"]["$ref"].endswith(
        "/RecommendationCandidateOut"
    )
    evidence = schema["RecommendationEvidenceOut"]
    assert {"evidence_id", "text", "locator", "file_sha256", "review_status"} <= set(
        evidence["properties"]
    )


def test_recommendation_result_is_mapped_from_internal_dto() -> None:
    internal = RecommendationResult(
        recommendation_run_id="run-1",
        list_id="list-1",
        revision_id="revision-1",
        status="done",
        candidates=[
            RecommendationCandidate(
                product_key="seat-a",
                variant_key="black",
                product_name="안전 카시트",
                price=300000,
                eligibility_status="pass",
                verification_status="verified",
                coverage_status="complete",
                evidence=[
                    RecommendationEvidence(
                        evidence_id="evidence-1",
                        text="6개월 이상 사용",
                        locator={"page": 3},
                        file_sha256="abc",
                        review_status="reviewed",
                    )
                ],
            )
        ],
    )

    response = recommendation_result_out(internal)

    assert response.model_dump() == {
        "recommendation_run_id": "run-1",
        "list_id": "list-1",
        "revision_id": "revision-1",
        "status": "done",
        "candidates": [
            {
                "product_key": "seat-a",
                "variant_key": "black",
                "product_name": "안전 카시트",
                "price": 300000,
                "eligibility_status": "pass",
                "verification_status": "verified",
                "coverage_status": "complete",
                "reason": None,
                "evidence": [
                    {
                        "evidence_id": "evidence-1",
                        "text": "6개월 이상 사용",
                        "locator": {"page": 3},
                        "file_sha256": "abc",
                        "review_status": "reviewed",
                    }
                ],
                "error_code": None,
            }
        ],
        "error_code": None,
    }


def test_mutable_schema_defaults_are_not_shared() -> None:
    first = RecommendResultOut(
        recommendation_run_id="run-1", list_id="list-1", revision_id="revision-1", status="done"
    )
    second = RecommendResultOut(
        recommendation_run_id="run-2", list_id="list-2", revision_id="revision-2", status="done"
    )

    first.candidates.append(
        RecommendationCandidateOut(
            product_key="product",
            product_name="상품",
            eligibility_status="unknown",
            verification_status="unknown",
            coverage_status="none",
        )
    )
    assert second.candidates == []
