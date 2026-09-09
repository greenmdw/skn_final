"""
PC 부품 팩 — 2026-09-07에 확정된 도메인(기획안 §4).

[제조사는 가상이고 게임은 실명이다 — 갈라 놓는 이유가 있다]
**제조사 이름은 실재하지 않는 것으로 쓴다.** 여기에 합성 리뷰가 붙기 때문이다 —
실제 제품에 대한 가짜 리뷰 판정을 만들지 않으려는 것이고, `docs/목업/README.md`
가 같은 정책을 적어 뒀다.

**게임 이름은 2026-09-09 에 실명으로 바꿨다.** 게임은 리뷰가 붙는 대상이 아니라
발행처가 공개한 사실(권장 사양)을 가리키는 이름이라 같은 위험이 없다. 대신
**수치는 발행처 문서에서 확인한 것만 넣는다**(`GAMES` 주석).

숫자와 시나리오는 `docs/목업/pc-부품.html` 의 것을 그대로 쓴다(예산 120만,
QHD 상옵). 목업과 API 응답이 다른 숫자를 말하면 발표에서 둘 중 하나는
거짓말이 된다.

[이 팩이 채우는 칸]
기획안 §3이 도메인 의존이라 표시한 세 칸 + `pack.py` 가 찾아낸 네 번째 칸.

    품목 사전       catalog() · claims_for() · followups() · weights()
                   · required_categories() · extract()
    외부 사실       external_facts()   ← 게임사 공개 권장 사양
    하드 제약       constraints()(조합) · meets()(낱개)  ← 기획안 §3 표가 안 센 칸
    리뷰 소스       review_source()
"""

from __future__ import annotations

import re

from ...reviews.synthetic import SyntheticReviews
from ..pipeline import extract_budget
from ..schemas import Claim, NeedsInput, Remedy, Requirement

NAME = "pc"

# ── 품목 사전 ────────────────────────────────────────────────────────────────
# 기획안 §4: 부품 8종 고정. 넓히는 것은 제출 이후다.
CATEGORIES = ("CPU", "GPU", "메인보드", "RAM", "SSD", "파워", "쿨러", "케이스")

CATALOG: list[dict] = [
    # CPU — socket / tdp
    {"code": "CPU-A6", "category": "CPU", "name": "A사 6코어 12스레드", "price": 289000,
     "socket": "S1", "tdp": 105},
    {"code": "CPU-A8", "category": "CPU", "name": "A사 8코어 16스레드", "price": 389000,
     "socket": "S1", "tdp": 125},
    # GPU — vram / tdp / 길이
    {"code": "GPU-B12", "category": "GPU", "name": "B사 12GB", "price": 437000,
     "vram": 12, "tdp": 220, "length_mm": 304},
    {"code": "GPU-B8", "category": "GPU", "name": "B사 8GB", "price": 419000,
     "vram": 8, "tdp": 180, "length_mm": 272},
    {"code": "GPU-C16", "category": "GPU", "name": "C사 16GB", "price": 899000,
     "vram": 16, "tdp": 285, "length_mm": 336},
    # 메인보드 — socket / ram_type
    {"code": "MB-S1D5", "category": "메인보드", "name": "A사 S1 보드", "price": 148000,
     "socket": "S1", "ram_type": "DDR5"},
    {"code": "MB-S1D4", "category": "메인보드", "name": "A사 S1 보드 (구형 메모리)", "price": 121000,
     "socket": "S1", "ram_type": "DDR4"},
    # RAM
    {"code": "RAM-D5-16", "category": "RAM", "name": "16GB DDR5-6000", "price": 92000,
     "ram_type": "DDR5"},
    {"code": "RAM-D4-16", "category": "RAM", "name": "16GB DDR4-3200", "price": 62000,
     "ram_type": "DDR4"},
    # SSD
    {"code": "SSD-1T", "category": "SSD", "name": "1TB NVMe Gen4", "price": 98000},
    # 파워 — watt
    {"code": "PSU-650", "category": "파워", "name": "650W 80+ Gold", "price": 89000, "watt": 650},
    {"code": "PSU-850", "category": "파워", "name": "850W 80+ Gold", "price": 139000, "watt": 850},
    # 쿨러 — 지원 소켓
    {"code": "COOL-T1", "category": "쿨러", "name": "타워형 공랭", "price": 34000,
     "sockets": ["S1"]},
    # 케이스 — 장착 가능 GPU 길이
    {"code": "CASE-M", "category": "케이스", "name": "미들타워", "price": 62000,
     "max_gpu_mm": 330},
]

# 4단계 예산 배분 W값. 카테고리별 데이터라 품목 사전 칸에 속한다.
# 6단계가 갱신하는 대상이 이 표다(기획안 §8 — "학습"이 아니라 W값 갱신).
WEIGHTS: dict[str, float] = {
    "GPU": 0.40, "CPU": 0.20, "메인보드": 0.10, "RAM": 0.08,
    "SSD": 0.08, "파워": 0.08, "케이스": 0.03, "쿨러": 0.03,
}

# ── 주장 ─────────────────────────────────────────────────────────────────────
# 목업 3단계 표의 여섯 행. 주장의 주인이 팩이므로 remedy 도 여기 있다.
CLAIMS: dict[str, list[Claim]] = {
    "GPU-B12": [
        Claim(claim_id="gpu-temp", subject="그래픽카드 B사·12GB",
              text="게이밍 부하 시 68°C", source="제조사 스펙",
              # 반증되지만 대안이 없다 — 목업이 "같은 가격대에서 VRAM 12GB를
              # 만족하는 대안이 없어 유지하고 경고만 단다"고 적은 자리다.
              remedy=Remedy(warning="부하 시 온도가 스펙보다 높다는 리뷰가 있습니다. 케이스 흡배기를 확인하세요.")),
        Claim(claim_id="gpu-power", subject="그래픽카드 B사·12GB",
              text="보조전원 8핀 1개", source="제조사 스펙"),
    ],
    "CPU-A6": [
        Claim(claim_id="cpu-cooler", subject="CPU A사·6C12T",
              text="기본 쿨러로 정격 유지", source="제조사 스펙",
              # 반증되면 쿨러가 세트에 들어간다 — 검증이 구성에 관여하는 증거다.
              remedy=Remedy(add_category="쿨러",
                            warning="기본 쿨러로는 정격이 유지되지 않는다는 리뷰가 다수입니다.")),
    ],
    "PSU-650": [
        Claim(claim_id="psu-noise", subject="파워 650W 80+ Gold",
              text="풀로드 소음 24dB", source="제조사 스펙"),
    ],
    "SSD-1T": [
        Claim(claim_id="ssd-write", subject="SSD 1TB NVMe Gen4",
              text="연속 쓰기 5,000MB/s", source="제조사 스펙"),
    ],
    "RAM-D5-16": [
        Claim(claim_id="ram-xmp", subject="메모리 16GB DDR5-6000",
              text="XMP 6000 안정", source="제조사 스펙"),
    ],
}

# ── 리뷰 묶음 (합성) ─────────────────────────────────────────────────────────
# **리뷰는 주장이 아니라 품목에 달린다.** 그래픽카드의 두 주장이 목업에서 똑같이
# "리뷰 214"를 대조 표본으로 적은 이유이고, 3단계가 실제로 하는 일도 품목의 리뷰
# 묶음을 한 번 읽고 주장마다 다시 훑는 것이다.
#
# `retained` 는 **조작 확률 필터를 통과한 뒤** 대조에 쓰는 건수다. 목업의 "대조
# 표본" 칸이 이 값이고, 수집 건수는 그보다 많다(공개 화면이 조작 확률 20% 이상을
# 대조에서 뺀다고 약속했다).
REVIEW_POOLS: dict[str, dict] = {
    "GPU-B12": {
        "retained": {"리뷰": 214, "QA": 31},
        "claims": {
            "gpu-temp": {"in": ["리뷰"], "relevant": 214, "hits": 47,
                         "note": "214건 중 47건이 80°C 이상을 언급"},
            "gpu-power": {"in": ["리뷰"], "relevant": 214, "hits": 0,
                          "note": "반증 사례 없음"},
        },
    },
    "CPU-A6": {
        "retained": {"리뷰": 178},
        "claims": {
            "cpu-cooler": {"in": ["리뷰"], "relevant": 178, "hits": 63,
                           "note": "178건 중 63건이 서멀 스로틀링 언급"},
        },
    },
    "PSU-650": {
        "retained": {"리뷰": 96},
        "claims": {
            "psu-noise": {"in": ["리뷰"], "relevant": 96, "hits": 11,
                          "note": "96건 중 11건이 코일 소음 언급"},
        },
    },
    "SSD-1T": {
        # 142건을 읽지만 실측을 언급한 것은 3건뿐이다. 대조가 표본을 **골라내는**
        # 일이라는 것을 보여주는 유일한 자리이고, 의미 대조의 난이도도 여기서 갈린다.
        "retained": {"리뷰": 142},
        "claims": {
            "ssd-write": {"in": ["리뷰"], "relevant": 3, "hits": 1,
                          "note": "실측을 언급한 리뷰가 3건뿐 — 표본 부족"},
        },
    },
    "RAM-D5-16": {
        "retained": {"리뷰": 88, "QA": 19},
        "claims": {
            "ram-xmp": {"in": ["리뷰", "QA"], "relevant": 107, "hits": 0,
                        "note": "Q&A 19건 포함, 반증 없음"},
        },
    },
}

# 주장마다 어긋나는 문장과 닿되 어긋나지 않는 문장. 합성 리뷰의 본문이 여기서 온다.
CLAIM_PHRASES: dict[str, dict[str, list[str]]] = {
    "gpu-temp": {
        "against": [
            "풀로드 돌리면 82도까지 올라갑니다.",
            "벤치 30분 돌리니 85도 찍고 팬이 풀속으로 갑니다.",
            "여름에 케이스 안에서 88도까지 봤어요.",
            "68도는 무슨, 게임 켜면 80도 아래로 안 내려옵니다.",
            "하드한 게임에서 84도 근처에 계속 머뭅니다.",
        ],
        "for": [
            "온도는 게임 중에도 65도 근처에서 유지됩니다.",
            "스펙대로 68도를 안 넘네요.",
            "통풍 괜찮은 케이스면 67도 정도로 잡힙니다.",
            "장시간 돌려도 온도가 스펙 범위 안이라 만족합니다.",
        ],
    },
    "gpu-power": {
        "against": [],
        "for": [
            "보조전원 8핀 하나만 꽂으면 됩니다.",
            "8핀 1개라 기존 파워 그대로 썼어요.",
            "케이블 정리가 편합니다. 8핀 단자 하나뿐이라서.",
        ],
    },
    "cpu-cooler": {
        "against": [
            "기본 쿨러로는 90도 찍고 클럭이 떨어집니다.",
            "번들 쿨러에서 스로틀링이 걸려 사제로 바꿨습니다.",
            "동봉 쿨러로 렌더 돌리면 금방 온도 제한에 걸려요.",
            "기본 쿨러 물려 두면 부스트가 유지되질 않습니다.",
        ],
        "for": [
            "기본 쿨러로도 정격은 유지됩니다.",
            "동봉 쿨러로 일반 작업은 문제없었어요.",
        ],
    },
    "psu-noise": {
        "against": [
            "부하 걸리면 코일 소음이 들립니다.",
            "고사양 게임에서 코일 훰이 제법 납니다.",
        ],
        "for": [
            "조용합니다. 팬 소리가 거의 안 들려요.",
            "소음은 스펙 수준으로 잡혀 있습니다.",
            "새벽에 써도 거슬리지 않습니다.",
        ],
    },
    "ssd-write": {
        "against": [
            "연속 쓰기를 재보니 3,200MB/s 정도밖에 안 나옵니다.",
        ],
        "for": [
            "실측해 보니 연속 쓰기 5,100MB/s 나왔습니다.",
            "벤치 프로그램으로 쓰기 속도 5,050MB/s 확인했어요.",
        ],
    },
    "ram-xmp": {
        "against": [],
        "for": [
            "XMP 켜고 6000으로 안정적으로 돌아갑니다.",
            "메모리 프로파일 6000 적용해도 문제없습니다.",
            "XMP 활성화 후 며칠 써봤는데 오류 없어요.",
        ],
    },
}

# 어느 주장에도 닿지 않는 문장. **일부러 헷갈리는 것을 섞었다** — 온도·속도·소음
# 같은 낱말이 들어 있지만 그 주장에 대한 것이 아닌 문장들이다. 낱말만 보는 대조는
# 여기서 틀리고, 의미 대조는 여기서 값을 한다.
FILLER: list[str] = [
    "배송이 하루 만에 왔습니다.",
    "포장이 꼼꼼했어요.",
    "가격 대비 만족합니다.",
    "생각보다 크기가 큽니다. 케이스 확인하세요.",
    "설치는 어렵지 않았습니다.",
    "정품 스티커 확인했습니다.",
    "as 문의했더니 응대는 괜찮았어요.",
    "박스 모서리가 눌려 왔지만 제품은 멀쩡합니다.",
    # ↓ 헷갈리게 만든 것들
    "방 온도가 높아서 그런지 여름엔 전체적으로 뜨겁네요.",
    "CPU 온도가 높아 고민인데 이건 별개 문제겠죠.",
    "체감 속도는 빠릅니다. 부팅이 금방이에요.",
    "택배 기사님이 빠르셔서 좋았습니다.",
    "케이스 팬 소음이 더 큽니다.",
    "전원부 발열은 따로 안 재봤습니다.",
    "쓰기 속도는 공식 스펙만 보고 샀습니다.",
]

# 조작 확률이 이 값 이상이면 대조 표본에서 뺀다 — 목업 공개 화면의 약속이다.
# ("조작 확률 20% 이상인 리뷰는 대조 표본에서 제외. 삭제하지 않고 별도 보관한다")
REVIEW_RISK_THRESHOLD = 0.20

# ── 외부 사실 ────────────────────────────────────────────────────────────────
# 게임사가 공개하는 권장 사양. **수치는 발행처 문서에서 확인한 것만 넣는다** —
# 여기가 2단계 하드 제약의 유일한 근거라 지어내면 파이프라인 전체가 거짓이 된다.
# `as_of` 는 그 문서를 확인한 날이다. 9/7 17시 지적(공개 사양과 벤치마크의 시차)
# 에 대한 기획안 §4의 대응이 "시차 자체를 화면에 쓴다"였다.
#
# **어느 조건의 권장 사양인지가 값과 함께 가야 한다.** 12GB 와 8GB 의 차이는
# 게임의 차이이기도 하지만 해상도·옵션 기준의 차이이기도 해서, 기준을 빼면
# "12GB 가 필요하다"가 무슨 말인지 알 수 없다. 그래서 `basis` 가 origin 에 실린다.
GAMES: dict[str, dict] = {
    "인디아나 존스: 그레이트 서클": {
        "vram": 12, "as_of": "2026-09-09",
        "basis": "QHD(1440p) 네이티브 권장",
        "source": "Bethesda 공식 지원 문서"},
    "몬스터 헌터 와일즈": {
        "vram": 8, "as_of": "2026-09-09",
        "basis": "1080p 60fps 중간 옵션(프레임 생성) 권장",
        "source": "Steam 상점 페이지 · Capcom"},
}
# 팀이 9/7 17시(`cmtr1qwnh00bbzvkad7qsscp1`)에 이름을 댄 롤·배틀그라운드·
# 오버워치 2 는 **아직 안 넣었다.** 발행처 페이지에서 수치를 확인하지 못했다
# (롤 지원 문서는 스크립트 렌더, PUBG Steam 페이지는 연령 확인 게이트).
#
# 확인하더라도 셋 다 요구 VRAM 이 낮아(공개된 권장 GPU 가 3~4GB 급이다) 지금
# 카탈로그에서는 **깔때기가 한 개도 못 거른다.** 깔때기 장면은 12GB 쪽에서만
# 나오므로, 저사양 게임만으로 데모를 짜면 3단계 ①이 통째로 안 보인다.

# 파워 용량은 권장 사양이 아니라 계통 합계에서 나온다 — 목업의 "권장 사양 + 계통 여유 20%".
PSU_HEADROOM = 1.2


class PCPack:
    """`DomainPack` 구현. 상태가 없다 — 팩은 데이터고 판단은 엔진이 한다."""

    name = NAME

    def catalog(self) -> list[dict]:
        return [dict(p) for p in CATALOG]

    def extract(self, query: str, known: dict) -> dict:
        """
        1단계 — 사용자 문장에서 이 도메인이 아는 것을 뽑는다.

        **엔진이 아니라 팩이 한다.** 게임 이름은 이 팩의 사전에만 있고, 여행
        팩이라면 도시·날짜를 뽑을 자리다. 예전에는 엔진이 `pack.name == "pc"` 로
        분기해 이 표를 읽었는데, 그러면 도메인이 하나 늘 때마다 엔진을 고쳐야
        해서 `DomainPack` 이 있으나 마나였다.

        **사전에 없는 게임은 지어내지 않는다.** 모르면 안 넣고, 2단계에서
        외부 사실이 비는 것으로 드러난다.
        """
        out: dict = {}

        if "game" not in known:
            for title in GAMES:
                if title in query:
                    out["game"] = title
                    break

        if "budget" not in known:
            budget = extract_budget(query)
            if budget:
                out["budget"] = budget

        if "resolution" not in known:
            for token, value in (("QHD", "QHD 2560×1440"), ("FHD", "FHD 1920×1080"),
                                 ("4K", "4K 3840×2160")):
                if token in query.upper():
                    out["resolution"] = value
                    break

        return out

    def meets(self, part: dict, requirements: dict) -> bool:
        """
        3단계 ① — 품목 **하나**가 하드 제약을 만족하는가.

        `constraints()` 가 조합 규칙(소켓·전력·길이)이라면 이쪽은 낱개 규칙이다.
        둘 다 도메인 지식이라 같이 팩에 있어야 하는데, 예전에는 이 함수만 엔진에
        `vram` 과 `"GPU"` 로 하드코딩돼 있었다 — 여행의 "도보 15분 이내"를 넣으려면
        엔진을 고쳐야 했다.
        """
        vram = requirements.get("vram")
        if vram and part["category"] == "GPU":
            need = int(re.sub(r"\D", "", vram.value) or 0)
            if part.get("vram", 0) < need:
                return False
        return True

    def required_categories(self, known: dict) -> list[str]:
        """
        1단계 — 이번 요청에 **필요한** 카테고리. 8종 전부가 아닐 수 있다.

        되묻기 "쓰던 케이스와 파워를 재사용할까요?" 의 답이 여기로 들어온다.
        목업 4단계 배분 표에서 케이스가 "재사용 — " 으로 비어 있는 것이 이
        자리다. 재사용을 세트에서 빼지 않으면 예산이 그만큼 잘못 잡힌다.

        **쿨러는 기본 목록에 없다.** CPU 에 기본 쿨러가 동봉되기 때문이다. 3단계에서
        *"기본 쿨러로 정격 유지"* 주장이 반증될 때만 편성된다 — 목업이 *"쿨러
        34,000원은 단계 3에서 CPU 기본 쿨러 주장이 반증되며 편성된 항목"* 이라고
        적은 그 경로다. 처음부터 넣어 두면 검증이 세트를 바꾸는 장면 자체가 사라진다.
        """
        reuse = known.get("reuse", "")
        drop: set[str] = {"쿨러"}
        if reuse == "케이스만":
            drop.add("케이스")
        elif reuse == "둘 다 재사용":
            drop |= {"케이스", "파워"}
        return [c for c in CATEGORIES if c not in drop]

    def claims_for(self, code: str) -> list[Claim]:
        return list(CLAIMS.get(code, []))

    def weights(self) -> dict[str, float]:
        return dict(WEIGHTS)

    def followups(self, known: dict) -> list[NeedsInput]:
        """
        룰베이스 빈칸 채우기(기획안 §3). **모델이 질문을 지어내지 않는다.**

        목업의 세 질문 그대로다. 이미 답이 있는 것은 묻지 않으므로, 화면이
        답을 채워 다시 부르면 목록이 줄어든다.
        """
        asks = [
            NeedsInput(key="refresh_hz", question="모니터 주사율이 어떻게 되나요?",
                       options=["60Hz", "144Hz", "240Hz"]),
            NeedsInput(key="reuse", question="쓰던 케이스와 파워를 재사용할까요?",
                       options=["케이스만", "둘 다 재사용", "둘 다 교체"]),
            NeedsInput(key="priority", question="소음과 성능 중 어느 쪽이 우선인가요?",
                       options=["소음", "성능", "상관없음"]),
        ]
        return [a for a in asks if a.key not in known]

    def external_facts(self, known: dict) -> list[Requirement]:
        """게임사 공개 권장 사양. 모르는 게임이면 빈 목록이다 — 지어내지 않는다."""
        game = known.get("game")
        spec = GAMES.get(game)
        if not spec:
            return []
        origin = f"게임사 공개 권장 사양 · 〈{game}〉 {spec['basis']} · {spec['source']}"
        out = [
            Requirement(key="vram", value=f"{spec['vram']}GB 이상", origin=origin,
                        hard=True, as_of=spec["as_of"]),
        ]
        if known.get("resolution"):
            out.append(Requirement(key="resolution", value=known["resolution"],
                                   origin="사용자 입력", hard=False))
        if known.get("refresh_hz"):
            # 주사율은 하드 제약으로 걸지 않는다 — 평균 프레임을 판정할 실측 표본이
            # 없기 때문이다. 목업도 이 항목을 "판정하지 않았다"로 남긴다.
            out.append(Requirement(
                key="refresh_hz", value=known["refresh_hz"], origin="되묻기 응답",
                hard=False, judged=False,
                unjudged_reason="기준 평균 프레임은 실측 표본이 부족해 판정하지 않았습니다."))
        return out

    def constraints(self, candidate_set: list[dict]) -> list[str]:
        """
        호환성. **틀리면 물건이 안 돈다** — 그럴듯한 필터가 아니라 판정이다.

        기획안 §4가 PC 를 고른 결정적 이유 중 하나가 이것이다. 다나와가 이미
        하는 일이라 차별점은 아니지만, 3단계 ①이 진짜 룰이 되는 자리다.
        """
        by_cat = {p["category"]: p for p in candidate_set}
        problems: list[str] = []

        cpu, mb = by_cat.get("CPU"), by_cat.get("메인보드")
        if cpu and mb and cpu["socket"] != mb["socket"]:
            problems.append(
                f"CPU 소켓({cpu['socket']})과 메인보드 소켓({mb['socket']})이 맞지 않습니다."
            )

        ram = by_cat.get("RAM")
        if ram and mb and ram["ram_type"] != mb["ram_type"]:
            problems.append(
                f"메모리 규격({ram['ram_type']})을 이 메인보드({mb['ram_type']})가 지원하지 않습니다."
            )

        psu, gpu = by_cat.get("파워"), by_cat.get("GPU")
        if psu:
            draw = sum(p.get("tdp", 0) for p in candidate_set)
            need = int(draw * PSU_HEADROOM)
            if psu["watt"] < need:
                problems.append(
                    f"계통 소비 {draw}W 에 여유 20%를 더하면 {need}W 가 필요한데 "
                    f"파워가 {psu['watt']}W 입니다."
                )

        case = by_cat.get("케이스")
        if case and gpu and gpu["length_mm"] > case["max_gpu_mm"]:
            problems.append(
                f"그래픽카드 길이 {gpu['length_mm']}mm 가 케이스 한계 {case['max_gpu_mm']}mm 를 넘습니다."
            )

        cooler = by_cat.get("쿨러")
        if cooler and cpu and cpu["socket"] not in cooler["sockets"]:
            problems.append(f"쿨러가 이 CPU 소켓({cpu['socket']})을 지원하지 않습니다.")

        return problems

    def review_source(self) -> SyntheticReviews:
        return SyntheticReviews(REVIEW_POOLS, CLAIM_PHRASES, FILLER,
                                REVIEW_RISK_THRESHOLD)


pack = PCPack()
