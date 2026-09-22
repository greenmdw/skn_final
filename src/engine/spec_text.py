"""사양 텍스트(업로드 파일·견적 설명)에서 부품별 문구를 뽑는 규칙 기반 파서.

LLM 추출(src.agent.spec_extraction_agent)이 꺼져 있거나(MOCK_MODE·키 없음·SPEC_EXTRACTION_AGENT=0)
실패했을 때의 fallback이다. "key: value" 형식의 줄만 인식한다 — 자유 문장(유튜브 설명란처럼
줄글로 이어진 텍스트)은 이 규칙으로 못 뽑는다. 그래서 LLM 경로가 우선이고, 이건 그게 없을 때도
파일 업로드 최소 기능이 죽지 않게 하는 안전망이다.

computer의 slot_structure(config/categories/computer.yaml)와 같은 8개 슬롯 이름을 쓴다."""
from __future__ import annotations

import re

SPEC_SLOTS = ("CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러")

_SPEC_LINE = re.compile(
    r"(?im)^\s*(cpu|프로세서|gpu|그래픽카드|그래픽|ram|메모리|메인보드|mainboard|motherboard|"
    r"저장장치|ssd|storage|파워|psu|power|케이스|case|쿨러|cooler)\s*[:=]\s*(.+?)\s*$")
_SPEC_KEY_MAP = {
    "cpu": "CPU", "프로세서": "CPU",
    "gpu": "GPU", "그래픽카드": "GPU", "그래픽": "GPU",
    "ram": "RAM", "메모리": "RAM",
    "메인보드": "메인보드", "mainboard": "메인보드", "motherboard": "메인보드",
    "저장장치": "저장장치", "ssd": "저장장치", "storage": "저장장치",
    "파워": "파워", "psu": "파워", "power": "파워",
    "케이스": "케이스", "case": "케이스",
    "쿨러": "쿨러", "cooler": "쿨러",
}


def parse_spec_text(content: str) -> dict[str, str]:
    """'CPU: i5-13600K' 같은 key: value 줄만 규칙 기반으로 뽑는다. 매칭 안 되면 빈 dict."""
    specs: dict[str, str] = {}
    for m in _SPEC_LINE.finditer(content):
        specs[_SPEC_KEY_MAP[m.group(1).lower()]] = m.group(2).strip()
    return specs
