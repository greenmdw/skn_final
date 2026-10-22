"""사용자에게 보이는 말 — 금액(원) 표시와 조사."""
from __future__ import annotations


def fmt_money(krw: int | float | None, signed: bool = False) -> str:
    """저장 금액(원)을 표시 문자열로. signed 면 부호(+/-)를 붙인다."""
    if krw is None:
        return "-"
    n = int(krw)
    return f"{n:+,}원" if signed else f"{n:,}원"


# 영문·숫자로 끝나는 말의 받침. 약어(대문자)·숫자는 글자 이름으로 읽고(AMD → 디, RAM → 엠, 3050 → 영),
# 일반 단어는 표기 관례로 읽는다(Seasonic → 시소닉, Corsair → 커세어, Zalman → 잘만, Deepcool → 딥쿨).
_LETTER_BATCHIM, _LETTER_RIEUL = set("LMNR"), set("LR")            # 엘·엠·엔·알
_DIGIT_BATCHIM, _DIGIT_RIEUL = set("013678"), set("178")           # 영·일·삼·육·칠·팔


def _latin_batchim(token: str) -> tuple[bool, bool]:
    last = token[-1]
    if last.isdigit():
        return last in _DIGIT_BATCHIM, last in _DIGIT_RIEUL
    low = token.lower()
    # 모음이 없는 대문자(NZXT·HDR·SSD·RTX)·한 글자·"7600X"처럼 숫자 뒤 글자는 글자 이름으로 읽는다. 모음이 있으면
    # 대문자여도 단어로 읽는다(ARCTIC → 아크틱, CORSAIR → 커세어, RAM → 램, CPU → 씨피유).
    if len(token) == 1 or not token[-2:].isalpha() or (token.isupper() and not set(low) & set("aeiou")):
        return last.upper() in _LETTER_BATCHIM, last.upper() in _LETTER_RIEUL
    if low.endswith("ng") or low[-1] in "mn":
        return True, False
    if low[-1] == "l":
        return True, True
    if low[-1] in "ck" and not low.endswith("ch"):                      # -ic·-ec·-ck → ㄱ (…닉·…텍), -ch 는 …치·…크
        return True, False
    if low.endswith("up"):                                              # -up → 업 (Group → 그룹)
        return True, False
    return False, False


def _batchim(word: str) -> tuple[bool, bool]:
    """(받침 있음, 그 받침이 ㄹ). 괄호·따옴표·공백·느낌표 같은 끝 기호는 건너뛴다."""
    stripped = word.strip()
    i = len(stripped)
    while i and not stripped[i - 1].isalnum():
        i -= 1
    if not i:
        return False, False
    ch = stripped[i - 1]
    if "가" <= ch <= "힣":
        final = (ord(ch) - 0xAC00) % 28
        return final != 0, final == 8
    j = i
    while j and stripped[j - 1].isalnum() and not ("가" <= stripped[j - 1] <= "힣"):
        j -= 1
    return _latin_batchim(stripped[j:i])


def josa(word: str, pair: str) -> str:
    """word 뒤에 받침에 맞는 조사를 붙인다. pair 는 "받침 있을 때/없을 때": "을/를"·"은/는"·"이/가"·"과/와"·"으로/로".
    "으로/로"는 ㄹ 받침에도 "로"다(서울로). 브랜드·모델명처럼 영문·숫자로 끝나면 읽는 소리로 판단한다
    (RTX 3050 → 영 → 으로, SUPER → 알 → 로, NVIDIA → 에이 → 를). "을(를)"처럼 괄호로 둘 다 쓰지 않는다."""
    with_batchim, without = pair.split("/")
    has, rieul = _batchim(word)
    if with_batchim == "으로":
        return word + ("으로" if has and not rieul else "로")
    return word + (with_batchim if has else without)
