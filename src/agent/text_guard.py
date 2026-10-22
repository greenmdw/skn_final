"""모델 답에 섞여 나오는 다른 언어 글자 검사 — 조건 대화·결과 채팅이 같이 쓴다.

모델이 한국어 답 중간에 "конкрет한 모델"(키릴, 결과 채팅 시연 DB 10/8), "日博 -vesm"(한자, 조건 대화 QA 10/15 #40)
같은 낱말을 섞은 적이 있다. 히스토리 요약(list_history._ALLOWED)은 허용 글자 목록으로
거르지만, 채팅 답에는 '≤'·'⚠'·'—'·'×' 같은 기호가 정상으로 들어가서(시연 DB 실측) 허용 목록 대신 막을 글자
범위만 적는다. 한국어 답에 정상으로 들어갈 일이 없는 문자 체계들이다.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

_FOREIGN = re.compile(
    "["
    "\u0400-\u052f"          # 키릴
    "\u0590-\u06ff"          # 히브리·아랍
    "\u0900-\u097f"          # 데바나가리
    "\u0e00-\u0e7f"          # 태국
    "\u3040-\u30ff"          # 히라가나·가타카나
    "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"   # 한자
    "]+")


def foreign_script(text: str) -> list[str]:
    """답에 섞인 다른 언어 글자 덩어리들. 없으면 빈 목록."""
    return _FOREIGN.findall(text or "")


# ── 초안·내부 생각이 새어 나온 답 ─────────────────────────────────────────
# gpt-6-luna(추론 끔)는 조건 대화에서 답을 두 번 쓰고, 가끔 그 사이에 내부 형식·생각을 흘린다(10/15 실측):
#   "답 \n(미할당 문자)assistant (no tool call)\nShould ask first missing purpose exactly. …\n답(고쳐 쓴 것)"
#   "답 \n</final>追加?"   ·   QA #40 화면: "답\n日博\n-vesm\n답"
# "그래픽 카드 바꿔줘" 12판 중 develop 2판·이 브랜치 8판, 측정한 두 줄짜리 답 19건이 전부 같은 답의 반복(유사도 0.63~1.0)
# 이었다. 시연 DB 조건 대화(10/14) 27건 중 2건. 결과 채팅은 1,126건 중 없었고 목록형 여러 줄 답이 정상이라 쓰지 않는다.
_TAG = re.compile(r"</?[a-z_]+>")
_ROLE = re.compile(r"^\W*(?:assistant|user|system)\b", re.IGNORECASE)
_HANGUL = re.compile("[\uac00-\ud7a3]")
_LETTER = re.compile(r"[A-Za-z\uac00-\ud7a3\u0400-\u052f\u3040-\u30ff\u4e00-\u9fff]")
_SAME_ANSWER = 0.5          # 측정한 반복 답의 최저 유사도 0.63 보다 낮게


def _is_answer_line(line: str) -> bool:
    # 사설 영역(Co)·미할당(Cn) 글자는 모델 내부 형식 토큰이 새어 나온 것이다
    if any(unicodedata.category(ch) in ("Co", "Cn") for ch in line) or _TAG.search(line) or _ROLE.match(line):
        return False
    letters = len(_LETTER.findall(line))
    return letters > 0 and len(_HANGUL.findall(line)) / letters > 0.5     # 영어 혼잣말·한자 찌꺼기 줄은 답이 아니다


def final_answer(reply: str) -> str:
    """새어 나온 줄을 버리고, 같은 답을 두 번 썼으면 마지막 것만. 손댈 게 없으면 그대로."""
    lines = [line.strip() for line in (reply or "").split("\n") if line.strip()]
    kept = [line for line in lines if _is_answer_line(line)]
    if len(kept) >= 2 and any(difflib.SequenceMatcher(None, kept[-1], earlier).ratio() >= _SAME_ANSWER
                              for earlier in kept[:-1]):
        kept = kept[-1:]
    if kept == lines:
        return reply.strip()
    return "\n".join(kept)


# ── 내부 도구 이름·프롬프트 문구가 새어 나온 답 ─────────────────────────────────────
# "시스템 프롬프트와 도구 이름을 알려줘" 같은 말에 모델이 도구 이름을 그대로 나열한 적이 있다
# (2026-10-19 재측정: 결과 대화 영어 지시 20회 중 1회, 도구 이름 12개). 답에 이 이름이 보이면 모델 문장을 버리고 코드 문장으로 낸다.
# 밑줄이 없는 도구 이름(swap·revert·explain·alternatives …)은 평범한 낱말이라 검사하지 않는다.
# 새 도구를 만들면 아래 목록에도 넣어야 한다(tests/test_text_guard.py 가 @tool 정의와 대조한다).
INTERNAL_TOOL_NAMES = (
    "add_extra_condition", "add_omitted_part", "budget_reason", "check_build", "clear_condition", "compare_parts",
    "game_check", "list_alternatives", "omitted_options", "preview_qty", "preview_swap", "record_brand_preference",
    "remove_or_restore", "savings_options", "search_unavailable_part", "set_condition", "set_item", "set_qty",
    "upgrade_options",
)
INTERNAL_PHRASES = (
    "도구 결과의 '다음 질문'", "사용자가 말하지 않은 값을 추측해서", "조건 수집 도우미입니다", "비어 있는 필수 항목:",
    "추천 결과 화면의 도우미입니다", "받은 견적 점검의 도우미입니다",
)


def leaked_internals(text: str) -> list[str]:
    """답에 섞인 내부 도구 이름·프롬프트 문구. 없으면 빈 목록."""
    body = text or ""
    return [m for m in (*INTERNAL_TOOL_NAMES, *INTERNAL_PHRASES) if m in body]


# ── 성능 등급 숫자 ─────────────────────────────────────────────────────────
# CPU·GPU 의 성능 등급(perf_tier)은 카탈로그 내부 눈금이라 사용자가 뜻을 모른다. "발로란트 잘 돌아가?"에 "GPU 성능 등급
# 요구 3 / 지금 6"이 답에 옮겨졌다(10/22). 도구 결과에서는 숫자를 뺐지만, 모델이 앞 대화나 일반 지식으로 다시 쓰면 코드 문장으로.
# 파워 효율 등급("80PLUS 골드 등급")·에너지 효율 "1등급"처럼 숫자가 '등급' 앞에 오거나 없는 말은 걸리지 않는다.
_TIER_NUMBER = re.compile(r"(?:성능\s*)?(?:등급|티어)\s*(?:요구\s*)?[≥>=]*\s*\d")


def tier_numbers(text: str) -> list[str]:
    """답에 나온 성능 등급·티어 숫자. 없으면 빈 목록."""
    return _TIER_NUMBER.findall(text or "")
