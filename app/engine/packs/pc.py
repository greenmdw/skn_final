"""
PC 부품 팩 — 2026-09-07에 확정된 도메인(기획안 §4).

[데이터는 전부 예시다]
제조사·게임 이름은 **실재하지 않는 것**으로 썼다. `docs/목업/README.md` 가 같은
정책을 적어 뒀고 이유도 같다 — 실제 제품에 대한 가짜 리뷰 판정을 만들지 않으려는
것이다. 데모에 실제 게임명이 필요하면 그때 바꾼다.

숫자와 시나리오는 `docs/목업/pc-부품.html` 의 것을 그대로 쓴다(예산 120만,
〈오르카 프로토콜〉 QHD 상옵, 권장 사양 2026-07-18 상향). 목업과 API 응답이
다른 숫자를 말하면 발표에서 둘 중 하나는 거짓말이 된다.

[이 팩이 채우는 칸]
기획안 §3이 도메인 의존이라 표시한 세 칸 + `pack.py` 가 찾아낸 네 번째 칸.

    품목 사전       catalog() · claims_for() · followups() · weights()
    외부 사실       external_facts()   ← 게임사 공개 권장 사양
    하드 제약       constraints()      ← 소켓·전력·길이. 기획안 §3 표가 안 센 칸
    리뷰 소스       review_source()
"""

from __future__ import annotations

from ...reviews.synthetic import SyntheticReviews
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

# 합성 리뷰 라벨. 목업 표의 숫자 그대로다 — 목업과 API 가 다른 수를 말하면 안 된다.
REVIEW_LABELS: dict[str, dict] = {
    "gpu-temp":   {"samples": {"리뷰": 214, "QA": 31}, "relevant": 214, "hits": 47,
                   "note": "214건 중 47건이 80°C 이상을 언급"},
    "gpu-power":  {"samples": {"리뷰": 214}, "relevant": 214, "hits": 0,
                   "note": "반증 사례 없음"},
    "cpu-cooler": {"samples": {"리뷰": 178}, "relevant": 178, "hits": 63,
                   "note": "178건 중 63건이 서멀 스로틀링 언급"},
    "psu-noise":  {"samples": {"리뷰": 96}, "relevant": 96, "hits": 11,
                   "note": "96건 중 11건이 코일 소음 언급"},
    # 읽은 표본은 142건이지만 실측을 언급한 것은 3건뿐이다. 임계값이 걸리는 자리.
    "ssd-write":  {"samples": {"리뷰": 142}, "relevant": 3, "hits": 1,
                   "note": "실측을 언급한 리뷰가 3건뿐 — 표본 부족"},
    "ram-xmp":    {"samples": {"리뷰": 88, "QA": 19}, "relevant": 107, "hits": 0,
                   "note": "Q&A 19건 포함, 반증 없음"},
}

# ── 외부 사실 ────────────────────────────────────────────────────────────────
# 게임사가 공개하는 최소·권장 사양. 게임명은 가상이다.
# `as_of` 를 반드시 채운다 — 9/7 17시 지적(공개 사양과 벤치마크의 시차)에 대한
# 기획안 §4의 대응이 "시차 자체를 화면에 쓴다"였다.
GAMES: dict[str, dict] = {
    "오르카 프로토콜": {"vram": 12, "as_of": "2026-07-18",
                       "note": "발표 이후 권장 사양이 한 차례 상향됐습니다."},
    "실버레인": {"vram": 8, "as_of": "2026-03-02", "note": ""},
    "헤일로우 드리프트": {"vram": 10, "as_of": "2026-05-30", "note": ""},
}

# 파워 용량은 권장 사양이 아니라 계통 합계에서 나온다 — 목업의 "권장 사양 + 계통 여유 20%".
PSU_HEADROOM = 1.2


class PCPack:
    """`DomainPack` 구현. 상태가 없다 — 팩은 데이터고 판단은 엔진이 한다."""

    name = NAME

    def catalog(self) -> list[dict]:
        return [dict(p) for p in CATALOG]

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
        origin = f"게임사 공개 권장 사양 · 〈{game}〉"
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
        return SyntheticReviews(REVIEW_LABELS)


pack = PCPack()
