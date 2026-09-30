#!/usr/bin/env python3
"""페르소나 기반 우선순위 라벨 생성 — B-1(델파이) 대체용.

배경: 팀원이 직접 비교쌍을 라벨링할 시간이 없어서, LLM 페르소나 5명의 판단을
다수결로 모아 학습용 라벨(정답)을 만든다. 비교쌍은 난수가 아니라 실제 카탈로그
후보(`stage3b_rank._score()`가 계산한 진짜 breakdown 값)를 쓴다.

절차:
  1. 슬롯별 실제 카탈로그에서 후보 두 개를 뽑아 비교쌍을 만든다(우선순위 4개 공통).
  2. 같은 (페르소나, 비교쌍)을 3회 반복 호출 — 응답 노이즈를 걸러 그 페르소나의
     최종 답을 다수결로 정한다(3회 중 2회 이상 같아야 채택, 아니면 그 페르소나는
     그 쌍에 대해 판단 불가로 제외).
  3. 같은 우선순위 안 페르소나 5명의 최종 답을 다시 다수결로 모아, 그 쌍의
     최종 라벨(정답)로 삼는다(5명 중 3명 이상 동의해야 채택, 아니면 그 쌍은
     라벨 없이 버린다).
  4. 결과를 학습 파이프라인(B안 문서의 쌍대비교 학습)이 바로 쓸 수 있는
     CSV로 낸다: (우선순위, 후보A 축값 5개, 후보B 축값 5개, 승자).

실행:
  OPENAI_API_KEY=... PYTHONPATH=. python scripts/persona_priority_diagnostic.py
  (모델은 OPENAI_MODEL 환경변수로 바꿀 수 있다. 기본 gpt-4o-mini)

출력:
  outputs/persona_diagnostic_<날짜>/raw_responses.jsonl  — 호출별 원본 응답
  outputs/persona_diagnostic_<날짜>/labels.csv           — 학습용 라벨(최종 산출물)
  outputs/persona_diagnostic_<날짜>/summary.md           — 우선순위별 페르소나 일치율(참고용)
"""
from __future__ import annotations

import csv
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.categories import load_category  # noqa: E402
from src.db import get_conn  # noqa: E402
from src.dto import Slots  # noqa: E402
from src.engine import stage2_requirement  # noqa: E402
from src.repo.catalog_repo import load_candidates_by_slot_from_db  # noqa: E402
from src.engine.stage3b_rank import _score  # noqa: E402

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
REPEATS = 3            # 같은 (페르소나, 비교쌍) 반복 횟수 — LLM 노이즈 구분용
N_PAIRS = 80             # 총 비교쌍 개수(슬롯을 돌아가며 뽑는다) — 우선순위당 최소 20~30건 라벨 확보 목표
SEED = 20260929         # 비교쌍 재현성을 위한 고정 시드
IDEAL_TIER = 6.0                    # 밸런스 축 계산에 쓰는 가정 목표 성능 등급
# 예산 하나로 고정하면 비싼 부품은 항상 "예산 초과"로 가격축이 0에 뭉개진다 —
# 실제 사용자처럼 예산대를 저가~고가로 돌려가며 뽑아야 가격 축에 변별력이 생긴다.
BUDGET_TIERS = [1_000_000, 1_500_000, 2_500_000, 4_000_000]

_AXES = ("가격", "성능", "밸런스", "리뷰", "호환여유", "소음")
# stage3b_rank._score()는 weights["소음"]이 0보다 커야만 소음 축을 계산해 breakdown에
# 넣는다(가중치 크기 자체는 여기서 안 씀 — 단지 "포함시킬지"만 이 값으로 정해진다).
# "저소음" 페르소나에게 판단 근거로 줄 소음 값을 얻으려면 0보다 큰 값을 강제로 넘겨야 한다
# (2026-09-29 실측 결함: 이걸 안 넘겨서 labels.csv에 소음 축 자체가 통째로 빠졌었다).
_FORCE_WEIGHTS = {"가격": 0.35, "성능": 0.25, "밸런스": 0.15, "리뷰": 0.20, "호환여유": 0.05, "소음": 0.01}

# ── 페르소나 20명 (우선순위 4개 × 5명) ─────────────────────────────────────
PERSONAS: dict[str, list[str]] = {
    "기본": [
        "처음 PC를 맞추는 초보자 — 뭘 중요하게 봐야 할지 잘 모른다.",
        "이것저것 꼼꼼히 따지는 실속형 사용자.",
        "지인 추천만 믿고 크게 고민하지 않는 수동적 구매자.",
        "여러 브랜드를 비교해보는 걸 좋아하는 얼리어답터.",
        "관심이 낮아서 무난한 거면 다 괜찮은 사람.",
    ],
    "성능우선": [
        "프레임이 무조건 높아야 하는 하드코어 게이머.",
        "인코딩·멀티코어 작업이 많은 영상 편집자.",
        "스트리밍과 동시 작업을 많이 하는 스트리머.",
        "벤치마크 점수 자체를 추구하는 오버클러커.",
        "몇 년 뒤까지 여유 성능을 원하는 장기 사용자.",
    ],
    "가성비": [
        "용돈이 한정된 대학생 — 절대 가격이 싼 걸 최우선으로 본다.",
        "성능 대비 가격(가격/성능 비율)을 따지는 실속형 직장인.",
        "나중에 되팔 때 감가상각까지 고려하는 사람.",
        "세일·할인 시점을 기다리는 알뜰형 구매자.",
        "가성비를 '고장 안 나고 오래 쓰는 것'으로 해석하는 보수적 구매자.",
    ],
    "저소음": [
        "방음이 안 되는 원룸에 살아서 소음에 매우 예민한 사람.",
        "너무 시끄럽지만 않으면 되는, 저소음에 크게 집착하지 않는 사람.",
        "밤에 게임을 해서 주변 소음에 신경 쓰는 사람.",
        "방송·녹음을 해서 마이크에 소음이 잡히는 게 싫은 사람.",
        "소음보다 발열을 더 신경 쓰는 사람 (저소음을 후순위로 둔다).",
    ],
}


# ── 실제 카탈로그 + 실제 요구사항으로 비교쌍 만들기 ────────────────────────────
def _real_spec(purpose: str, budget_max: int):
    """stage2_requirement.run()을 실제로 돌려 진짜 RequirementSpec을 얻는다.

    이러면 targets(슬롯별 tdp_budget_w·wattage_min 등, 호환여유 축이 실제로 쓰는 값)와
    budget.alloc·budget.total(가격 축이 실제로 쓰는 슬롯별 예산)이 전부 실측치가 된다.
    """
    slots = Slots(category="computer", mode="build", objective_text="라벨 생성용 가상 요청",
                  values={"purpose": purpose, "budget_max": budget_max}, assumed_keys=["resolution"])
    return stage2_requirement.run(slots, load_category("computer"), lambda _msg: None)


def _make_pairs(n: int, seed: int) -> list[dict]:
    """실제 카탈로그 후보 두 개씩을, 다양한 예산대의 실제 요구사항으로 스코어링한다.

    DB 연결 카탈로그(catalog.*_spec)를 쓴다 — CSV 목업 카탈로그는 perf_tier만 있고
    tdp_w/power_w/wattage_w가 없어 호환여유 축이 항상 0.5로 뭉개진다. 이 함수를 쓰려면
    DATABASE_URL이 실행 환경에 설정돼 있어야 한다(테스트 DB가 아니라 시드가 된 DB).
    """
    rng = random.Random(seed)
    with get_conn() as conn:
        by_slot = load_candidates_by_slot_from_db(conn)
    slots = [s for s in by_slot if len(by_slot[s]) >= 2]

    pairs = []
    for i in range(n):
        slot = slots[i % len(slots)]
        budget_max = rng.choice(BUDGET_TIERS)
        spec = _real_spec("game", budget_max)
        target = spec.targets.get(slot, {})
        slot_budget = int(spec.budget["total"] * spec.budget["alloc"].get(slot, 0.1))

        a, b = rng.sample(by_slot[slot], 2)
        scored_a = _score(a, IDEAL_TIER, slot_budget, slot, target, weights=_FORCE_WEIGHTS)
        scored_b = _score(b, IDEAL_TIER, slot_budget, slot, target, weights=_FORCE_WEIGHTS)
        pairs.append({
            "id": f"pair{i+1:02d}", "slot": slot, "budget_max": budget_max,
            "A": scored_a.breakdown, "B": scored_b.breakdown,
            "A_name": a.name, "B_name": b.name,
        })
    return pairs


# ── 프롬프트 ─────────────────────────────────────────────────────────────
_PROMPT = """당신은 PC 부품을 구매하려는 사용자입니다. 아래 페르소나가 되어 판단하세요.

[페르소나]
{persona}

[우선순위]
{priority}

[판단 규칙]
- 아래 두 후보의 수치만 근거로 판단하세요.
- "가격여유"는 값이 높을수록 예산 대비 저렴하다는 뜻입니다(1.0=매우 저렴, 0.0=예산 초과). 절대 가격 자체가 아니라 "저렴한 정도"이니, 숫자가 낮은 쪽이 오히려 더 비싸거나 예산을 초과한 것입니다.
- 소음은 값이 높을수록 더 조용하다는 뜻입니다(1.0=매우 조용, 0.0=시끄러움).
- 수치에 없는 정보(브랜드 이미지, 실제로 안 써본 느낌 등)를 지어내지 마세요.
- 반드시 둘 중 하나를 고르세요. 동점이라고 판단되면 "무승부"라고만 답하세요.

[후보 A]
가격여유(저렴한 정도): {a_가격}, 성능: {a_성능}, 밸런스: {a_밸런스}, 리뷰: {a_리뷰}, 호환여유: {a_호환여유}, 소음(조용함 정도): {a_소음}

[후보 B]
가격여유(저렴한 정도): {b_가격}, 성능: {b_성능}, 밸런스: {b_밸런스}, 리뷰: {b_리뷰}, 호환여유: {b_호환여유}, 소음(조용함 정도): {b_소음}

다음 형식으로만 답하세요:
승자: A / B / 무승부
이유: (한 문장, 페르소나 관점에서만)
"""

_WINNER_RE = re.compile(r"승자\s*[:：]\s*(A|B|무승부)")


def _build_prompt(persona: str, priority: str, pair: dict) -> str:
    return _PROMPT.format(
        persona=persona, priority=priority,
        a_가격=pair["A"]["가격"], a_성능=pair["A"]["성능"], a_밸런스=pair["A"]["밸런스"],
        a_리뷰=pair["A"]["리뷰"], a_호환여유=pair["A"]["호환여유"], a_소음=pair["A"].get("소음", 0.5),
        b_가격=pair["B"]["가격"], b_성능=pair["B"]["성능"], b_밸런스=pair["B"]["밸런스"],
        b_리뷰=pair["B"]["리뷰"], b_호환여유=pair["B"]["호환여유"], b_소음=pair["B"].get("소음", 0.5),
    )


def _call_llm(prompt: str) -> str:
    from openai import OpenAI  # 지역 임포트 — 이 스크립트만 openai 패키지가 필요하다

    client = OpenAI()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )
    return resp.choices[0].message.content or ""


def _parse_winner(reply: str) -> str | None:
    m = _WINNER_RE.search(reply)
    return m.group(1) if m else None


def _majority(votes: list[str | None], min_agree: int) -> str | None:
    """votes 중 min_agree 표 이상 모인 값이 있으면 그 값, 없으면 None."""
    valid = [v for v in votes if v is not None]
    if not valid:
        return None
    value, n = Counter(valid).most_common(1)[0]
    return value if n >= min_agree else None


def main() -> int:
    out_dir = Path("outputs") / f"persona_diagnostic_{datetime.now(timezone.utc):%Y%m%d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw_responses.jsonl"

    pairs = _make_pairs(N_PAIRS, SEED)

    # persona_final[priority][persona_idx][pair_id] = 그 페르소나의 3회 다수결 답
    persona_final: dict[str, dict[int, dict[str, str | None]]] = defaultdict(lambda: defaultdict(dict))

    with raw_path.open("w", encoding="utf-8") as raw_f:
        for priority, personas in PERSONAS.items():
            for p_idx, persona in enumerate(personas):
                for pair in pairs:
                    prompt = _build_prompt(persona, priority, pair)
                    votes: list[str | None] = []
                    for attempt in range(REPEATS):
                        reply = _call_llm(prompt)
                        winner = _parse_winner(reply)
                        votes.append(winner)
                        raw_f.write(json.dumps({
                            "priority": priority, "persona_idx": p_idx, "persona": persona,
                            "pair_id": pair["id"], "attempt": attempt + 1,
                            "reply": reply, "parsed_winner": winner,
                        }, ensure_ascii=False) + "\n")
                    persona_final[priority][p_idx][pair["id"]] = _majority(votes, min_agree=2)
                print(f"[{priority}] 페르소나 {p_idx+1}/{len(personas)} 완료")

    # ── 페르소나 5명 다수결 → 쌍별 최종 라벨(학습용 정답) ──
    label_rows: list[dict] = []
    agreement_by_priority: dict[str, float] = {}
    for priority, personas in PERSONAS.items():
        agree, total = 0, 0
        for pair in pairs:
            votes = [persona_final[priority][i].get(pair["id"]) for i in range(len(personas))]
            for i in range(len(votes)):
                for j in range(i + 1, len(votes)):
                    if votes[i] is not None and votes[j] is not None:
                        total += 1
                        if votes[i] == votes[j]:
                            agree += 1
            final_label = _majority(votes, min_agree=3)   # 5명 중 3명 이상 동의해야 채택
            if final_label is None or final_label == "무승부":
                continue
            label_rows.append({
                "priority": priority, "pair_id": pair["id"], "slot": pair["slot"],
                **{f"a_{axis}": pair["A"][axis] for axis in _AXES},
                **{f"b_{axis}": pair["B"][axis] for axis in _AXES},
                "winner": final_label,
            })
        agreement_by_priority[priority] = agree / total if total else 0.0

    labels_path = out_dir / "labels.csv"
    with labels_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = ["priority", "pair_id", "slot"] + [f"a_{a}" for a in _AXES] + [f"b_{a}" for a in _AXES] + ["winner"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(label_rows)

    summary_lines = ["# 페르소나 진단 결과 요약", "", "| 우선순위 | 페르소나 간 일치율 |", "|---|---|"]
    for priority, rate in sorted(agreement_by_priority.items(), key=lambda kv: kv[1]):
        summary_lines.append(f"| {priority} | {rate:.0%} |")
    summary_lines.append("")
    summary_lines.append(f"학습용 라벨 {len(label_rows)}건 → {labels_path}")

    (out_dir / "summary.md").write_text("\n".join(summary_lines), encoding="utf-8")
    print("\n".join(summary_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
