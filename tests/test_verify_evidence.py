"""[3-C] 쟁점에 카탈로그 출처 근거 연결 (계획 §3.2 E5) + 예산 이중 감점 정리(추가 작업 A).

DB 통합 테스트(맨 아래, @pytest.mark.db) 하나를 빼고는 DB 가 필요 없다.
"""
from __future__ import annotations

import pytest

from src.dto import BuildResult, Candidate, RequirementSpec
from src.engine import stage3c_verify as s3c
from src.engine.stage2_requirement import load_computer_rules
from src.engine.stage4_optimize import pc_link_check
from src.repo import catalog_repo

_noop = lambda _m: None  # noqa: E731
RULES = load_computer_rules()["verification"]


def _spec(**kw) -> RequirementSpec:
    return RequirementSpec(list_id="t", category="computer", mode="build", **kw)


def _gpu_case_pair(with_provenance: bool) -> dict[str, Candidate]:
    """길이 400mm GPU + 최대 300mm 케이스 — gpu_len 이 fail 이 되는 조합."""
    gpu_prov = {}
    case_prov = {}
    if with_provenance:
        gpu_prov = {"spec_url": "https://maker.example/gpu-x", "checked_at": "2026-08-01",
                    "by_key": {"length_mm": "https://maker.example/gpu-x/dimensions"}}
        # 케이스는 gpu_max_length_mm 전용 출처 컬럼이 없다(스키마에 없음) — spec_url(제품 페이지)로 대체.
        case_prov = {"spec_url": "https://maker.example/case-y", "checked_at": "2026-08-02"}
    gpu = Candidate(product_key="gpu-x", slot="GPU", name="GPU X", price=1,
                    specs={"length_mm": 400}, provenance=gpu_prov)
    case = Candidate(product_key="case-y", slot="케이스", name="케이스 Y", price=1,
                     specs={"max_gpu_len_mm": 300}, provenance=case_prov)
    return {"GPU": gpu, "케이스": case}


def _verify_gpu_len(with_provenance: bool):
    chosen = _gpu_case_pair(with_provenance)
    spec = _spec()
    link_check = pc_link_check(chosen, spec, RULES)
    assert link_check.get("gpu_len") == "fail"
    build = BuildResult(list_id="t", link_check=link_check, budget={})
    result = s3c.verify_build(build, "computer", _noop, chosen=chosen, spec=spec, rules=RULES)
    target = result.targets[0]
    issues_by_axis = {i.axis: i for i in target.issues}
    assert "gpu_len" in issues_by_axis
    return issues_by_axis["gpu_len"], target


# ── 카탈로그 출처 근거(evidence) ──────────────────────────────────────────
def test_gpu_len_issue_gets_two_catalog_evidence_when_sources_exist():
    issue, target = _verify_gpu_len(with_provenance=True)
    assert len(issue.evidence) == 2
    kinds = {e["kind"] for e in issue.evidence}
    assert kinds == {"catalog_spec"}
    slots = {e["slot"] for e in issue.evidence}
    assert slots == {"GPU", "케이스"}
    # GPU 쪽은 전용 출처(dimension_source_url 격), 케이스 쪽은 spec_url 로 대체됐다.
    by_slot = {e["slot"]: e for e in issue.evidence}
    assert by_slot["GPU"]["source_url"] == "https://maker.example/gpu-x/dimensions"
    assert by_slot["케이스"]["source_url"] == "https://maker.example/case-y"
    assert s3c.axis_label("gpu_len") not in target.gray_axes


def test_gpu_len_issue_gets_no_evidence_when_sources_absent():
    issue, target = _verify_gpu_len(with_provenance=False)
    assert issue.evidence == []
    assert s3c.axis_label("gpu_len") in target.gray_axes


# ── specs 키 집합 불변(데이터 결손 감점 회귀 없음) ───────────────────────
def test_specs_from_row_has_no_provenance_keys():
    row = {
        "length_mm": 320, "power_w": 250, "vram_gb": "12", "lineup": "High-End",
        "recommended_psu_w": 650, "power_connector": "2× 8-pin", "aux_power": "O",
        "height_mm": 130, "slot_thickness": "2.5",
        "spec_url": "https://maker.example/gpu", "status_checked_at": "2026-08-01",
        "dimension_source_url": "https://maker.example/gpu/dim",
        "perf_score_source_url": "https://maker.example/gpu/perf",
    }
    specs = catalog_repo._specs_from_row("gpu", row)
    meta_keys = {"spec_url", "status_checked_at", "dimension_source_url", "perf_score_source_url",
                 "checked_at", "by_key", "power_family_source_url", "expansion_source_url", "height_source_url"}
    assert not (set(specs.keys()) & meta_keys)


def test_provenance_from_row_maps_confident_keys_only():
    row = {
        "spec_url": "https://maker.example/gpu", "status_checked_at": "2026-08-01",
        "dimension_source_url": "https://maker.example/gpu/dim",
        "perf_score_source_url": "https://maker.example/gpu/perf",
    }
    prov = catalog_repo._provenance_from_row("gpu", row)
    assert prov["spec_url"] == "https://maker.example/gpu"
    assert prov["checked_at"] == "2026-08-01"
    # dimension_source_url 만 매핑한다(perf_score 는 engine specs 가 아직 안 쓴다 — 계획 주석 참고).
    assert prov["by_key"] == {
        "length_mm": "https://maker.example/gpu/dim",
        "height_mm": "https://maker.example/gpu/dim",
        "slot_thickness": "https://maker.example/gpu/dim",
    }


def test_provenance_from_row_empty_without_spec_url():
    assert catalog_repo._provenance_from_row("gpu", {"dimension_source_url": "https://x"}) == {}


# ── 하위 호환 ─────────────────────────────────────────────────────────────
def test_verify_build_without_chosen_is_backward_compatible():
    build = BuildResult(list_id="t", link_check={"gpu_len": "fail"}, budget={})
    result = s3c.verify_build(build, "computer", _noop)
    target = result.targets[0]
    assert target.issues[0].evidence == []
    assert target.gray_axes == ["설명서·규격(RAG 미연결)", "호환성 정밀 검사(소켓·전력·크기는 근사값)"]


# ── verification_issue_payload ───────────────────────────────────────────
def test_verification_issue_payload_shape():
    row = {
        "rule_key": "gpu_len", "severity": "warning", "message": "그래픽카드 길이: 관측값 fail",
        "measured_values": {"evidence": [
            {"text": "케이스 Y — GPU 최대 길이 300 (제조사 사양, 2026-08-02 확인)",
             "source_url": "https://maker.example/case-y", "checked_at": "2026-08-02",
             "kind": "catalog_spec", "slot": "케이스", "name": "케이스 Y", "key": "max_gpu_len_mm", "value": 300},
        ]},
    }
    payload = s3c.verification_issue_payload(row)
    assert set(payload.keys()) == {"axis", "severity", "text", "evidence"}
    assert payload["axis"] == "gpu_len"
    assert payload["severity"] == "major"
    assert payload["text"] == row["message"]
    assert payload["evidence"] == [{
        "text": "케이스 Y — GPU 최대 길이 300 (제조사 사양, 2026-08-02 확인)",
        "source_url": "https://maker.example/case-y", "checked_at": "2026-08-02",
    }]


def test_verification_issue_payload_severity_minor_for_info():
    row = {"rule_key": "budget", "severity": "info", "message": "예산: 관측값 105.0%", "measured_values": {}}
    payload = s3c.verification_issue_payload(row)
    assert payload["severity"] == "minor"
    assert payload["evidence"] == []


# ── 추가 작업 A: 예산 이중 감점 정리 ───────────────────────────────────────
def test_budget_link_check_fail_only_penalizes_20_axis_budget():
    """link_check["budget"]="fail" 만 있고 110% 는 안 넘음 — 옛 동작 그대로 축 budget, 판정 위반, 감점 20."""
    build = BuildResult(list_id="t", link_check={"budget": "fail"},
                        budget={"max": 1_000_000, "used": 1_050_000, "used_pct": 105.0})
    result = s3c.verify_build(build, "computer", _noop)
    target = result.targets[0]
    assert target.confidence == 80
    assert len(target.issues) == 1
    issue = target.issues[0]
    assert issue.axis == "budget" and issue.judge == "위반" and issue.penalty == 20
    assert issue.tool_result == "fail"


def test_budget_110_percent_only_penalizes_15_axis_예산():
    """link_check 에 budget 키가 없이 used_pct>110 만 있는 경우 — 옛 동작 그대로 축 예산, 판정 초과, 감점 15."""
    build = BuildResult(list_id="t", link_check={},
                        budget={"max": 1_000_000, "used": 1_150_000, "used_pct": 115.0})
    result = s3c.verify_build(build, "computer", _noop)
    target = result.targets[0]
    assert target.confidence == 85
    assert len(target.issues) == 1
    issue = target.issues[0]
    assert issue.axis == "예산" and issue.judge == "초과" and issue.penalty == 15
    assert issue.tool_result == "115.0%"


def test_budget_both_causes_merge_into_one_issue_penalty_35():
    """두 원인이 겹칠 때만(추가 작업 A) 한 건(축 budget, 판정 초과, 감점 35=20+15)으로 합친다."""
    build = BuildResult(list_id="t", link_check={"budget": "fail"},
                        budget={"max": 1_000_000, "used": 1_150_000, "used_pct": 115.0})
    result = s3c.verify_build(build, "computer", _noop)
    target = result.targets[0]
    assert target.confidence == 65
    assert len(target.issues) == 1
    issue = target.issues[0]
    assert issue.axis == "budget" and issue.judge == "초과" and issue.penalty == 35
    assert issue.tool_result == "115.0%"


def test_budget_and_other_issue_do_not_duplicate_budget_axis():
    build = BuildResult(list_id="t", link_check={"socket": "fail", "budget": "fail"},
                        budget={"max": 1_000_000, "used": 1_050_000, "used_pct": 105.0})
    result = s3c.verify_build(build, "computer", _noop)
    target = result.targets[0]
    axes = [i.axis for i in target.issues]
    assert axes.count("budget") == 1
    assert axes.count("예산") == 0
    assert target.confidence == 100 - 20 - 20


# ── DB 통합 ────────────────────────────────────────────────────────────
@pytest.fixture
def conn():
    import psycopg
    from src.config import DATABASE_URL

    try:
        connection = psycopg.connect(DATABASE_URL, prepare_threshold=None, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("로컬 PostgreSQL(DATABASE_URL)에 연결할 수 없습니다 — db/setup_all.py로 준비하세요.")
    try:
        ok = connection.execute("SELECT to_regclass('catalog.cpu_spec') IS NOT NULL").fetchone()[0]
        if not (ok and connection.execute("SELECT count(*) FROM catalog.cpu_spec").fetchone()[0] > 0):
            pytest.skip("PC 카탈로그가 seed 되지 않았습니다 — db/setup_all.py로 준비하세요.")
        yield connection
    finally:
        connection.close()


@pytest.mark.db
def test_db_candidates_carry_provenance_when_catalog_has_spec_url(conn):
    """사전 점검(2026-09-23, PC 8종 spec 테이블) — spec_url·status_checked_at 채움률이 8종 모두 0%가
    아니었다(cpu/gpu/ram/mainboard/ssd/psu/case/cooler 전부 spec_url 100%). 그래서 시드가 있으면
    최소 한 후보는 provenance.spec_url 을 가져야 한다 — 0건이면 사전 점검과 어긋나므로 skip 이 아니라
    실패로 알린다."""
    from src.repo.catalog_repo import load_candidates_by_slot_from_db

    by_slot = load_candidates_by_slot_from_db(conn)
    all_candidates = [c for cands in by_slot.values() for c in cands]
    assert all_candidates, "카탈로그에 가격이 확인된 후보가 없습니다 — seed 확인 필요"
    with_spec_url = [c for c in all_candidates if c.provenance.get("spec_url")]
    assert with_spec_url, (
        "provenance.spec_url 이 있는 후보가 0건입니다 — 2026-09-23 사전 점검(8종 테이블 모두 spec_url 채움)과 "
        "어긋납니다. 시드가 그 사이 바뀌었다면 사전 점검을 다시 돌려 이 assert 를 갱신하세요."
    )
