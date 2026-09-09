"""
Strands Agents SDK 기반 셀러/바이어 에이전트 — 해커톤 필수 요건.

대회 규정이 *"Build a new AI agent with **Strands Agents**"* 이고 심사 기준 1번이
그 사용도 자체를 묻는다. `llm_agents.py` 는 OpenAI
SDK 를 직접 호출해서 그 기준을 채우지 못한다.

`agents.py`/`llm_agents.py` 와 **정확히 같은 인터페이스**(`SellerAgentPort` /
`BuyerAgentPort`)를 구현한다. `negotiate.py` 는 `NEGOTIATOR_MODE` 만 보고,
라운드 진행·로그 적재·낙찰 로직은 한 줄도 안 바뀐다.

프롬프트는 `agent_prompts.py` 에서 온다 — OpenAI 어댑터와 같은 문장을 쓴다.
정보 은닉 규약(셀러는 바이어 상한가를 못 본다)이 그 문장 안에 들어 있어서,
어댑터마다 프롬프트를 들고 있으면 한쪽만 고쳐질 때 규약이 조용히 깨진다.

**모델 바꾸기.** `MODEL_PROVIDER` 하나다. `openai`(기본) / `bedrock` 이고, 나머지
(`Agent`, `structured_output`, 프롬프트, 스키마, 도구)는 그대로다. 해커톤 가점
항목이 이 스위치다.

**Bedrock 없이도 전부 돌아간다.** 기본 프로바이더가 `openai` 이고, 그보다 먼저
`rule`·`label`·`none` 모드가 모델을 아예 안 쓴다 — 검사와 데모는 어느 쪽 자격증명도
필요 없다.

[모델 이름을 자리(role)로 받는 이유]
프로바이더마다 모델 id 형식이 다르다(`gpt-4o-mini` ↔ `global.anthropic.claude-opus-5`).
호출부가 id 를 직접 넘기면 프로바이더를 바꾸는 순간 남의 형식 id 가 그대로 흘러가서
**런타임에야 터진다.** 그래서 호출부는 `_model("match")` 처럼 **자리**만 말하고,
그 자리의 id 는 프로바이더별 환경변수에서 고른다.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from .schemas import SellerRegister, BuyerRequest
from .agent_prompts import seller_prompt, buyer_prompt

# 어느 프로바이더를 쓸 것인가. openai(기본) / bedrock
MODEL_PROVIDER = os.environ.get("MODEL_PROVIDER", "openai").lower()

# 프로바이더별 기본 모델. 자리별로 덮어쓰려면 아래 `_id_for` 참고.
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
# Bedrock 은 교차 리전 추론 프로파일 접두사(global./us./eu.)를 붙인 id 를 받는다.
# **날짜 접미사나 -v1:0 을 붙이지 않는다** — 지금 모델 id 는 그 자체로 완결이다.
BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "global.anthropic.claude-opus-5")
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")


# ── 구조화 출력 스키마 ──────────────────────────────────────────────────────
# llm_agents.py 의 SELLER_SCHEMA / BUYER_SCHEMA(JSON Schema dict)와 1:1 대응이다.
# Strands 는 pydantic 모델을 받아 스키마를 스스로 만든다.
class SellerOffer(BaseModel):
    """셀러가 이번 라운드에 내놓는 것."""

    price: int = Field(description="이번 라운드에 제시할 단가")
    message: str = Field(description="협상 상대에게 보낼 짧은 메시지(한국어, 1문장)")


class BuyerDecision(BaseModel):
    """바이어가 제시가를 보고 내리는 판단."""

    accept: bool = Field(description="이 제시가를 수락할지 여부")
    message: str = Field(description="협상 상대에게 보낼 짧은 메시지(한국어, 1문장)")


def _id_for(role: str | None, provider: str) -> str:
    """
    이 자리에서 쓸 모델 id. `{ROLE}_{PROVIDER}_MODEL` → `{PROVIDER}_MODEL` 순으로 찾는다.

        _id_for("match", "bedrock")  →  MATCH_BEDROCK_MODEL  또는 BEDROCK_MODEL
        _id_for("match", "openai")   →  MATCH_MODEL          또는 OPENAI_MODEL

    openai 쪽 자리 변수에 접두사가 없는 이유는 이 이름들이 먼저 있었기 때문이다
    (`MATCH_MODEL`·`ASSISTANT_MODEL`·`RISK_MODEL`). 문서와 .env 가 그 이름을 쓰고 있다.
    """
    fallback = BEDROCK_MODEL if provider == "bedrock" else MODEL
    if not role:
        return fallback
    suffix = "_BEDROCK_MODEL" if provider == "bedrock" else "_MODEL"
    return os.environ.get(f"{role.upper()}{suffix}") or fallback


def _load_env_once() -> None:
    """
    `.env` 를 한 번 더 찾는다. `main.py` 는 기동할 때 읽지만 스크립트·검사는 안 읽는다.

    자격증명이 필요한 지점이 `_model()` 하나뿐이라 여기 둔다 — 키를 .env 에 넣어
    두고도 "키가 없습니다"를 보는 일이 없게.
    """
    from dotenv import load_dotenv

    load_dotenv()


def _model(role: str | None = None):
    """
    이 자리에서 쓸 모델. **호출부는 자리 이름만 말하고 id 는 모른다.**

    임포트를 함수 안에 두는 이유는 기본 모드(`rule`·`label`·`none`)가 이 패키지들
    없이도 돌아야 하기 때문이다.
    """
    if MODEL_PROVIDER == "bedrock":
        return _bedrock(_id_for(role, "bedrock"))
    if MODEL_PROVIDER != "openai":
        raise RuntimeError(
            f"모르는 MODEL_PROVIDER 입니다: {MODEL_PROVIDER!r}. "
            "쓸 수 있는 것: 'openai'(기본), 'bedrock'."
        )
    return _openai(_id_for(role, "openai"))


def _openai(model_id: str):
    from strands.models.openai import OpenAIModel

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        _load_env_once()
        api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY 환경변수가 설정되어 있지 않습니다. "
            "키 없이 돌리려면 기본 모드(NEGOTIATOR_MODE=rule · MATCH_MODE=label · "
            "RISK_MODE=none)를 쓰거나, MODEL_PROVIDER=bedrock 으로 가세요."
        )
    return OpenAIModel(client_args={"api_key": api_key}, model_id=model_id)


def _bedrock(model_id: str):
    """
    Bedrock. 자격증명은 boto3 의 표준 체인(환경변수·프로파일·인스턴스 역할)에서 온다.

    **모델 id 에 날짜 접미사나 `-v1:0` 을 붙이지 않는다.** 교차 리전 추론 프로파일
    접두사(`global.`·`us.`·`eu.`)만 붙인 `global.anthropic.claude-opus-5` 형태다.

    대조·조작확률처럼 호출이 많은 자리는 `MATCH_BEDROCK_MODEL` 로 더 싼 모델을
    따로 지정하는 것이 정석이다(예: `global.anthropic.claude-haiku-4-5`).
    """
    try:
        from strands.models.bedrock import BedrockModel
    except ImportError as e:  # pragma: no cover - 설치 상태에 따라 다름
        raise RuntimeError(
            "Bedrock 프로바이더를 쓸 수 없습니다. `pip install 'strands-agents[bedrock]' boto3` "
            f"가 필요합니다: {e}"
        ) from e

    if not os.environ.get("AWS_REGION") and not os.environ.get("AWS_PROFILE"):
        _load_env_once()

    return BedrockModel(model_id=model_id,
                        region_name=os.environ.get("AWS_REGION", AWS_REGION))


def _agent(system_prompt: str):
    """
    라운드마다 새 Agent 를 만든다 — 대화 이력을 남기지 않기 위해서다.

    Strands 의 `Agent` 는 기본적으로 메시지 이력을 누적하는데, 협상에서 그러면
    셀러 에이전트가 **자기가 이전에 본 것을 계속 들고 다닌다**. 라운드 간에
    무엇을 기억할지는 `negotiate.py` 가 인자(`round_no`, `last_reject_price`)로
    정하는 것이고, 그게 정보 은닉의 경계이기도 하다. 이력을 SDK 에 맡기면
    그 경계가 흐려진다.
    """
    from strands import Agent

    return Agent(model=_model(), system_prompt=system_prompt)


SELLER_SYSTEM = (
    "당신은 B2B 조달 마켓플레이스의 판매자 측 협상 에이전트입니다. "
    "주어진 사실만 근거로 판단하고, 요청된 형식으로만 답하세요."
)
BUYER_SYSTEM = (
    "당신은 B2B 조달 마켓플레이스의 구매자 측 협상 에이전트입니다. "
    "주어진 사실만 근거로 판단하고, 요청된 형식으로만 답하세요."
)


class StrandsSellerAgent:
    """`SellerAgentPort` 구현. 반환 계약은 규칙 기반과 동일한 `(price, message)`."""

    def decide(
        self, offer: SellerRegister, round_no: int, last_reject_price: int | None
    ) -> tuple[int, str]:
        result = _agent(SELLER_SYSTEM).structured_output(
            SellerOffer, seller_prompt(offer, round_no, last_reject_price)
        )
        return int(result.price), str(result.message)


class StrandsBuyerAgent:
    """`BuyerAgentPort` 구현. 반환 계약은 규칙 기반과 동일한 `(accept, message)`."""

    def decide(
        self, request: BuyerRequest, offer_price: int, seller_message: str
    ) -> tuple[bool, str]:
        result = _agent(BUYER_SYSTEM).structured_output(
            BuyerDecision, buyer_prompt(request, offer_price, seller_message)
        )
        return bool(result.accept), str(result.message)
