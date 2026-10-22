"""[F-1] 조건 기반 리뷰 축 문장 정렬.

`priority=quiet` 처럼 이미 들어온 조건에 맞는 리뷰 축(`소음`, `발열` 등) 문장을 먼저 보여준다.
`config/computer_verification_rules.yaml` 의 `explanation.review_focus` 절이 조건 → 축 매핑을
쥐고 있고, 이 모듈은 그 표를 읽어 **정렬만** 한다.

경계 (계획서 §3.1 E2):
- `sentiment`(긍정/부정)는 정렬에 쓰지 않는다 — 축이 맞으면 긍정이든 부정이든 앞으로 온다.
- 랭킹 점수·후보 선택에 관여하지 않는다. 이 모듈이 다루는 건 이미 뽑힌 후보의 리뷰 문장
  "순서"뿐이다.
- 새 LLM 호출을 만들지 않는다. 문장은 `data/review_summaries.json`(합성 데모, 결정 0001)에
  이미 있는 것을 그대로 옮긴다.
- 응답 스키마 연결(`ItemOut.review_highlights` 등)은 범위 밖이다(R-6) — 여기서는 순수 함수와
  테스트만 만든다. `get_stored_result` 등 서비스 계층에 연결하지 않는다.
"""
from __future__ import annotations

from src.config import REVIEW_SUMMARIES_DEMO
from src.engine.stage2_requirement import load_computer_rules
from src.repo.review_repo import ReviewSummaryDemoFile

# review_focus 표를 보는 순서 — 계획서 E2: "조건 우선순위는 priority > noise_sensitive > purpose >
# assembly 순이다." 먼저 나온 조건이 만든 축이 앞자리를 차지하고, 같은 축이 뒤에 다시 나와도
# (예: quiet 의 발열과 game 의 발열) 처음 매치된 자리만 쓴다.
_CONDITION_ORDER = ("priority", "noise_sensitive", "purpose", "assembly")

_demo_file: ReviewSummaryDemoFile | None = None


def _demo() -> ReviewSummaryDemoFile:
    """`data/review_summaries.json` 리더를 한 번만 만든다.

    `src.services.review_service._stores()`와 같은 지연 초기화 패턴이다 — 다만 이 모듈은
    서비스 계층에 의존하지 않도록(엔진 → 서비스 역방향 의존을 만들지 않으려고) 독립적으로
    같은 로더(`ReviewSummaryDemoFile`)를 재사용해 직접 연다.
    """
    global _demo_file
    if _demo_file is None:
        _demo_file = ReviewSummaryDemoFile([REVIEW_SUMMARIES_DEMO])
    return _demo_file


def _candidate_keys(product_key: str) -> list[str]:
    """받은 키를 그대로, 그리고 엔진 슬러그 모양으로도 찾아본다.

    `src.services.review_service.candidate_keys`와 같은 방식(원 키 + 소문자·공백→하이픈
    슬러그)이다 — 그 함수를 그대로 import 하면 엔진(`src/engine`)이 서비스 계층
    (`src/services`)에 의존하게 되어 계층 방향이 거꾸로 된다. 매칭 "방식"만 맞추고, 서비스
    쪽 함수가 바뀌면 이 사본도 같이 맞춰야 한다는 것이 이 복제의 대가다.
    """
    keys = [product_key]
    slug = product_key.strip().lower().replace(" ", "-")
    if slug and slug not in keys:
        keys.append(slug)
    return keys


def focus_axes(values: dict) -> list[tuple[str, str]]:
    """조건(`values`, 예: `Slots.values`) → 먼저 보일 (축, matched_by) 목록.

    `config/computer_verification_rules.yaml` 의 `explanation.review_focus` 표를
    `_CONDITION_ORDER`(priority > noise_sensitive > purpose > assembly) 순으로 훑는다.
    조건 자체가 없거나(`values`에 키 없음/None) 표에 없는 값이면 건너뛴다. 같은 축이 여러
    조건에서 나오면 처음 매치된 조건만 남긴다(중복 없이, 등장 순서 유지).
    """
    focus_cfg = (load_computer_rules().get("explanation") or {}).get("review_focus") or {}
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for cond_key in _CONDITION_ORDER:
        sub_table = focus_cfg.get(cond_key)
        if not sub_table:
            continue
        cond_value = values.get(cond_key)
        if cond_value is None:
            continue
        axes = sub_table.get(cond_value)
        if not axes:
            continue
        # bool 조건(noise_sensitive)은 YAML 이 True/False 로 파싱하므로 매치는 True/False 로 하되,
        # matched_by 표시는 YAML 원문과 같은 소문자로 남긴다(예: "noise_sensitive:true").
        cond_repr = str(cond_value).lower() if isinstance(cond_value, bool) else cond_value
        matched_by = f"{cond_key}:{cond_repr}"
        for axis in axes:
            if axis not in seen:
                seen.add(axis)
                result.append((axis, matched_by))
    return result


def order_summaries(summaries: list[dict], values: dict) -> list[dict]:
    """리뷰 요약 문장 목록을 `focus_axes(values)` 순서로 재배열한다.

    맞는 축의 문장이 그 축의 우선순위 순서대로 앞에 오고, 나머지는 원래 순서 그대로 뒤에
    남는다(안정 정렬 — 같은 축끼리, 그리고 매치 안 된 문장끼리는 입력 순서를 지킨다).
    각 항목에 `matched_by`(매치 안 되면 `None`)를 덧붙인 **사본**을 낸다 — 원본 dict는
    바꾸지 않는다. `sentiment`는 정렬 키에 쓰지 않는다.
    """
    axis_rank = {axis: (rank, matched_by) for rank, (axis, matched_by) in enumerate(focus_axes(values))}

    def sort_key(indexed: tuple[int, dict]) -> tuple:
        idx, item = indexed
        hit = axis_rank.get(item.get("axis"))
        return (0, hit[0], idx) if hit else (1, idx)

    ordered: list[dict] = []
    for idx, item in sorted(enumerate(summaries), key=sort_key):
        hit = axis_rank.get(item.get("axis"))
        new_item = dict(item)
        new_item["matched_by"] = hit[1] if hit else None
        ordered.append(new_item)
    return ordered


_HIGHLIGHT_FIELDS = ("axis", "sentiment", "text", "source_label", "source_url",
                     "collected_at", "orig_refs", "matched_by")


def review_highlights(product_key: str, values: dict, limit: int = 3) -> dict:
    """프론트에 전달할 수 있는 형태의 리뷰 하이라이트 (아직 응답에 연결되지 않음, R-6).

    반환: `{"status": "ready"|"none", "is_synthetic": bool, "matched_axes": [...],
    "items": [{axis, sentiment, text, source_label, source_url, collected_at, orig_refs,
    matched_by}]}`.

    `matched_axes`는 조건(`values`)이 노린 축 전체가 아니라, 실제로 반환하는 `items` 중
    `matched_by`가 붙은 항목의 축만 담는다(등장 순서, 중복 제거). 예를 들어
    `priority=quiet`이어도 이 상품 문장에 "소음" 축이 없으면 `matched_axes`에도 "소음"이
    없다 — "조건과 맞아 앞으로 온 문장"이라는 이름 뜻을 지키기 위해서다. `limit`으로 잘려
    나간 항목의 축도 포함하지 않는다.

    상품이 `data/review_summaries.json`에 없으면 `status="none"`, `items=[]`.
    `is_synthetic`은 그 파일의 표지를 그대로 옮긴다 — 행마다 `is_synthetic: true`가 박혀
    있고(결정 0001 §2), `src/config.py`의 `REVIEW_SUMMARIES_DEMO` 주석도 이 파일 전체를
    "합성 데모"로 못박아 둔다. 그래서 행에 값이 없더라도(있어야 하는데 없는 경우) 기본값을
    False가 아니라 True로 둔다 — 이 로더가 내는 모든 행은 합성이라는 것이 파일의 전제다.
    상품이 아예 없는 `status="none"`도 같은 이유로 `is_synthetic=True`.
    """
    demo = _demo()
    row = next((r for r in (demo.get(key) for key in _candidate_keys(product_key)) if r is not None), None)
    if row is None:
        return {"status": "none", "is_synthetic": True, "matched_axes": [], "items": []}
    ordered = order_summaries(row.get("top_summaries") or [], values)
    items = [{field: s.get(field) for field in _HIGHLIGHT_FIELDS} for s in ordered[:limit]]
    # matched_axes는 focus 표 전체가 아니라 실제로 낸 items 중 matched_by가 붙은 축만 낸다
    # (순서 유지, 중복 제거) — 조건이 "소음"을 우선하더라도 이 상품 문장에 소음 축이 없으면
    # matched_axes에도 안 나와야 "조건과 맞아 앞에 온 문장"이라는 이름 뜻과 맞는다.
    matched_axes: list[str] = []
    for item in items:
        if item["matched_by"] is not None and item["axis"] not in matched_axes:
            matched_axes.append(item["axis"])
    return {
        "status": "ready",
        "is_synthetic": bool(row.get("is_synthetic", True)),
        "matched_axes": matched_axes,
        "items": items,
    }
