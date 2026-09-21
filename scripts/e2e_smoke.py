"""PC 추천 파이프라인 점검 — 조건 대화 → 추천 → 결과 → 대안·교체 → 결과 대화 → 가입 → 확정 → 리포트를 HTTP 로 끝까지.

신규 조립(build) · 업그레이드(upgrade) · 경계 상황(edge)을 각각 돌려 단계별 PASS/FAIL 과 소요 시간을 표로 낸다.
"큰 파이프라인이 끊기지 않고 이어지는가"를 1~2초에 확인하는 용도이고, tests/test_pipeline_http_smoke.py 가 같은 함수를 부른다.

사용 (준비된 일회용 DB 필요 — db/README.md 의 "테스트용 일회용 DB" 참고):
    TEST_DATABASE_URL=postgresql://truefit:truefit@localhost:5432/truefit_test python scripts/e2e_smoke.py
    python scripts/e2e_smoke.py --flows build,edge        # 일부만

DB 이름에 "test" 가 없으면 실행을 거부한다(익명 세션·추천 기록·계정이 쌓이므로). 의도한 것이면 TRUEFIT_ALLOW_ANY_DB=1.
외부 호출은 MOCK_MODE=1(기본)이라 LLM 은 가짜다 — 실호출 검증은 별도로 해야 한다.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALL_SLOTS = {"CPU", "GPU", "RAM", "메인보드", "저장장치", "파워", "케이스", "쿨러"}
FLOWS = ("build", "upgrade", "edge")


@dataclass
class Step:
    flow: str
    label: str
    ok: bool
    seconds: float
    note: str = ""


class Runner:
    """한 흐름(=한 사용자 세션)의 단계를 실행하고 결과를 모은다."""

    def __init__(self, flow: str, steps: list[Step]):
        from fastapi.testclient import TestClient
        from src.api import app

        self.flow, self.steps, self.app = flow, steps, app
        self.c = TestClient(app)
        self.lid: str | None = None
        self.result: dict | None = None
        self.item: dict | None = None
        self.alt: dict | None = None

    def step(self, label: str, fn) -> bool:
        started = time.time()
        try:
            note = str(fn() or "")[:90]
            self.steps.append(Step(self.flow, label, True, time.time() - started, note))
            return True
        except AssertionError as exc:
            self.steps.append(Step(self.flow, label, False, time.time() - started, f"AssertionError: {str(exc)[:80]}"))
        except Exception as exc:  # noqa: BLE001 — 점검 도구라 어떤 오류든 단계 실패로 기록한다
            self.steps.append(Step(self.flow, label, False, time.time() - started, f"{type(exc).__name__}: {str(exc)[:80]}"))
        return False

    def ok(self, response, code: int = 200):
        assert response.status_code == code, (
            f"{response.request.method} {response.request.url.path} -> {response.status_code} {response.text[:120]}")
        return response.json() if response.content else None

    # ── 공통 단계 ──────────────────────────────────────────────────────────
    def start(self, mode: str) -> None:
        def create():
            self.lid = self.ok(self.c.post("/session"))["list_id"]
            return self.lid[:8]
        self.step("세션 생성", create)
        self.step(f"카테고리 선택(computer/{mode})", lambda: self.ok(
            self.c.post(f"/session/{self.lid}/category", json={"category": "computer", "mode": mode})) and mode)

    def conditions(self, **values) -> None:
        def go():
            for key, value in values.items():
                self.ok(self.c.patch(f"/session/{self.lid}/slot", json={"field": key, "value": value}))
            state = self.ok(self.c.get(f"/session/{self.lid}"))
            return f"can_recommend={state['can_recommend']} next={(state.get('next_question') or {}).get('id')}"
        self.step("조건 입력", go)

    def answer_questions(self, choice: str = "unknown") -> None:
        def go():
            answered = []
            for _ in range(5):
                nq = self.ok(self.c.get(f"/session/{self.lid}")).get("next_question")
                if not nq:
                    break
                self.ok(self.c.post(f"/session/{self.lid}/answer", json={"question_id": nq["id"], "selected": [choice]}))
                answered.append(nq["id"])
            assert self.ok(self.c.get(f"/session/{self.lid}"))["can_recommend"], "질문에 답했는데도 추천 불가"
            return "답변: " + ",".join(answered) if answered else "질문 없음"
        self.step("대화 질문 응답", go)

    def recommend(self, expect_slots: set[str] | None = None) -> None:
        def rec():
            response = self.c.post(f"/session/{self.lid}/recommend", json={})
            assert response.status_code == 202, f"{response.status_code} {response.text[:120]}"
            return response.json()["status"]
        self.step("추천 실행(202)", rec)

        def res():
            self.result = self.ok(self.c.get(f"/session/{self.lid}/result"))
            slots = {i["slot"] for i in self.result["items"]}
            if expect_slots is not None:
                assert slots == expect_slots, f"슬롯 {sorted(slots)}"
            return f"status={self.result['status']} 부품 {len(slots)}개 합계 {self.result['totals']['selected_price']:,}원"
        self.step("결과 조회", res)

        def content():
            d = self.result
            assert d["items"] and all(i["price"] > 0 and i["product"]["name"] for i in d["items"]), "부품 정보 비어 있음"
            assert (d.get("explanation") or {}).get("text"), "요약 문장 없음"
            checks = sum(1 for i in d["items"] if (i.get("checks") or {}).get("text"))
            return f"요약 {len(d['explanation']['text'])}자, 구매 전 확인 문구 {checks}/{len(d['items'])}개 품목"
        self.step("결과 내용(부품·가격·요약)", content)

    def alternatives_and_swap(self, slot: str) -> None:
        def alts():
            self.item = next(i for i in self.result["items"] if i["slot"] == slot)
            data = self.ok(self.c.get(f"/session/{self.lid}/items/{self.item['item_id']}/alternatives"))
            assert data["items"], "대안 없음"
            self.alt = data["items"][0]
            return f"{slot} 대안 {len(data['items'])}개"
        self.step(f"대안 목록({slot})", alts)

        def swap():
            data = self.ok(self.c.post(f"/session/{self.lid}/items/{self.item['item_id']}/swap",
                                       json={"candidate_id": self.alt["candidate_id"]}))
            new = next(i for i in data["items"] if i["item_id"] == self.item["item_id"])
            assert new["product"]["variant_id"] == self.alt["candidate_id"], "교체가 반영 안 됨"
            self.result = data
            return "교체 반영"
        self.step("후보 교체", swap)

        def patch():
            data = self.ok(self.c.patch(f"/session/{self.lid}/items/{self.item['item_id']}", json={"qty": 1, "timing": "soon"}))
            return f"timing={next(i for i in data['items'] if i['item_id'] == self.item['item_id'])['timing']}"
        self.step("품목 수정(구매 시점)", patch)

    def chat(self, text: str = "그래픽카드를 더 저렴한 걸로 바꿔줘") -> None:
        self.step("결과 화면 대화", lambda: self.ok(self.c.post(f"/session/{self.lid}/result-message", json={"text": text}))["reply"][:60])

    def signup(self, tag: str) -> None:
        def go():
            email = f"smoke_{tag}_{uuid.uuid4().hex[:8]}@example.com"
            self.ok(self.c.post("/auth/signup", json={"email": email, "password": "Passw0rd!pass", "display_name": "smoke",
                                                      "terms_agreed": True, "privacy_agreed": True}), 201)
            return email
        self.step("회원가입(게스트 병합)", go)

    def confirm_and_report(self) -> None:
        def conf():
            data = self.ok(self.c.post(f"/lists/{self.lid}/confirm", json={
                "name": "스모크 리스트", "planned_purchase_at": "2026-10-30", "target_amount": 2_000_000, "memo": "e2e"}))
            return f"확정 name={data.get('name')}"
        self.step("리스트 확정", conf)

        def rep():
            data = self.ok(self.c.get(f"/lists/{self.lid}/report"))
            assert data.get("items") or data.get("lines"), "리포트에 품목 없음"
            return "리포트 조회"
        self.step("리포트 조회", rep)


def _flow_build(steps: list[Step]) -> None:
    r = Runner("A 신규 조립", steps)
    r.start("build")
    r.conditions(purpose="game", budget_max=1_500_000, priority="value")
    r.recommend(expect_slots=ALL_SLOTS)
    r.alternatives_and_swap("CPU")
    r.chat()
    r.signup("a")
    r.confirm_and_report()


def _flow_upgrade(steps: list[Step]) -> None:
    r = Runner("B 업그레이드", steps)
    r.start("upgrade")
    r.conditions(purpose="game", budget_max=800_000, priority="value", upgrade_parts=["GPU"])
    r.answer_questions()
    r.recommend(expect_slots={"GPU"})
    r.alternatives_and_swap("GPU")
    r.signup("b")
    r.confirm_and_report()


def _flow_edge(steps: list[Step]) -> None:
    from fastapi.testclient import TestClient

    r = Runner("C 경계 상황", steps)
    r.start("build")

    def early_recommend():
        resp = r.c.post(f"/session/{r.lid}/recommend", json={})
        assert resp.status_code in (400, 409, 422), f"조건 미충족인데 {resp.status_code}"
        return f"{resp.status_code} {resp.json().get('error', {}).get('code')}"
    r.step("조건 미충족 추천 거절", early_recommend)

    def early_result():
        assert r.c.get(f"/session/{r.lid}/result").status_code == 404
        return "404"
    r.step("추천 전 결과 조회 404", early_result)

    r.conditions(purpose="game", budget_max=400_000, priority="value")      # 하드 조건상 불가능한 예산
    r.recommend()

    def over_budget_flagged():
        assert r.result["totals"].get("over_budget") is True, "예산 초과 표시가 없음"
        return f"합계 {r.result['totals']['selected_price']:,} (예산 40만) over_budget=True"
    r.step("불가능한 예산은 초과로 표시", over_budget_flagged)

    r.signup("c")

    def over_budget_confirm():
        resp = r.c.post(f"/lists/{r.lid}/confirm", json={"name": "초과 리스트"})
        assert resp.status_code in (400, 409, 422), f"예산 초과인데 확정 {resp.status_code}"
        return f"{resp.status_code} {resp.json().get('error', {}).get('code')}"
    r.step("예산 초과 견적 확정 거절", over_budget_confirm)

    def deselect_all_confirm():
        for item in r.result["items"]:
            r.ok(r.c.patch(f"/session/{r.lid}/items/{item['item_id']}", json={"selected": False}))
        resp = r.c.post(f"/lists/{r.lid}/confirm", json={"name": "빈 리스트"})
        assert resp.status_code in (400, 409, 422), f"선택 0개인데 확정 {resp.status_code}"
        return f"{resp.status_code} {resp.json().get('error', {}).get('code')}"
    r.step("선택 0개 확정 거절", deselect_all_confirm)

    def foreign_access():
        resp = TestClient(r.app).get(f"/session/{r.lid}")
        assert resp.status_code in (401, 403, 404), f"남의 세션 접근 {resp.status_code}"
        return str(resp.status_code)
    r.step("다른 사용자 접근 차단", foreign_access)


_RUNNERS = {"build": _flow_build, "upgrade": _flow_upgrade, "edge": _flow_edge}


def assert_disposable_db() -> str:
    """이름에 test 가 없는 DB 로는 돌리지 않는다."""
    from src.config import DATABASE_URL
    from psycopg.conninfo import conninfo_to_dict

    name = conninfo_to_dict(DATABASE_URL).get("dbname") or ""
    if "test" not in name.lower() and os.environ.get("TRUEFIT_ALLOW_ANY_DB") != "1":
        raise SystemExit(f"'{name}' 는 일회용 테스트 DB 가 아니라 실행하지 않습니다(계정·세션이 쌓입니다). "
                         "TEST_DATABASE_URL 을 지정하거나 TRUEFIT_ALLOW_ANY_DB=1 을 설정하세요.")
    return name


def run_smoke(flows: tuple[str, ...] = FLOWS) -> list[Step]:
    steps: list[Step] = []
    for flow in flows:
        _RUNNERS[flow](steps)
    return steps


def format_report(steps: list[Step]) -> str:
    lines = [f"{'흐름':<12}{'단계':<28}{'결과':<5}{'초':>6}  비고", "-" * 100]
    current = None
    for s in steps:
        if s.flow != current:
            current = s.flow
            if len(lines) > 2:
                lines.append("-" * 100)
        lines.append(f"{s.flow:<12}{s.label:<28}{'PASS' if s.ok else 'FAIL':<5}{s.seconds:>6.2f}  {s.note}")
    passed = sum(1 for s in steps if s.ok)
    lines += ["-" * 100, f"합계: {passed}/{len(steps)} 단계 통과, 총 {sum(s.seconds for s in steps):.1f}초"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--flows", default=",".join(FLOWS), help="build,upgrade,edge 중 쉼표로")
    args = parser.parse_args(argv)
    flows = tuple(f.strip() for f in args.flows.split(",") if f.strip())
    unknown = [f for f in flows if f not in _RUNNERS]
    if unknown:
        parser.error(f"알 수 없는 흐름: {unknown}")

    os.environ.setdefault("MOCK_MODE", "1")
    os.environ.setdefault("PGCONNECT_TIMEOUT", "3")
    if os.environ.get("TEST_DATABASE_URL"):
        os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    sys.path.insert(0, str(ROOT))
    db = assert_disposable_db()
    print(f"DB: {db}  ·  MOCK_MODE={os.environ['MOCK_MODE']}\n")
    steps = run_smoke(flows)
    print(format_report(steps))
    return 0 if all(s.ok for s in steps) else 1


if __name__ == "__main__":
    sys.exit(main())
