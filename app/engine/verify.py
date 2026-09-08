"""
3단계 ③ — 스펙 주장 ↔ 리뷰 대조. **이 기획의 심장**(기획안 §3).

[오늘 들어간 것과 안 들어간 것]
이 파일에는 **판정 규칙**만 있다. 근거(표본·닿는 수·어긋난 수)를 받아
`Verdict` 를 내는 부분이고, 전부 룰이다.

들어가지 **않은** 것은 근거를 모으는 쪽, 즉 *"이 리뷰 문장이 이 주장에 닿는가,
어긋나는가"* 를 판정하는 의미 대조다. 그건 AI 몫이고(기획안 §9), 일정상 9/10
자리다. 지금은 `ReviewSource` 가 라벨을 들고 있어서 파이프라인 전체가 키 없이
끝까지 돈다 — 실데이터 소스가 붙을 때 라벨 자리에 의미 대조가 들어간다.

[임계값은 지어내지 않았다]
아래 두 상수는 `docs/목업/pc-부품.html` 3단계 표의 여섯 행을 전부 재현하도록
맞춘 값이다. 목업이 판정을 이미 그려 놨으니 규칙이 거기 맞아야 한다.

    주장                    표본        어긋남   비율    판정
    GPU "부하 시 68°C"      214+31      47      .220    ✕ 반증
    GPU "보조전원 8핀 1개"   214          0      .000    ● 확인
    CPU "기본 쿨러로 정격"   178         63      .354    ✕ 반증
    PSU "풀로드 24dB"        96         11      .115    ◐ 부분 확인
    SSD "연속 쓰기 5,000"    142(닿는 것 3건)    —       · 근거 없음
    RAM "XMP 6000 안정"      88+19        0      .000    ● 확인

값을 바꾸면 여섯 행 중 몇이 뒤집힌다. `tests/test_recommend_engine.py` 가
그 여섯 행을 그대로 검사한다 — 임계값이 조용히 흘러가지 않게 하려는 것이다.
"""

from __future__ import annotations

import os

from .schemas import Claim, ClaimVerdict, Evidence, Verdict

# 주장에 닿는 표본이 이 미만이면 판정하지 않는다 — "모르는 것을 모른다고 말한다".
# 목업 SSD 행(닿는 리뷰 3건)이 근거 없음으로 떨어지는 자리다.
MIN_RELEVANT = int(os.getenv("VERIFY_MIN_RELEVANT", "10"))

# 닿는 표본 중 어긋난 비율이 이 이상이면 반증. 미만이면서 0보다 크면 부분 확인.
# 목업 PSU 행(.115)이 부분 확인, GPU 온도(.220)가 반증으로 갈리는 자리다.
REFUTE_RATIO = float(os.getenv("VERIFY_REFUTE_RATIO", "0.15"))


def verdict_from(evidence: Evidence) -> Verdict:
    """
    근거 하나에서 판정 하나. **여기에 AI 가 없다.**

    순서가 중요하다 — 표본 부족을 먼저 본다. 어긋난 사례가 2건 있어도 닿는
    표본이 3건이면 "반증"이 아니라 "근거 없음"이다. 3건으로 반증을 선언하면
    9/7 15시의 엘리베이터 논쟁에서 팀이 고른 쪽(확률과 근거를 그대로 노출)이
    아니라 반대쪽으로 가는 것이다.
    """
    if evidence.relevant < MIN_RELEVANT:
        return Verdict.NO_EVIDENCE
    if evidence.hits <= 0:
        return Verdict.CONFIRMED
    if evidence.hits / evidence.relevant >= REFUTE_RATIO:
        return Verdict.REFUTED
    return Verdict.PARTLY


def verify_claims(claims: list[Claim], source) -> list[ClaimVerdict]:
    """주장 목록을 리뷰 소스와 대조한다. 목업 3단계 표 한 장이 나온다."""
    out: list[ClaimVerdict] = []
    for claim in claims:
        evidence = source.evidence_for(claim)
        out.append(
            ClaimVerdict(claim=claim, evidence=evidence, verdict=verdict_from(evidence))
        )
    return out
