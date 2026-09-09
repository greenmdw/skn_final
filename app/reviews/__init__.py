"""
리뷰 소스 고르기 — `REVIEW_SOURCE`.

이 파일이 없던 동안 `REVIEW_SOURCE` 는 **문서에만 있었다.** `synthetic.py` 의
docstring 과 `docs/추천엔진_API계약.md` 가 그런 환경변수가 있다고 적어 놨는데
읽는 코드가 없어서, 소스를 바꾸려면 `packs/pc.py` 의 `review_source()` 를 손으로
고쳐야 했다. 문서가 거짓이었다.

새 소스를 붙이는 자리는 여기 하나다. `ReviewSource`(`base.py`)를 만족하는 클래스를
`app/reviews/` 에 두고 아래 `_SOURCES` 에 이름을 등록하면 된다.
"""

from __future__ import annotations

import os

REVIEW_SOURCE = os.environ.get("REVIEW_SOURCE", "synthetic").lower()


def build_source(pack):
    """
    이 요청에 쓸 리뷰 소스.

    `synthetic` 은 팩이 만들어 준다 — 합성 라벨이 그 도메인의 주장에 붙어 있어서
    팩 밖에서는 만들 수 없다. 실데이터 소스는 팩과 무관하므로 여기서 만든다.
    """
    if REVIEW_SOURCE == "synthetic":
        return pack.review_source()
    raise RuntimeError(
        f"모르는 리뷰 소스입니다: {REVIEW_SOURCE!r}. "
        f"쓸 수 있는 것: 'synthetic'. 새로 붙이려면 app/reviews/ 에 "
        f"ReviewSource(base.py) 구현을 두고 app/reviews/__init__.py 에 등록하세요."
    )
