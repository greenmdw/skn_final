"""[3-C]→[4] 재탐색 루프 (E1) — 검증 결과가 재구성으로 이어지게 한다.

데모 경로(`pipeline._run_computer_branch`)와 실경로(`recommendation_service.execute_recommendation`)가
같은 함수(`run_set_with_research`)를 공유한다. 둘의 차이는 주입되는 `verify`·`choose_exclusion` 뿐이다:
  - 데모: `stage3c_verify.verify_set` + 시나리오 `problem_slot` → 기존 동작과 한 글자도 다르지 않다.
  - 실경로: `stage3c_verify.verify_build` + `rule_based_exclusion`(이 모듈).

C5(현황 문서): [4] 는 탐색 중 확정 비호환(`_pc_known_failures`)을 이미 걸러내므로, 후보 하나를 빼고
다시 찾아 나아질 수 있는 것은 "근사(확인 필요) 누적"뿐이다. `set`/`budget` 실패는 [4] 가 이미 전체
풀에서 찾아본 결과라 후보를 빼도 풀리지 않는다 — 재탐색 대상에서 뺀다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from src.config import CONFIDENCE_THRESHOLD, MAX_RESEARCH_ROUNDS
from src.dto import BuildResult, Candidate, RankResult, RequirementSpec, VerificationResult
from src.engine import LogFn
from src.engine import stage4_optimize

# 재탐색 대상에서 빼는 축 — set/budget 은 [4] 가 이미 전체 풀을 본 결과라 후보를 빼도 풀리지 않는다(C5).
_NON_RESEARCHABLE_AXES = {"set", "budget", "예산"}

# 루프 종료 이유(RoundRecord.stop_reason). "통과" 말고 셋으로 나눈다 — 계획 §3.1 E1: 뺄 게
# 없어서 곧바로 끝나는 것과 라운드가 실제로 소진된 것은 다른 사유이고 로그도 달라야 한다.
_STOP_PASSED = "passed"
_STOP_MAX_ROUNDS_EXHAUSTED = "max_rounds_exhausted"          # round_no >= max_rounds 로 끝남(실제 소진)
_STOP_NO_EXCLUSION_STRATEGY = "no_exclusion_strategy"         # choose_exclusion 자체가 없음(호출부가 재탐색을 안 씀)
_STOP_NO_RESEARCHABLE_EXCLUSION = "no_researchable_exclusion"  # choose_exclusion 이 None 반환(C5, "재탐색으로 개선 불가")

ExclusionChoice = tuple[str, str, str]  # (slot, product_key, axis)
VerifyFn = Callable[[BuildResult, int], VerificationResult]
ChooseExclusionFn = Callable[[BuildResult, VerificationResult], "ExclusionChoice | None"]


@dataclass
class RoundRecord:
    """라운드 1건의 기록 — 채택 규칙(신뢰도 최고, 동점이면 앞 라운드)과 트랜스크립트가 같이 쓴다."""

    round: int
    build: BuildResult
    verification: VerificationResult
    excluded: dict | None = None   # 이번 라운드 뒤 다음 라운드를 위해 뺀 것 — {"slot", "name", "axis"}
    # 루프가 이 라운드에서 멈춘 이유(마지막 라운드에만 채워진다) — _STOP_* 상수 중 하나.
    # E1 감사 지적: choose_exclusion 함수가 없는 경우/함수가 None을 반환한 경우(개선 불가)를
    # "재탐색 {n}회 소진"으로 뭉뚱그리면 라운드가 실제로 소진되지 않았을 때도 소진됐다고 말한다.
    stop_reason: str | None = None


def _pool_index(rank: RankResult) -> dict[tuple[str, str], Candidate]:
    """rank 의 (top-N + 전체 풀) 후보를 (slot, product_key) 로 찾을 수 있게 인덱싱한다."""
    index: dict[tuple[str, str], Candidate] = {}
    for slot, info in rank.slots.items():
        for raw in (info.get("pool") or info.get("ranked") or []):
            c = Candidate.model_validate(raw)
            index[(slot, c.product_key)] = c
    return index


def resolve_chosen(rank: RankResult, build: BuildResult) -> dict[str, Candidate]:
    """build.items 의 product_key 로 rank 풀에서 다시 찾은 Candidate(specs 포함).

    BuildItem 에는 specs 가 없어(가격·이름만) missing_slots 판단·호환 재계산에는 [3-B] 가 남긴
    전체 스펙이 필요하다 — rule_based_exclusion 이 이 결과를 pc_compat_details 입력으로 쓴다.
    """
    index = _pool_index(rank)
    return {item.slot: index[(item.slot, item.product_key)]
            for item in build.items if (item.slot, item.product_key) in index}


def _candidate_name(rank: RankResult, slot: str, product_key: str) -> str:
    cand = _pool_index(rank).get((slot, product_key))
    return cand.name if cand is not None else product_key


def _confidence(record: RoundRecord) -> int:
    return record.verification.targets[0].confidence if record.verification.targets else -1


def _pick_best(records: list[RoundRecord]) -> RoundRecord:
    """신뢰도가 가장 높은 라운드, 같으면 앞 라운드([4]가 1라운드에서 점수를 최대화하므로)."""
    best = records[0]
    best_conf = _confidence(best)
    for rec in records[1:]:
        conf = _confidence(rec)
        if conf > best_conf:
            best, best_conf = rec, conf
    return best


def _round_transcript(records: list[RoundRecord]) -> list[dict]:
    """채택된 target.transcript 에 실리는 라운드별 기록. verify_set/verify_build 가 라운드 1건에
    남기던 issues 덤프(코치 리뷰 지적사항)를 라운드별로 그대로 보존하고, 그 위에
    excluded/issue_count/stop_reason 을 얹는다. stop_reason 은 루프가 멈춘 마지막 라운드에만
    값이 있고(그 외 라운드는 None) — 기존 키는 그대로 두고 이 키만 추가한다(E1 감사)."""
    rows = []
    for rec in records:
        target = rec.verification.targets[0] if rec.verification.targets else None
        issues = [i.model_dump() for i in target.issues] if target else []
        rows.append({"round": rec.round, "excluded": rec.excluded,
                     "issue_count": len(issues), "issues": issues, "stop_reason": rec.stop_reason})
    return rows


def research_trace_detail(records: list[RoundRecord]) -> str | None:
    """2라운드 이상 재탐색했을 때만 "세트 재검토" trace 문장을 만든다. None 이면 trace 단계를 넣지 않는다.

    신뢰도 숫자는 쓰지 않는다(결정 0003) — 라운드별 확인 필요 건수와 뺀 부품만 서술한다.
    채택 라운드(신뢰도 최고, `_pick_best`)까지의 제외만 "빼고 다시 구성"으로 나열한다 — 채택 라운드
    "뒤"에 시도한 라운드의 제외는 채택된 구성에 반영되지 않았으므로 부품명을 나열하면 오해를 부른다
    (리뷰 지적: 3라운드까지 돌고 2라운드를 채택하면 3라운드용으로 뺀 부품이 "빠진 것처럼" 읽혔다).
    1라운드가 채택되면(재탐색을 시도했지만 나아지지 않음) "처음 구성 유지"로 끝낸다.
    """
    if len(records) < 2:
        return None
    from src.engine.stage3c_verify import axis_label  # 지역 임포트: stage3c_verify → dto 순환 없음, 최소 결합만

    def issue_count(rec: RoundRecord) -> int:
        t = rec.verification.targets[0] if rec.verification.targets else None
        return len(t.issues) if t else 0

    best = _pick_best(records)
    adopted_idx = records.index(best)

    steps = [f"확인 필요 {issue_count(records[0])}건"]
    for rec in records[:adopted_idx]:
        ex = rec.excluded
        if ex:
            steps.append(f"{ex['slot']} '{ex['name']}'({axis_label(ex['axis'])} 확인 필요)를 빼고 다시 구성")

    if adopted_idx == 0:
        detail = f"{steps[0]} — 처음 구성 유지"
    else:
        steps.append(f"확인 필요 {issue_count(best)}건 구성 채택")
        detail = " → ".join(steps)

    extra_rounds = len(records) - 1 - adopted_idx
    if extra_rounds > 0:
        detail += f" (이후 {extra_rounds}회 더 구성해 봤지만 확인 필요 건수가 줄지 않아 채택하지 않음)"
    return detail


def run_set_with_research(
    rank: RankResult,
    spec: RequirementSpec,
    log: LogFn,
    *,
    verify: VerifyFn,
    choose_exclusion: ChooseExclusionFn | None,
    base_exclude: frozenset[tuple[str, str]] = frozenset(),
    max_rounds: int = MAX_RESEARCH_ROUNDS,
) -> tuple[BuildResult, VerificationResult, list[RoundRecord]]:
    """[4] 세트 최적화 → `verify` 검증을 최대 `max_rounds` 회 돌며, 실패한 라운드에서
    `choose_exclusion` 이 고른 (slot, product_key) 를 다음 라운드 exclude 에 더한다.

    채택: 라운드마다 결과를 보관하고 신뢰도가 가장 높은 라운드를 고른다(동점이면 앞 라운드) —
    재탐색이 결과를 나쁘게 만드는 일은 없다.
    """
    exclude: set[tuple[str, str]] = set(base_exclude)
    records: list[RoundRecord] = []

    for round_no in range(1, max_rounds + 1):
        build = stage4_optimize.run(rank, spec, log, exclude=exclude, round_no=round_no)
        log("")
        verification = verify(build, round_no - 1)
        target = verification.targets[0] if verification.targets else None
        records.append(RoundRecord(round=round_no, build=build, verification=verification))

        if target is not None and target.passed:
            log(f"      → {round_no}라운드 만에 통과.")
            records[-1].stop_reason = _STOP_PASSED
            break
        if choose_exclusion is None:
            log(f"      ! 재탐색 로직이 연결되지 않아 {round_no}라운드 결과를 그대로 채택")
            records[-1].stop_reason = _STOP_NO_EXCLUSION_STRATEGY
            break
        if round_no >= max_rounds:
            log(f"      ! 재탐색 {round_no}회 소진 → best-so-far + '검증 미완료' 표시")
            records[-1].stop_reason = _STOP_MAX_ROUNDS_EXHAUSTED
            break
        choice = choose_exclusion(build, verification)
        if choice is None:
            # 계획 §3.1 E1(C5): 라운드가 소진된 게 아니라 뺄 만한 후보가 없어서 곧바로 끝난다 —
            # "소진"이라고 하면 실제로는 그러지 않은 라운드까지 다 썼다고 오해하게 만든다.
            log(f"      ! 재탐색으로 개선 불가({round_no}라운드까지 시도) → best-so-far + '검증 미완료' 표시")
            records[-1].stop_reason = _STOP_NO_RESEARCHABLE_EXCLUSION
            break

        slot, product_key, axis = choice
        exclude.add((slot, product_key))
        name = _candidate_name(rank, slot, product_key)
        records[-1].excluded = {"slot": slot, "name": name, "axis": axis}
        log(f"      ⟳ 재탐색: 문제 슬롯 {slot} 후보 '{name}' 제외 → [4] 세트 재구성")
        log("")

    best = _pick_best(records)
    if best.verification.targets:
        best.verification.targets[0].rounds = best.round
        best.verification.targets[0].transcript = _round_transcript(records)
    return best.build, best.verification, records


def rule_based_exclusion(
    build: BuildResult,
    verification: VerificationResult,
    chosen: dict[str, Candidate],
    spec: RequirementSpec,
    rules: dict,
    *,
    impact_slots: frozenset[str] = frozenset(),
) -> ExclusionChoice | None:
    """실경로용 규칙 기반 제외 대상 선택(C5).

    감점이 큰 쟁점부터 본다. set/budget/예산 축은 재탐색 대상이 아니다(그 쟁점만 있으면 None).
    "근사"(judge == "확인 필요") 쟁점만 대상이며, pc_compat_details 의 missing_slots 로 뺄 슬롯을
    정하고 그 슬롯에서 "이번에 뽑힌 후보"(chosen[slot])를 제외 대상으로 삼는다. chosen 은 build.items
    로만 채워져 있어(resolve_chosen), spec.owned 슬롯·base_exclude 로 이미 빠진 후보는 대상이 될 수 없다.

    impact_slots(설정 ranking.impact_slots, 보통 CPU·GPU) 도 제외 대상에서 뺀다 — 이 슬롯은 점수에
    끼치는 영향이 커서, "스펙 데이터가 없다"는 이유만으로 빼면 성능이 눈에 띄게 낮은 구성이
    "확인 필요 건수가 줄었다"는 이유로 채택될 수 있다(리뷰 지적). 같은 축에 다른 missing_slot이
    있으면 그쪽을 대신 고르고, 없으면 다음 쟁점으로 넘어간다.
    """
    target = verification.targets[0] if verification.targets else None
    if target is None:
        return None
    actionable = [i for i in target.issues if i.axis not in _NON_RESEARCHABLE_AXES and i.judge == "확인 필요"]
    if not actionable:
        return None

    detail_by_axis = {row["axis"]: row for row in stage4_optimize.pc_compat_details(chosen, spec, rules)}
    for issue in sorted(actionable, key=lambda i: -i.penalty):
        row = detail_by_axis.get(issue.axis)
        for slot in (row or {}).get("missing_slots") or ():
            if slot in spec.owned or slot in impact_slots:
                continue
            cand = chosen.get(slot)
            if cand is None:
                continue
            return slot, cand.product_key, issue.axis
    return None
