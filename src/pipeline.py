"""파이프라인 오케스트레이션 (Truefit).

시나리오 파일(data/scenarios/*.json)을 입력으로 8단계를 순서대로 실행한다.
컴퓨터 (verify_branch=set): [4] 세트 최적화 → [3-C] 세트 검증  ─(신뢰도<80)⟳

각 단계 로그는 on_log 콜백으로 흘리고 최종 결과는 PipelineResult(pydantic)로 반환한다.
"""
from __future__ import annotations

import json
import os
from typing import Callable

from src.categories import load_category, verify_branch
from src.config import DATA_DIR, SCENARIO_DIR
from src.dto import BuildResult, Candidate, PipelineResult, VerificationResult
from src.engine import stage1_intent, stage2_requirement, stage3_0_candidates
from src.engine import stage3a_hardfilter, stage3c_verify
from src.engine import stage5_explain
from src.engine.research_loop import run_set_with_research
from src.rag.evidence_search import load_mini_corpus

LogFn = Callable[[str], None]


def load_scenario(name: str) -> dict:
    path = SCENARIO_DIR / f"{name}.json"
    if not path.exists():
        avail = ", ".join(p.stem for p in SCENARIO_DIR.glob("*.json"))
        raise FileNotFoundError(f"시나리오 없음: {name}  (사용 가능: {avail})")
    return json.loads(path.read_text(encoding="utf-8"))


def run_pipeline(scenario_name: str, on_log: LogFn = print, *, catalog_source: str | None = None) -> PipelineResult:
    scenario = load_scenario(scenario_name)
    cat = scenario["category"]
    cat_def = load_category(cat)
    load_mini_corpus(scenario.get("corpus", []))

    result = PipelineResult(scenario=scenario_name, category=cat, input_text=scenario["input_text"])

    def log(msg: str) -> None:
        result.logs.append(msg)
        on_log(msg)

    log(f"입력: {scenario['input_text']!r}")
    log(f"카테고리: {cat_def['label']} · 모드: {scenario['mode']} · 검증분기: {cat_def['verify_branch']}")
    log("")

    # ── ② 공통 단계 ──────────────────────────────────────────────────
    result.slots = stage1_intent.run(scenario, cat_def, log); log("")
    result.requirement = stage2_requirement.run(result.slots, cat_def, log); log("")
    by_slot = stage3_0_candidates.run(result.requirement, log, catalog_source=catalog_source); log("")
    result.hard_filter = stage3a_hardfilter.run(result.requirement, by_slot, log); log("")
    from src.services.review_ranking import rank_with_review_aspects
    result.rank, result.review_requirement_profiles = rank_with_review_aspects(
        result.hard_filter, result.requirement, result.slots, log,
        catalog_source=catalog_source,
    ); log("")

    # ── ③ 카테고리별 검증 분기 ──────────────────────────────────────
    branch = verify_branch(cat)
    if branch == "set":
        log("── 분기: 컴퓨터 → [4] 세트 최적화 먼저, 그다음 [3-C] 세트 검증 ──")
        _run_computer_branch(scenario, result, log)
        _run_peripherals(scenario, result, log, catalog_source=catalog_source)
    elif branch == "per_item":
        _run_per_item_branch(scenario, result, log)
    else:
        raise NotImplementedError(f"pipeline: 지원하지 않는 검증 분기입니다: {branch}")
    log("")

    # ── ④ 설명 ─────────────────────────────────────────────────────
    result.explanation = stage5_explain.run(result.build, result.verification, log, rank=result.rank)
    log("")
    log("파이프라인 종료.")
    return result


def _run_computer_branch(scenario: dict, result: PipelineResult, log: LogFn) -> None:
    """데모 경로 — verify_set(시나리오 정답값) + problem_slot 을 run_set_with_research 에 감싸 넣는다.
    실경로(recommendation_service)와 같은 루프 함수를 쓰되, 데모 동작·로그 문구는 그대로 유지한다."""
    spec, rank = result.requirement, result.rank

    def verify(build: BuildResult, round_index: int) -> VerificationResult:
        return stage3c_verify.verify_set(build, scenario, round_index=round_index, log=log)

    def choose_exclusion(build: BuildResult, verification: VerificationResult):
        target = verification.targets[0] if verification.targets else None
        round_index = (target.rounds - 1) if target is not None else 0
        ps = stage3c_verify.problem_slot(scenario, round_index=round_index)
        ranked = rank.slots.get(ps, {}).get("ranked", []) if ps else []
        if not (ps and ranked):
            return None
        worst = Candidate.model_validate(ranked[0])
        issues = target.issues if target is not None else []
        axis = issues[0].axis if issues else ps
        return ps, worst.product_key, axis

    result.build, result.verification, _ = run_set_with_research(
        rank, spec, log, verify=verify, choose_exclusion=choose_exclusion,
    )


def _run_per_item_branch(scenario: dict, result: PipelineResult, log: LogFn) -> None:
    """`verify_branch: per_item` 카테고리 자리(계획 §3.3 E11).

    지금 이 분기를 쓰는 카테고리는 없다 — `config/categories/computer.yaml`은
    `verify_branch: set`이다. 주변기기(모니터·키보드·마우스·스피커)는 `per_item` 판정
    방식(하드 필터→랭킹→품목별 검증, [4] 세트 최적화 없음)을 실제로 쓰지만, 컴퓨터
    카테고리 자체의 부속 결과라 이 분기를 통해 오지 않는다 — `_run_computer_branch` 뒤
    `_run_peripherals`가 별도로 부른다(`src/engine/peripheral_select.run_peripherals`).

    이 자리에 실제로 도달하면(=`per_item` 카테고리가 새로 생기면) `result.build`(완성
    세트)가 없어 뒤이은 [5] `stage5_explain.run`이 세트 기여도 설명을 만들 수 없다 —
    그 카테고리의 [5]는 품목별 설명으로 다시 설계해야 하므로, 여기서 억지로 BuildResult
    모양을 흉내 내지 않고 명확한 예외로 멈춘다(계획 §4: "억지 구현보다 명확한 설명").
    """
    raise NotImplementedError(
        "pipeline: per_item 분기는 아직 실제 카테고리가 없습니다 — 주변기기는 "
        "verify_branch가 아니라 컴퓨터(set) 분기 뒤 _run_peripherals가 별도로 처리합니다"
    )


def _load_peripheral_catalog(log: LogFn, *, catalog_source: str | None = None) -> dict[str, list[Candidate]]:
    """`CATALOG_SOURCE=mock`이면 CSV, 그 외에는 DB만 사용한다. DB 오류/빈 결과는 실패시킨다."""
    from src.engine.peripheral_catalog import load_peripheral_candidates_from_csv

    source = catalog_source if catalog_source is not None else os.environ.get("CATALOG_SOURCE", "db")
    if source == "mock":
        by_kind = load_peripheral_candidates_from_csv(
            DATA_DIR / "peripherals", filename_template="{kind}_processed.csv",
        )
    elif source == "db":
        from src.db import get_conn
        from src.repo.catalog_repo import load_peripheral_candidates

        with get_conn() as conn:
            by_kind = load_peripheral_candidates(conn)
        if not any(by_kind.values()):
            raise RuntimeError("DB peripheral catalog is empty")
        summary = " / ".join(f"{k} {len(c)}" for k, c in by_kind.items())
        log(f"      [P][DB] 주변기기 카탈로그 로드 → {summary}")
        return by_kind
    else:
        raise ValueError(f"unsupported CATALOG_SOURCE: {source}")
    if not any(by_kind.values()):
        log("      [P][MOCK] data/peripherals CSV를 찾지 못함 → 주변기기 후보 0건")
        return by_kind
    summary = " / ".join(f"{k} {len(c)}" for k, c in by_kind.items())
    log(f"      [P][MOCK] data/peripherals CSV 로드 → {summary}")
    return by_kind


def _run_peripherals(scenario: dict, result: PipelineResult, log: LogFn, *, catalog_source: str | None = None) -> None:
    """컴퓨터 set 분기 뒤에 붙는 주변기기 단계(계획 §3.3 E11 + E12).

    시나리오 조건([1]의 결과, `result.slots.values`)에 `peripherals`가 없으면 아무 것도
    하지 않는다 — 기존 데모 시나리오(computer_pass/computer_research 등)는 이 조건이 없어
    한 글자도 안 바뀐다(계획 §4 "기존 결과 불변 원칙").

    E12 — `pc_context`를 여기서 조립해 `run_peripherals`에 넘긴다: 해상도는 [1]이 채운
    `values["resolution"]`, GPU 스펙은 `research_loop.resolve_chosen(result.rank,
    result.build)["GPU"]`(재탐색 루프가 채택한 라운드의 실제 GPU 후보 — E1)의 `specs`다.
    컴퓨터 세트가 GPU를 못 골랐거나(비정상 상황) `result.build`가 없으면 `gpu_specs=None`
    으로 넘어가고, `peripheral_cross`는 이를 "그래픽카드 출력 단자 정보 없음"으로 다룬다
    (PC 세트 신뢰도에는 영향을 주지 않는다 — `monitor_gpu_port`/`monitor_usb_c`가 Pending
    될 뿐이다).
    """
    values = (result.slots.values if result.slots else {}) or {}
    if not values.get("peripherals"):
        return
    from src.engine.peripheral_select import run_peripherals
    from src.engine.research_loop import resolve_chosen
    from src.engine.peripheral_rules import requested_kinds

    log("── [P] 주변기기 단계 (계획 §3.3 E11) ──")
    candidates = _load_peripheral_catalog(log, catalog_source=catalog_source)
    from src.services.review_ranking import score_peripheral_candidates
    source = catalog_source if catalog_source is not None else os.environ.get("CATALOG_SOURCE", "db")
    requested_candidates = {kind: candidates.get(kind, []) for kind in requested_kinds(values)}
    if source == "mock":
        score_peripheral_candidates(None, requested_candidates, values, catalog_source="mock")
    else:
        from src.db import get_conn
        with get_conn() as review_conn:
            score_peripheral_candidates(review_conn, requested_candidates, values, catalog_source="db")

    gpu_specs: dict | None = None
    if result.rank is not None and result.build is not None:
        gpu = resolve_chosen(result.rank, result.build).get("GPU")
        if gpu is not None:
            gpu_specs = gpu.specs
    pc_context = {"resolution": values.get("resolution"), "gpu_specs": gpu_specs}

    result.peripherals = run_peripherals(
        values, candidates, log, pc_context=pc_context, require_review_details=True,
    )

    # E13 — payload를 데모 로그에 요약해 가공 결과를 확인한다. 주변기기 R도 payload에 포함된다.
    # peripherals 조건이
    # 없는 시나리오는 이 함수가 위에서 이미 return하므로 이 로그도 그 경우엔 절대 찍히지
    # 않는다(계획 §4 "기존 결과 불변 원칙").
    from src.engine.peripheral_payload import peripheral_payload

    payload = peripheral_payload(result.peripherals)
    if payload["status"] == "ready":
        names = ", ".join(f"{i['kind_label']} {i['product']['name']}" for i in payload["items"])
        log(f"      [P][E13] payload: {names} · 참고가 합계 {payload['totals']['reference_price']:,}원"
            f" (PC 예산과 별도)")
    else:
        log(f"      [P][E13] payload status={payload['status']}")

