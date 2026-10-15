"""이어가기 제안에 글로 답한 말 판정(web/src/state/offerReply.ts) — 10/15 QA #65.

웹에는 테스트 도구가 없어 node 의 타입 제거 실행(22.18+)으로 함수를 직접 부른다. node 가 없으면 건너뛴다."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[1] / "web/src/state/offerReply.ts"
CASES = [
    # 말, 제안이 마지막 질문인지, 기대
    ("이어서 해줘", True, "resume"), ("지난 견적 이어서 할게요", False, "resume"), ("그대로 진행해 주세요", True, "resume"),
    ("응", True, "resume"), ("네!", True, "resume"),
    ("응", False, None),                                  # 뒤에 선호 되묻기가 있으면 "응"은 어느 질문의 답인지 모른다
    ("새로 시작할게요", True, "fresh"), ("처음부터 할래", False, "fresh"), ("이어서 하지 말고", True, "fresh"),
    ("아니요", True, "fresh"), ("아니요", False, None),
    ("게임용 PC 맞추고 싶어요", True, None),
    ("이어서 하되 예산은 200만원으로 올려 주세요", True, None),   # 조건이 섞인 긴 문장은 조건 대화로
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node 필요")
def test_offer_reply_reading():
    script = (f"import {{ readOfferReply }} from {json.dumps(MODULE.as_uri())};"
              f"const cases = {json.dumps([[t, o] for t, o, _ in CASES], ensure_ascii=False)};"
              "console.log(JSON.stringify(cases.map(([t, o]) => readOfferReply(t, o))));")
    out = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", script],
                         capture_output=True, text=True, check=True).stdout
    got = json.loads(out)
    assert list(zip([c[0] for c in CASES], got)) == [(t, e) for t, _, e in CASES]
