"""브랜드·부품 슬롯 이름 맞추기 — 사용자가 말한 이름("인텔", "그래픽카드")을 카탈로그 표기("Intel", "GPU")로.

선호 신호는 (슬롯, 브랜드) 문자열로 쌓인다. 조건 에이전트가 적는 값은 LLM 이 쓴 자유 문자열이고 교체 기록에서
추론한 값은 카탈로그 표기라, 맞추지 않으면 같은 브랜드가 다른 신호로 갈리고("인텔" ≠ "Intel") 직접 말한
"인텔 좋아요"가 CPU 조건(brand_pref: intel)에도 안 담겼다.

카탈로그 표기는 슬롯마다 다르다(케이스 "커세어 (Corsair)" · 파워 "Corsair" · RAM "CORSAIR") — 신호는 슬롯별로
쌓이므로 목표는 "그 슬롯의 카탈로그 표기"다. 모르는 이름은 버리지 않고 다듬어서 그대로 둔다.
"""
from __future__ import annotations

import re

# 같은 브랜드를 부르는 이름들. 첫 항목이 대표(비교 키). 카탈로그 표기의 괄호 안·앞 이름도 따로 비교하므로
# "커세어 (Corsair)" 같은 것은 여기 없어도 맞는다 — 여기는 사용자가 말하는 한글 이름·제품군 이름을 모은다.
_GROUPS = [
    ("intel", "인텔", "코어", "core"),
    ("amd", "에이엠디", "라이젠", "ryzen", "라데온", "radeon"),
    ("nvidia", "엔비디아", "지포스", "geforce", "rtx"),
    ("samsung", "삼성", "삼성전자"),
    ("skhynix", "sk하이닉스", "하이닉스", "hynix"),
    ("micron", "마이크론"),
    ("corsair", "커세어"),
    ("coolermaster", "쿨러마스터", "쿨마"),
    ("zalman", "잘만"),
    ("micronics", "마이크로닉스"),
    ("antec", "안텍"),
    ("lianli", "리안리"),
    ("seasonic", "시소닉"),
    ("asus", "에이수스", "아수스"),
    ("msi", "엠에스아이"),
    ("gigabyte", "기가바이트"),
    ("darkflash", "다크플래쉬", "다크플래시"),
    ("hyte", "하이트"),
    ("phanteks", "판텍스"),
    ("fractaldesign", "프랙탈디자인", "프랙탈"),
    ("bequiet", "비콰이엇"),
    ("deepcool", "딥쿨"),
    ("noctua", "녹투아"),
    ("thermaltake", "써멀테이크", "서멀테이크"),
    ("thermalright", "써멀라이트", "서멀라이트"),
    ("westerndigital", "웨스턴디지털", "wd"),
    ("kingston", "킹스톤"),
]


def _key(text: str) -> str:
    return re.sub(r"[\s.\-!_'’]", "", text).lower()


_ALIAS = {_key(name): group[0] for group in _GROUPS for name in group}


def brand_key(text: str) -> str:
    """비교 키 — 같은 브랜드면 같은 값(대소문자·공백·기호 무시, 한글 별칭은 대표 이름으로)."""
    key = _key(text)
    return _ALIAS.get(key, key)


def _catalog_keys(brand: str) -> set[str]:
    """카탈로그 표기 하나의 비교 키들 — "커세어 (Corsair)"면 전체·괄호 앞·괄호 안."""
    keys = {brand_key(brand)}
    found = re.match(r"^(.*?)\s*\((.*?)\)\s*$", brand)
    if found:
        keys |= {brand_key(found.group(1)), brand_key(found.group(2))}
    return keys


def canonical_brand(text: str, catalog_brands: list[str]) -> str:
    """그 슬롯의 카탈로그 표기 중 같은 브랜드가 있으면 그 표기, 없으면 공백만 다듬은 원래 값."""
    wanted = brand_key(text)
    return next((b for b in catalog_brands if wanted in _catalog_keys(b)), text.strip())


def cpu_brand_pref(text: str) -> str | None:
    """CPU 조건 brand_pref(intel·amd)에 담을 값. 카탈로그 없이 별칭만으로 — 조건 에이전트가 쓴다."""
    key = brand_key(text)
    return key if key in ("intel", "amd") else None


# 부품 슬롯을 부르는 말 → 카탈로그 슬롯. 결과 화면 채팅의 교체 요청 해석(recommendation_service)도 이 표를 쓴다.
SLOT_SYNONYMS: dict[str, str] = {
    "그래픽카드": "GPU", "그래픽": "GPU", "지포스": "GPU", "라데온": "GPU", "gpu": "GPU",
    "씨피유": "CPU", "프로세서": "CPU", "cpu": "CPU",
    "램": "RAM", "메모리": "RAM", "ram": "RAM",
    "메인보드": "메인보드", "마더보드": "메인보드",
    "저장장치": "저장장치", "에스에스디": "저장장치", "ssd": "저장장치", "hdd": "저장장치", "하드": "저장장치",
    "파워": "파워", "전원": "파워", "psu": "파워",
    "케이스": "케이스",
    "쿨러": "쿨러", "쿨링": "쿨러",
}
PC_SLOTS = ("CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러")


def canonical_slot(text: str) -> str:
    """부품 슬롯 이름을 카탈로그 슬롯으로("그래픽카드" → "GPU"). 부분 일치는 하지 않는다(엉뚱한 슬롯 방지).
    모르는 이름은 다듬어서 그대로 둔다."""
    raw = text.strip()
    by_lower = {s.lower(): s for s in PC_SLOTS}
    return by_lower.get(raw.lower()) or SLOT_SYNONYMS.get(raw.lower().replace(" ", "")) or raw
