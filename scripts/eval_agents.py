"""조건 대화·결과 대화·견적 점검 질문 에이전트의 도구 호출 반복 검증 — 전체_테스트_시나리오_실행_기획.md §4(2번, 최소 3회).

실제 서버(기본 http://127.0.0.1:8000, MOCK_MODE=0)에 HTTP 로 요청해 에이전트가 매번 도구를 불러 결과를 바꾸는지(조건 반영·구성표 변경)
또는 에이전트 경로로 답하는지(via=agent, 근거 있음)를 코드로 판정한다. 비용이 든다(대화 9회 + 추천 3회).
  PYTHONPATH=. python scripts/eval_agents.py --out outputs/<파일>.json"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Api:
    def __init__(self, base: str):
        self.base = base
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def post_form(self, path, fields):
        """폼(urlencoded) 요청 — 받은 견적 점검 초안 만들기는 JSON 이 아니라 폼으로 받는다."""
        req = urllib.request.Request(self.base + path, method="POST", data=urllib.parse.urlencode(fields).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with self.op.open(req, timeout=300) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw or b"null")
            except ValueError:
                return e.code, {"raw": raw[:200].decode("utf-8", "replace")}

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.op.open(req, timeout=300) as r:
                text = r.read()
                return r.status, (json.loads(text) if text else None)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw or b"null")
            except ValueError:
                return e.code, {"raw": raw[:200].decode("utf-8", "replace")}


def fields(state: dict) -> dict:
    return {f["key"]: f["value"] for f in state.get("fields", [])}


CONDITION_CASES = [
    ("게임용 PC 예산 150만원 성능 우선이에요", {"purpose": "game", "budget_max": 1_500_000, "priority": "performance"}),
    ("사무용으로 쓸 거고 100만원 정도, 조용했으면 좋겠어요", {"purpose": "office", "budget_max": 1_000_000, "priority": "quiet"}),
    ("롤이랑 발로란트 할 거예요. 예산 200만원에 가성비 좋게요", {"purpose": "game", "budget_max": 2_000_000, "priority": "value"}),
]
RESULT_CASES = [("쿨러를 더 저렴한 걸로 바꿔줘", "쿨러"), ("그래픽카드를 한 단계 더 좋은 걸로 바꿔줘", "GPU"), ("저장장치를 더 저렴한 걸로 바꿔줘", "저장장치")]
QUOTE_CASES = ["호환은 문제 없어?", "가격 비교 알려줘", "그래픽카드 더 저렴한 대안 뭐가 있어?"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--out", default=str(ROOT / "outputs" / "agents_eval.json"))
    args = parser.parse_args()
    api = Api(args.base)
    s, _ = api.call("POST", "/auth/signup", {"email": f"agt-{uuid.uuid4().hex[:10]}@example.test", "password": "Aa1!" + uuid.uuid4().hex[:8],
                                             "display_name": "agt", "terms_agreed": True, "privacy_agreed": True})
    assert s == 201
    report = {"conditions": [], "result": [], "quote": []}
    started = time.time()
    for text, expect in CONDITION_CASES:
        _, sess = api.call("POST", "/session", {})
        lid = sess["list_id"]
        api.call("POST", f"/session/{lid}/category", {"category": "computer", "mode": "build"})
        s, state = api.call("POST", f"/session/{lid}/message", {"text": text})
        got = fields(state) if s == 200 else {}
        report["conditions"].append({"input": text, "status": s, "expected": expect, "got": {k: got.get(k) for k in expect},
                                     "games": got.get("games"), "ok": s == 200 and all(got.get(k) == v for k, v in expect.items()),
                                     "reply": (state.get("messages") or [{}])[-1].get("text") if s == 200 else None})
    for text, slot in RESULT_CASES:
        _, sess = api.call("POST", "/session", {})
        lid = sess["list_id"]
        api.call("POST", f"/session/{lid}/category", {"category": "computer", "mode": "build"})
        for qid, value in (("q_purpose", "게임"), ("q_budget_max", 2_000_000), ("q_priority", "성능 우선")):
            api.call("POST", f"/session/{lid}/answer", {"question_id": qid, "selected": [value]})
        api.call("POST", f"/session/{lid}/recommend", {})
        for _ in range(60):
            time.sleep(3)
            s, before = api.call("GET", f"/session/{lid}/result")
            if before.get("status") in ("done", "failed"):
                break
        pick = lambda r: {i["slot"]: i["product"]["name"] for i in r["items"]}      # noqa: E731
        s, r = api.call("POST", f"/session/{lid}/result-message", {"text": text})
        s2, after = api.call("GET", f"/session/{lid}/result")
        changed = [k for k, v in pick(before).items() if pick(after).get(k) != v]
        report["result"].append({"input": text, "status": s, "slot": slot, "changed_slots": changed, "ok": s == 200 and slot in changed,
                                 "reply": (r or {}).get("reply") if s == 200 else None})
    # 재설계한 받은 견적 점검: 초안 만들기(인식) → 분석(용도 필수) → 대화. 대화는 초안 id 로 건다
    s, rv = api.post_form("/pc/review-drafts", {
        "text": "CPU: AMD Ryzen 5 7500F 238,000원\nGPU: AMD Radeon RX 7600 438,000원\n메인보드: MSI B650 TOMAHAWK 250,000원\n파워: Seasonic FOCUS GX-750 140,000원",
        "conditions": json.dumps({"purpose": "game", "resolution": "QHD_165"})})
    rid = rv["draft_id"]
    api.call("POST", f"/pc/review-drafts/{rid}/analysis", {})
    for text in QUOTE_CASES:
        s, r = api.call("POST", f"/pc/reviews/{rid}/messages", {"text": text})
        report["quote"].append({"input": text, "status": s, "via": (r or {}).get("via"), "evidence": (r or {}).get("evidence"),
                                "ok": s == 200 and (r or {}).get("via") == "agent" and bool((r or {}).get("evidence")),
                                "reply": ((r or {}).get("reply") or "")[:200]})
    report["seconds"] = round(time.time() - started)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for k in ("conditions", "result", "quote"):
        print(k, f"{sum(x['ok'] for x in report[k])}/{len(report[k])}")
    print("saved", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
