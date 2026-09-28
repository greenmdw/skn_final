"""조립 가이드 에이전트 — Strands Agents SDK.

확정/추천된 부품 목록을 받아 조립 순서·주의사항 가이드를 만든다. `src/agent/conditions_agent.py`와
같은 경계 원칙을 따른다:

- 조립 **순서**는 코드가 고정한다(`ASSEMBLY_ORDER`) — 일반적인 PC 조립 순서는 의견이 아니라
  관행이라, 에이전트가 순서를 새로 만들거나 단계를 빼먹지 않는다.
- 각 단계 안내는 `search_guide` 도구(= `src/rag/care_guides.py`의 RAG 검색)가 찾은 내용만
  쓴다. 검색 결과가 없으면 "특별히 확인할 점 없음"이라고 정직하게 쓰고, 없는 주의사항을
  지어내지 않는다.
- `available()`이 False(MOCK_MODE·키 없음·`ASSEMBLY_GUIDE_AGENT=0`)면 규칙 기반 폴백을 쓴다 —
  검색 자체는 그대로 실제로 하고, 문장만 템플릿이다("[3-C] 문장 생성 실패는 신뢰도에 영향을
  주지 않는다"는 이 프로젝트의 원칙과 같다 — 여기서도 에이전트 실패가 가이드 자체를 막지 않는다).
"""
from __future__ import annotations

from src.config import ASSEMBLY_GUIDE_AGENT, LLM_MODEL, LLM_PROVIDER, MOCK_MODE, OPENAI_API_KEY
from src.rag.care_guides import search_care_guide

# 일반적인 PC 조립 순서(케이스 준비 → 전원 → 메인보드 계열 → 확장 카드 → 정리). 의견이 아니라 관행이다.
ASSEMBLY_ORDER = ["케이스", "파워", "메인보드", "CPU", "쿨러", "RAM", "저장장치", "GPU"]


def available() -> bool:
    return (not MOCK_MODE and ASSEMBLY_GUIDE_AGENT and LLM_PROVIDER == "openai"
            and bool(OPENAI_API_KEY) and bool(LLM_MODEL))


def _ordered_items(items: list[dict]) -> list[dict]:
    """items(슬롯당 하나)를 표준 조립 순서로 정렬. 순서표에 없는 슬롯은 등장 순서대로 맨 뒤에."""
    rank = {slot: i for i, slot in enumerate(ASSEMBLY_ORDER)}
    return sorted(items, key=lambda it: rank.get(it["slot"], len(ASSEMBLY_ORDER)))


def build_guide_fallback(ordered_items: list[dict]) -> str:
    """규칙 기반 폴백 — 검색은 실제로 하되 문장은 템플릿. 에이전트 미가용 시 이걸 쓴다.

    단계마다 "설치"(kind=install 문서: 장착 방법)와 "확인"(care 문서: 주의사항)을 각각 검색해 싣는다.
    둘 다 없으면 없다고 쓴다 — 없는 절차를 지어내지 않는다."""
    lines = []
    for i, it in enumerate(ordered_items, start=1):
        name = it["product"]["name"]
        install = search_care_guide(f"{it['slot']} {name} 장착 설치 방법", k=1, slot=it["slot"], kind="install")
        caution = search_care_guide(f"{it['slot']} {name} 조립 시 확인할 점", k=1, slot=it["slot"])
        lines.append(f"{i}. {it['slot']} — {name}")
        lines.append(f"   설치: {install[0]['text'] if install else '이 부품의 설치 안내 문서가 아직 없습니다. 제품 설명서를 확인하세요.'}")
        lines.append(f"   확인: {caution[0]['text'] if caution else '특별히 확인할 점은 없습니다.'}")
    return "\n".join(lines)


def make_tools() -> list:
    from strands import tool

    @tool
    def search_guide(slot: str, query: str) -> str:
        """그 슬롯 부품의 설치 방법과 확인할 점 문서를 찾는다. 다른 부품의 문서는 나오지 않는다.

        Args:
            slot: 슬롯 이름 — 주어진 그대로 (CPU·GPU·RAM·메인보드·저장장치·파워·케이스·쿨러)
            query: 찾고 싶은 내용 — 부품명 + 알고 싶은 것 (예: "RTX 4070 SUPER 장착 방법")
        """
        install = search_care_guide(query, k=1, slot=slot, kind="install")
        caution = search_care_guide(query, k=1, slot=slot)
        lines = [f"[설치] {h['text']}" for h in install] + [f"[확인] {h['text']}" for h in caution]
        return "\n".join(lines) or "관련된 가이드를 찾지 못했습니다."

    return [search_guide]


def _model():
    from strands.models.openai import OpenAIModel

    return OpenAIModel(client_args={"api_key": OPENAI_API_KEY}, model_id=LLM_MODEL,
                       params={"temperature": 0.2})


def _system_prompt(ordered_items: list[dict]) -> str:
    lines = [f"{i}. {it['slot']}: {it['product']['name']}" for i, it in enumerate(ordered_items, start=1)]
    return "\n".join([
        "당신은 TrueFit에서 확정된 부품 목록으로 조립 가이드를 작성하는 도우미입니다.",
        "",
        "아래는 이미 정해진 조립 순서와 부품입니다 — 순서를 바꾸거나 단계를 빼먹지 않습니다:",
        *lines,
        "",
        "각 단계마다 search_guide(slot, query) 도구를 그 슬롯 이름 그대로 불러 설치 방법과 확인할 점을 찾고,",
        "찾은 문장을 줄이거나 바꾸지 말고 그대로 옮깁니다. 검색 결과가 없으면 없다고 정직하게 씁니다 —",
        "없는 절차나 주의사항을 지어내지 않습니다.",
        "",
        "출력 형식(이것만 출력합니다 — 서론·맺음말·설명 없음):",
        "1. 케이스 — 부품명",
        "   설치: (도구가 준 [설치] 문장)",
        "   확인: (도구가 준 [확인] 문장)",
        "제목 줄은 '번호. 슬롯이름 — 부품명' 입니다(예: '3. GPU — NVIDIA GeForce RTX 4070 SUPER').",
        "순서·부품명·슬롯 이름은 위에 주어진 그대로 씁니다.",
        "한국어 존댓말로 답합니다.",
    ])


def build_guide(items: list[dict]) -> dict:
    """{"status": "ready", "text": str}. 품목이 없으면만 다른 status.

    에이전트가 미가용이거나 실패하면 규칙 폴백으로 내려간다 — 이 기능은 [3-C]/[5]처럼
    "문장 생성 실패가 결과 자체를 막지 않는다"는 원칙을 따른다. 검색(RAG)은 폴백에서도
    실제로 수행되므로, 사용자에게 보이는 조립 가이드는 항상 실제 데이터를 인용한다.
    """
    ordered = _ordered_items(items)
    if not ordered:
        return {"status": "pending", "text": None}
    if not available():
        return {"status": "ready", "text": build_guide_fallback(ordered)}
    from strands import Agent

    try:
        agent = Agent(model=_model(), system_prompt=_system_prompt(ordered),
                     tools=make_tools(), callback_handler=None)
        result = agent("이 목록으로 조립 가이드를 작성해 주세요.")
        text = str(result).strip()
        if not text:
            raise ValueError("empty_agent_response")
        return {"status": "ready", "text": text}
    except Exception:  # noqa: BLE001 — 에이전트 실패는 가이드 자체를 막지 않는다, 폴백으로
        return {"status": "ready", "text": build_guide_fallback(ordered)}
