"""관리형 LLM API 호출 래퍼 (벤더 중립).

실제 구현에서는 env 로 주입된 LLM_PROVIDER / LLM_MODEL 에 맞는 SDK 로
- 함수 호출(structured output) 로 스키마를 강제한 JSON
- 자유 텍스트 응답
을 받는다. 현재는 MOCK_MODE 에서 용도(system 프롬프트 / 스키마 모양)를 보고 고정 가짜 응답을 준다.
"""
from __future__ import annotations

import json
from typing import Any

from src.config import LLM_MODEL, LLM_PROVIDER, MOCK_MODE, OPENAI_API_KEY

_client: Any = None


def _get_client():
    global _client
    if _client is None:
        if LLM_PROVIDER != "openai":
            raise NotImplementedError(f"call_llm: 지원하지 않는 LLM_PROVIDER={LLM_PROVIDER!r}")
        if not OPENAI_API_KEY:
            raise RuntimeError("call_llm: OPENAI_API_KEY 미설정 (MOCK_MODE=0)")
        from openai import OpenAI

        _client = OpenAI(api_key=OPENAI_API_KEY)
    return _client


def _call_openai(prompt: str, *, system: str | None, output_schema: dict | None, model: str) -> dict:
    client = _get_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict[str, Any] = {"model": model or LLM_MODEL, "messages": messages}
    if output_schema:
        # strict=False: 일부 스키마가 dict[str, Any] 같은 자유 형태 필드를 포함해
        # OpenAI strict 모드의 additionalProperties 제약과 맞지 않을 수 있다.
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "output", "schema": output_schema, "strict": False},
        }

    last_error: Exception | None = None
    for _attempt in range(2):  # 파싱 실패 시 1회 재시도
        response = client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        if not output_schema:
            return {"text": content}
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            last_error = exc
    raise ValueError(f"call_llm: 구조화 출력 JSON 파싱 실패: {last_error}")


def call_llm(
    prompt: str,
    *,
    system: str | None = None,
    output_schema: dict | None = None,
    model: str = LLM_MODEL,
) -> dict:
    """LLM 호출.

    Args:
        prompt: 사용자 메시지 텍스트.
        system: 시스템 프롬프트.
        output_schema: 주어지면 스키마에 맞는 dict, 없으면 {"text": str} 반환.
        model: 모델 식별자 (env 주입).

    Returns:
        output_schema 가 있으면 dict, 없으면 {"text": str}.
    """
    if not MOCK_MODE:
        return _call_openai(prompt, system=system, output_schema=output_schema, model=model)

    preview = prompt.replace("\n", " ")[:36]
    print(f"[MOCK] LLM 호출: {preview}...")

    sys_text = system or ""
    if "검증 쟁점" in sys_text:
        return {"text": "[MOCK] 관측값과 근거를 그대로 옮긴 쟁점 문장입니다."}

    # 그 외 구조화 출력 요청 → 호출자가 시나리오 정답값을 직접 주입하므로 빈 골격 반환
    return {"text": "[MOCK] 일반 응답"}


def _call_openai_vision(image_data_url: str, *, system: str | None, output_schema: dict | None, model: str,
                        temperature: float | None) -> dict:
    client = _get_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    # detail="high" — 기본값(auto/low)은 캡처 속 작은 글자(모델번호·코드)를 다른 토큰으로
    # 잘못 읽는 사례가 실측됐다. 타일 단위 고해상도 처리라 토큰 비용은 늘지만, 이미지 1장짜리
    # 저빈도 호출이라 감당할 만하다.
    messages.append({"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": image_data_url, "detail": "high"}}]})

    kwargs: dict[str, Any] = {"model": model or LLM_MODEL, "messages": messages}
    if temperature is not None:
        kwargs["temperature"] = temperature
    if output_schema:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "output", "schema": output_schema, "strict": False},
        }

    # 일부 모델(예: gpt-6-luna)은 temperature 커스텀 값을 아예 거부한다("Only the default (1)
    # value is supported") — 모델별로 알고 있다가 분기하는 대신, 그 오류가 나면 그 자리에서
    # temperature를 빼고 같은 요청을 다시 보낸다. 미래에 같은 제약을 가진 다른 모델이 와도
    # 코드를 안 고쳐도 된다. 이미지가 실려 있어 비용이 드니, 확인용 별도 호출은 만들지 않는다.
    from openai import BadRequestError

    def _create(call_kwargs: dict[str, Any]):
        try:
            return client.chat.completions.create(**call_kwargs)
        except BadRequestError as exc:
            if "temperature" in call_kwargs and "temperature" in str(exc).lower():
                return client.chat.completions.create(**{k: v for k, v in call_kwargs.items() if k != "temperature"})
            raise

    last_error: Exception | None = None
    for _attempt in range(2):
        response = _create(kwargs)
        content = response.choices[0].message.content or ""
        if not output_schema:
            return {"text": content}
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            last_error = exc
    raise ValueError(f"call_llm_vision: 구조화 출력 JSON 파싱 실패: {last_error}")


def call_llm_vision(
    image_data_url: str,
    *,
    system: str | None = None,
    output_schema: dict | None = None,
    model: str = LLM_MODEL,
    temperature: float | None = None,
) -> dict:
    """이미지 1장을 보는 LLM 호출. call_llm과 같은 계약(스키마 있으면 dict, 없으면 {"text": str})이고
    입력만 텍스트 대신 이미지다 — call_llm 자체의 시그니처·동작은 바꾸지 않는다(다른 호출부가 많다).

    Args:
        image_data_url: "data:image/png;base64,..." 형식의 데이터 URL. 원본 이미지는 이 호출이
            끝나면 버려진다 — 저장하지 않는다(견적 점검 사양 추출의 개인정보·저작권 원칙).
        system, output_schema, model: call_llm과 같다.
        temperature: 안 주면(기본 None) API 기본값. 견적 점검 이미지 추출처럼 "같은 입력엔 같은
            답"이 중요한 호출은 0으로 준다 — 실측(2026-10-01)으로 기본값보다 환각이 줄고
            재현 가능해지는 걸 확인했다.
    """
    if not MOCK_MODE:
        return _call_openai_vision(image_data_url, system=system, output_schema=output_schema, model=model,
                                   temperature=temperature)

    print("[MOCK] LLM 비전 호출: (이미지 1장)")
    return {"text": "[MOCK] 일반 응답"}


def _call_openai_web_search(query: str, *, model: str) -> dict:
    client = _get_client()
    response = client.responses.create(model=model or LLM_MODEL, tools=[{"type": "web_search"}], input=query)
    source_url = None
    for item in response.output:
        if item.type != "message":
            continue
        for content in item.content:
            for annotation in getattr(content, "annotations", None) or []:
                if annotation.type == "url_citation":
                    source_url = annotation.url
                    break
            if source_url:
                break
        if source_url:
            break
    return {"text": response.output_text or "", "source_url": source_url}


def call_web_search(query: str, *, model: str = LLM_MODEL) -> dict:
    """웹 검색 1회 — DB 미보유 부품 실시간 스펙 검색(docs/미보유부품_실시간스펙검색_설계.md §3)
    전용. OpenAI Responses API의 내장 web_search 도구를 쓴다 — call_llm/call_llm_vision이 쓰는
    chat.completions과는 다른 엔드포인트라 별도 함수로 둔다.

    Returns:
        {"text": 검색 결과 요약 텍스트, "source_url": 첫 인용 출처 URL(없으면 None)}.
        "text"는 검증(critique) 단계의 입력일 뿐, 그대로 사용자에게 보여주지 않는다 — 모델이
        검색 결과를 요약하면서 지어낸 문장이 섞여 있을 수 있어, 그 지어낸 부분까지 추출되지
        않게 걸러내는 게 critique 단계의 역할이다(live_spec_lookup_system).
    """
    if not MOCK_MODE:
        return _call_openai_web_search(query, model=model)

    print(f"[MOCK] 웹 검색 호출: {query[:36]}...")
    return {"text": "[MOCK] 검색 결과 없음", "source_url": None}
