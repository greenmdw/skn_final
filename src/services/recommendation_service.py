"""추천 서비스 — [추천 실행] → 엔진 파이프라인 → 결과 영속화.

현재 스켈레톤은 시나리오 파일 기반(src/pipeline.run_pipeline).
실제 구현: plan_revision 의 조건·슬롯 → RequirementSpec 빌드 → [3-0]~[5] →
engine.recommendation_run / candidate / validation_result 로 저장 → S4 응답.
"""
from __future__ import annotations

from uuid import UUID

from src.dto import PipelineResult
from src.pipeline import run_pipeline as _run_scenario


def run_from_scenario(scenario_name: str) -> PipelineResult:
    """개발용: 시나리오 파일로 파이프라인 1회 (DB 미사용)."""
    return _run_scenario(scenario_name, on_log=lambda _m: None)


def run_for_revision(revision_id: UUID) -> dict:
    """실제 경로: 계획 버전의 조건으로 추천 실행 → 저장 → S4 페이로드."""
    # TODO: 실제 로직 구현 필요
    #   1. EngineRepo.start_run(...)
    #   2. slots ← PlanRepo.load_full(revision_id)  → Slots
    #   3. stage2..stage5 (카테고리 분기 + 재탐색 루프)
    #   4. EngineRepo.add_candidate / add_validation / link_*  저장
    #   5. EngineRepo.log_feedback(recommendation_shown)
    #   6. return S4 DTO
    raise NotImplementedError


def get_result(revision_id: UUID) -> dict:
    """S4 재조회 (폴링 or 새로고침). 진행 중이면 단계 상태."""
    raise NotImplementedError


def verify_and_explain_baby_candidate(*, rag_service, engine_repo, run_id, candidate: dict, slots: dict) -> dict:
    """후보 하나의 설명서 검증/설명과 채택 evidence 연결.

    검색 실패는 unknown이며 pass로 승격하지 않는다. 직렬화할 인용은 resolve_evidence
    재검사를 통과한 것만 반환한다.
    """
    from src.engine.stage3c_verify import verify_baby_manual
    from src.engine.stage5_explain import explain_manual
    from src.rag.contracts import SearchRequest
    product_key, variant_key = candidate.get("product_key"), candidate.get("variant_key")
    if not product_key or not variant_key:
        return {"eligibility_status": "unknown", "verification_status": "unknown", "coverage_status": "none", "reason": "missing_catalog_identifier", "evidence": []}
    context = {key: slots.get(key) for key in ("age_months", "weight_kg", "independent_sitting") if slots.get(key) is not None}
    request = SearchRequest(domain="baby", product_key=product_key, variant_key=variant_key, query="연령, 체중 및 독립 착석 조건", market=candidate.get("market", "KR"), language="ko", corpus="real", purpose="validation", recommendation_run_id=str(run_id), context=context)
    verified = verify_baby_manual(rag_service, request, **context)
    if verified.get("status") == "error":
        return {"eligibility_status": "unknown", "verification_status": "unknown", "coverage_status": "error", "reason": verified.get("error_code", "retrieval_error"), "evidence": []}
    validation_id = engine_repo.add_validation(run_id, rule_key="baby_manual_applicability", rule_version="v1", executor_version="rag-v1", status=verified.get("eligibility_status", "unknown"), severity="critical", measured_values=context, threshold={}, message=verified.get("reason", "manual verification"), checked_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    engine_repo.link_validation_target(validation_id, candidate_id=candidate["candidate_id"])
    explanation = explain_manual(rag_service, request)
    evidence = []
    profile_id = rag_service.repo.active_profile()["id"]
    for hit in explanation.get("hits", []):
        resolved = rag_service.repo.resolve_evidence(hit["evidence_id"], request, profile_id)
        if resolved:
            engine_repo.link_candidate_evidence(candidate["candidate_id"], hit["evidence_id"], "manual_excerpt")
            engine_repo.link_validation_evidence(validation_id, hit["evidence_id"])
            evidence.append(hit)
    return {"eligibility_status": verified.get("eligibility_status", "unknown"), "verification_status": verified.get("verification_status", "unknown"), "coverage_status": verified.get("coverage_status", "partial"), "reason": verified.get("reason"), "evidence": evidence, "explanation": explanation.get("answer"), "error_code": explanation.get("error_code")}


def get_stored_result(conn, revision_id: UUID) -> dict | None:
    """조회 시 RAG를 재실행하지 않고, 저장된 실행/후보만 공개 DTO로 변환한다."""
    from src.repo.engine_repo import EngineRepo
    repo = EngineRepo(conn); run = repo.get_latest_run(revision_id)
    if run is None: return None
    candidates=[]
    for row in repo.get_candidates(run["id"]):
        evidence=[]
        for ev in repo.get_candidate_evidence(row["id"]):
            citation=ev["citation_snapshot"]
            evidence.append({"evidence_id":str(ev["evidence_id"]), "text":citation.get("text", ""), "locator":citation.get("locator", {}), "file_sha256":citation.get("file_sha256"), "review_status":citation.get("review_status")})
        candidates.append({"product_key":row["product_key"], "variant_key":row["variant_key"], "product_name":row["product_name"], "price":row["price"], "eligibility_status":"unknown", "verification_status":"unknown", "coverage_status":"partial", "reason":row["reason"], "evidence":evidence})
    return {"recommendation_run_id":str(run["id"]), "revision_id":str(revision_id), "status":"done" if run["status"]=="completed" else run["status"], "candidates":candidates}
