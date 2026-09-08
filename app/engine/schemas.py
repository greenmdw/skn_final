"""
추천 엔진 L0 — 6단계가 주고받는 계약.

`app/schemas.py` 가 협상 쪽 계약이듯, 이 파일이 추천 쪽 계약이다. 두 파일은
서로를 임포트하지 않는다 — 협상(B2B)과 추천(B2C)은 다른 물건이고, 한쪽이
빠져도 다른 쪽이 안 무너지는 게 지금 국면에서 값이 크다.

[3단계 스키마는 목업에서 왔다]
`docs/목업/pc-부품.html` 과 `여행-예약.html` 이 **같은 표**를 쓴다 —
부품/장소 · 주장 · 대조 표본 · 판정. 두 도메인이 같은 스키마로 그려진다는 것이
기획안 §3의 주장(엔진은 도메인과 독립)에 대한 유일한 실물 증거라, 그 표를
그대로 타입으로 옮겼다. 화면 계약이 아니라 **데이터 모양**만 가져온 것이다.

세 가지가 목업을 읽고 나서야 보였다.

1. **표본은 소스별로 쪼개진다** — 목업이 항상 `리뷰 214 / Q&A 31` 로 나눠 적는다.
   정수 하나로 잡으면 나중에 못 쪼갠다. 그래서 `samples` 가 dict 다
2. **`NO_EVIDENCE` 는 임계값이 만든다** — SSD 가 *"실측 언급 리뷰 3건뿐"* 으로
   근거 없음이 됐다. AI 판정이 아니라 룰이고, 임계값은 `verify.py` 에 상수로 있다
3. **판정이 4단계로 되돌아간다** — CPU 기본 쿨러 주장이 반증되며 쿨러가 세트에
   편성됐다. `Verdict` 는 화면용 산출물이 아니라 최적화의 입력이다. 그래서
   `Claim.remedy` 가 있다
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    """
    스펙 주장 하나에 대한 판정. 목업의 네 값 그대로다.

    글리프를 값에 안 넣는다 — 목업이 ● ◐ ✕ · 를 색과 함께 쓰지만 그건 화면
    담당자의 몫이고, 여기서 정하면 백엔드가 표현을 강제하게 된다.
    """

    CONFIRMED = "confirmed"        # ● 확인 — 반증 사례가 없고 표본이 충분하다
    PARTLY = "partly"              # ◐ 부분 확인 — 반증 사례가 있으나 소수다
    REFUTED = "refuted"            # ✕ 반증 — 반증 사례가 무시할 수 없는 비율이다
    NO_EVIDENCE = "no_evidence"    # · 근거 없음 — 표본이 임계 미만. 모른다고 말한다


class Remedy(BaseModel):
    """
    주장이 반증됐을 때 세트를 어떻게 고칠지. **없을 수 있다.**

    목업의 두 장면이 이 타입의 양쪽 끝이다.
    - CPU *"기본 쿨러로 정격 유지"* 반증 → 쿨러를 편성한다 (`add_category`)
    - 그래픽카드 온도 주장 반증 → *"같은 가격대에 VRAM 12GB 대안이 없어"* 유지하고
      경고만 (`add_category` 가 None)

    **어느 쪽이든 후보에서 빼지는 않는다.** 그 규칙은 `optimize.py` 에 있고
    검사로 고정돼 있다.
    """

    add_category: str | None = None   # 이 카테고리 품목을 세트에 추가한다
    warning: str = ""                 # 세트에 붙는 경고 문구


class Claim(BaseModel):
    """
    검증 대상이 되는 주장 하나.

    PC 에서는 제조사가 스펙에 적은 것이고, 여행이라면 상세페이지가 적어 놓은
    약속이다("터미널에서 도보 5분"). 도메인이 달라도 구조가 같아서 이 타입이
    도메인 팩 바깥에 있다.
    """

    claim_id: str
    subject: str                      # 무엇에 대한 주장인가 ("그래픽카드 B사·12GB")
    text: str                         # 주장 원문 ("게이밍 부하 시 68°C")
    source: str = "제조사 스펙"        # 이 주장이 어디서 왔는가
    remedy: Remedy | None = None      # 반증됐을 때 세트를 어떻게 고칠지


class Evidence(BaseModel):
    """
    한 주장에 대해 리뷰에서 모은 근거.

    **읽은 표본과 주장에 닿는 표본은 다르다.** 목업의 SSD 행이 그 자리다 —
    대조 표본 칸은 "리뷰 142"인데 판정은 *"실측을 언급한 리뷰가 3건뿐 — 표본
    부족"* 으로 근거 없음이다. 142 를 세고 임계값을 걸면 이 판정이 안 나온다.
    그래서 숫자가 셋이다.

        samples   읽은 표본. 소스별로 쪼갠다 ({"리뷰": 214, "QA": 31})
        relevant  그중 이 주장에 닿는 것 (온도를 언급한 리뷰)
        hits      그중 주장과 **어긋나는** 것 (80°C 이상을 말한 리뷰)

    확인 쪽을 세지 않는 이유는 침묵이 확인의 근거이기 때문이다 — 목업도
    *"반증 사례 없음"* 을 확인 판정의 근거로 쓴다.
    """

    samples: dict[str, int] = Field(default_factory=dict)   # {"리뷰": 214, "QA": 31}
    relevant: int = 0
    hits: int = 0
    note: str = ""
    # 대조에 쓴 근거 구절. **정책에 따라 비어 있을 수 있다.**
    #
    # 판정이 어느 문장에서 나왔는지 보이지 않으면 그 숫자를 지어낸 것과 구분되지
    # 않는다 — 그래서 원문 인용을 근거로 썼다. 그런데 9/8 17시에 **리뷰 원문을
    # 내보낼 수 없다**는 방침이 정해졌다.
    #
    # **검증과 노출을 갈랐다.** 모델이 낸 인용이 원문에 실제로 있는지는 서버 안에서
    # 계속 확인한다(`match.accept`) — 지어낸 인용은 그 자리에서 버려진다. 밖으로
    # 내보내는 것만 정책이 가린다. 가려도 판정의 신뢰도는 그대로이고, 화면이
    # "근거를 보여줄 수 없다"는 사실을 알 수 있게 `excerpt_policy` 를 함께 낸다.
    quotes: list[str] = Field(default_factory=list)
    # "verbatim" 원문 인용이 실려 있다 / "withheld" 정책상 가렸다
    excerpt_policy: str = "verbatim"
    # 인용 대신 가리킬 출처. 화면은 여기로 링크한다.
    sources: list[str] = Field(default_factory=list)
    # 조작 확률이 임계 이상이라 대조 표본에서 뺀 건수(목업 공개 화면의 약속).
    excluded_high_risk: int = 0
    # 조작 확률을 **재지 못한** 건수. 0 이 아니면 "20% 이상을 걸렀다"고 말할 수
    # 없다 — 거르지 못한 것이 섞여 있다. 화면은 이 값을 보고 고지를 바꿔야 한다.
    unscored_risk: int = 0

    @property
    def total(self) -> int:
        """읽은 표본 전체. 목업의 "대조 표본" 칸이 이 값이다."""
        return sum(self.samples.values())


class Review(BaseModel):
    """
    리뷰 한 건. **3단계가 실제로 읽는 대상이다.**

    이전에는 소스가 집계 숫자(`Evidence`)를 바로 돌려줬다. 그러면 "이 문장이 이
    주장에 닿는가"를 판정하는 일 자체가 코드에 없다 — 3단계의 심장이 데이터에
    미리 들어 있는 셈이라, 파이프라인이 도는 것을 보고 됐다고 착각하게 된다
    ([`decisions/0008`](../../docs/decisions/0008-리뷰-소스-기본값을-합성으로-둔다.md)
    이 가장 큰 함정으로 적어 둔 것이 이것이다). 그래서 소스는 **문장**을 주고,
    닿는지 어긋나는지는 `match.py` 가 정한다.

    **리뷰는 주장이 아니라 품목에 달린다.** 한 품목에 주장이 여럿이면 같은 리뷰
    묶음을 여러 주장이 나눠 쓴다 — 목업에서 그래픽카드의 두 주장이 똑같이 "리뷰
    214"를 대조 표본으로 적은 이유다.
    """

    review_id: str
    part_code: str
    kind: str = "리뷰"                 # "리뷰" / "QA"
    # 리뷰 본문. **대조하는 동안에만 쓰는 값이고 저장 대상이 아니다.**
    # 9/8 17시: *"리뷰 원문을 그대로 가져와 저장하는 것은 법적 문제가 있어 절대
    # 안 되며, 반드시 가공한 뒤 노출해야 한다."* 실소스 어댑터는 이 값을 요청
    # 처리 동안만 들고 있어야 하고, DB·파일에 그대로 쓰면 안 된다.
    text: str
    source_url: str = ""              # 원문이 있는 곳. 인용 대신 여기를 가리킨다
    # 조작 확률 0.0~1.0. **`None` 은 "아직 안 쟀다"이지 "깨끗하다"가 아니다.**
    # 기본값을 0.0 으로 두면 실 리뷰가 전부 임계값 아래로 떨어져 20% 필터가
    # 한 건도 안 거르는데 에러는 안 난다 — 공개 화면의 약속이 조용히 무력해진다.
    risk: float | None = None

    # 합성 데이터만 갖는 정답 라벨. 실데이터에는 없다(그래서 기본값이 비어 있다).
    # 이 라벨의 값은 두 가지다 — LabelMatcher 가 키 없이 도는 것, 그리고
    # LLMMatcher 를 **채점할 수 있는 것**.
    bears_on: list[str] = Field(default_factory=list)
    contradicts: list[str] = Field(default_factory=list)


class ReviewJudgment(BaseModel):
    """대조 한 건의 결과. 모델이 채우는 것도 이 모양이다."""

    review_id: str
    bears_on: bool = Field(description="이 리뷰가 그 주장을 언급하거나 다루는가")
    contradicts: bool = Field(description="언급한다면, 주장과 어긋나는가")
    quote: str = Field(default="", description="근거가 된 리뷰 안의 짧은 구절")


class ClaimVerdict(BaseModel):
    """주장 + 근거 + 판정. 목업 3단계 표의 한 행이다."""

    claim: Claim
    evidence: Evidence
    verdict: Verdict


class Requirement(BaseModel):
    """
    2단계 산출 — 구체화된 요구사항 한 줄.

    `as_of` 가 있는 이유는 9/7 17시 지적 때문이다. *"게임사 공개 사양과 유튜버
    벤치마크는 시차가 있어 이미 구형 정보인 경우가 많다."* 기획안 §4의 대응이
    *"시차 자체를 화면에 쓴다"* 였으므로, 외부 사실에는 기준 시점이 반드시
    따라다녀야 한다. 없으면 화면이 그 약점을 흡수할 수 없다.
    """

    key: str
    value: str
    origin: str                       # 어디서 왔는가 ("게임사 공개 권장 사양")
    hard: bool = True                 # 하드 제약인가, 참고인가
    as_of: str = ""                   # 외부 사실의 기준 시점
    # 이 조건을 실제로 판정했는가. False 면 조건 충족도에서 "미충족"이 아니라
    # **판정하지 않음**으로 센다. 목업의 "144Hz 기준 평균 프레임은 실측 표본이
    # 부족해 판정하지 않았다"가 이 자리다 — 못 잰 것을 충족으로 세면 안 된다.
    judged: bool = True
    unjudged_reason: str = ""


class Screening(BaseModel):
    """
    3단계 ① — 제약 하나가 후보를 몇 개 걸러냈는가.

    목업의 깔때기(*"전체 후보 148 → 소켓 불일치 −62 → … → 통과 41"*)가 이
    자리인데 엔진이 이 데이터를 아예 안 만들고 있었다.

    **없으면 외부 사실이 한 일이 안 보인다.** VRAM 12GB 를 하드 제약으로 걸어도
    예산이 넉넉하면 결과가 같을 수 있는데(요구는 바닥이지 목표가 아니다), 그때
    화면에는 *"권장 사양을 주입했습니다"* 만 뜨고 무엇이 달라졌는지는 안 보인다.
    `excluded` 가 0 이면 **0 이라고 말하는 것**이 정직하다.
    """

    key: str
    label: str
    origin: str = ""
    excluded: int = 0          # 이 제약이 후보에서 걸러낸 품목 수
    remaining: int = 0         # 걸러낸 뒤 남은 후보 수


class SetLine(BaseModel):
    """4단계 산출 — 세트에 들어간 품목 한 줄."""

    category: str
    code: str
    name: str
    price: int
    added_by_claim: str | None = None   # 반증 판정 때문에 편성됐다면 그 claim_id
    warning: str = ""                   # 반증됐으나 대안이 없어 유지된 경우


class Reason(BaseModel):
    """
    5단계 산출 — 근거 문장 한 줄.

    `claim_id` 가 핵심이다. 목업이 *"근거 문장의 각 주장은 단계 3의 판정과
    일대일로 연결된다"* 고 적었고, 그게 *"설명이 스스로 지어낸 문장이 아니라는
    것"* 의 유일한 증거다. 판정에서 온 문장이 아니면 이 값이 None 이다.
    """

    text: str
    claim_id: str | None = None


class Indicators(BaseModel):
    """
    §7 세 지표. **하나로 합치지 않는다.**

    기획안 §7이 이유를 적어 뒀다 — 합치는 순간 가중치를 정당화해야 하는데 근거가
    없고, 멘토가 물어본 것이 정확히 그 지점이었다. *"종합 신뢰도 87점"* 보다
    *"조건 5/6 · 스펙 주장 4개 중 3개 확인(리뷰 128건 대조) · 리뷰 91%가 조작 확률
    20% 미만"* 이 강하다. 그래서 여기에 합계 필드를 두지 않는다 —
    **필드가 없으면 화면도 못 합친다.**
    """

    conditions_met: int
    conditions_total: int
    conditions_unmet: list[str] = Field(default_factory=list)

    verdicts: dict[str, int] = Field(default_factory=dict)   # verdict 값별 건수
    samples_compared: int = 0

    # 조작 확률 분포. 이진 판정을 하지 않는다(기획안 §7) — Fakespot 이 무너진
    # 자리를 우회하는 방식이라 구간 히스토그램으로만 내보낸다.
    review_risk_buckets: dict[str, int] = Field(default_factory=dict)


class NeedsInput(BaseModel):
    """
    1단계 되묻기 한 건. **선택지만 준다. 화면 형태는 정하지 않는다.**

    기획안 §3이 *"카드형 선택지 팝업"* 이라 적었지만 그건 화면 담당자의 몫이고,
    백엔드가 정할 것은 *무엇을 모르는가* 와 *고를 수 있는 것이 무엇인가* 뿐이다.
    """

    key: str
    question: str
    options: list[str] = Field(default_factory=list)


class Recommendation(BaseModel):
    """`POST /api/recommend` 의 응답 전체. 화면 담당자가 이 스키마에 붙는다."""

    domain: str
    needs_input: list[NeedsInput] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    claims: list[ClaimVerdict] = Field(default_factory=list)
    set: list[SetLine] = Field(default_factory=list)
    budget: int = 0
    spent: int = 0
    reasons: list[Reason] = Field(default_factory=list)
    indicators: Indicators | None = None
    screening: list[Screening] = Field(default_factory=list)
    # 예산 안에 들어왔는가. False 면 `spent` 가 `budget` 을 넘는다 — 화면이
    # 그냥 합계만 보여주면 사용자가 예산을 지킨 줄 안다.
    budget_met: bool = True
    # 엔진이 화면·사용자에게 반드시 알려야 하는 것. 비어 있는 것이 정상이다.
    notices: list[str] = Field(default_factory=list)
    tools_used: list[dict] = Field(default_factory=list)
    mode: str = "rule"
