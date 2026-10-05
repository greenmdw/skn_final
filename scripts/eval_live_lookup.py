#!/usr/bin/env python3
"""미보유 부품 실시간 검색 평가 — 멘토링(2026-10-03) 요청: "없는 부품, 잘 되는 부품, 낯선 제조사 약 30건".

실제 웹 검색 + 실제 LLM 검증을 돌려 다음을 잰다(비용 발생 — 사례당 검색 1회 + LLM 1회).
  1. 환각 방지   존재하지 않는 부품 10건 → "못 찾음"이어야 한다. 값이 나오면 환각(오탐)이다.
  2. 정확도     실제 부품 12건(정답 확신 있음) → 돌려준 필드가 정답과 맞는지. 틀린 값(오답)을 따로 센다.
  3. 낯선 제조사  실제 부품 8건(정답 미확정) → 자동 채점하지 않는다. 결과와 출처를 사람이 확인하도록 낸다.
  4. 정규화 적중  각 사례를 가격·괄호·수량·상품코드만 바꿔 다시 조회 → 저장소에서 나와야 한다(검색 호출 0).
  5. 참고가      카탈로그 부품 N건을 LIVE_REFERENCE_PRICE=1 로 조회 → 카탈로그 가격(다나와 수집분)과 비교.

개발 DB 를 더럽히지 않는다 — 사례마다 별도 커넥션에서 돌리고 마지막에 롤백한다(저장소 행이 남지 않는다).

    DATABASE_URL=postgresql://truefit:truefit@127.0.0.1:5432/truefit PYTHONIOENCODING=utf-8 \\
      python scripts/eval_live_lookup.py --workers 6 --out outputs/live_lookup_eval.json
"""
from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from src.errors import ServiceUnavailable  # noqa: E402
from src.services import live_spec_lookup as lsl  # noqa: E402

# 정답은 제조사 공개 사양으로 확신하는 값만 적는다. 값이 리스트면 허용 후보(용량의 1000/1024 등).
CASES: list[dict] = [
    # ── 1. 존재하지 않는 부품 (정답: 못 찾음) ──────────────────────────────────────────────
    {"id": "F01", "group": "fabricated", "slot": "RAM", "name": "삼성전자 DDR5-9999 64GB"},
    {"id": "F02", "group": "fabricated", "slot": "파워", "name": "Corsair RM1999x 1999W"},
    {"id": "F03", "group": "fabricated", "slot": "쿨러", "name": "Noctua NH-Z99 Ultra"},
    {"id": "F04", "group": "fabricated", "slot": "메인보드", "name": "ASUS ROG STRIX Z999-E GAMING"},
    {"id": "F05", "group": "fabricated", "slot": "파워", "name": "Seasonic PRIME TX-2200"},
    {"id": "F06", "group": "fabricated", "slot": "RAM", "name": "Kingston FURY Beast DDR6-8800 32GB"},
    {"id": "F07", "group": "fabricated", "slot": "저장장치", "name": "WD Black SN999 2TB"},
    {"id": "F08", "group": "fabricated", "slot": "CPU", "name": "Intel Core i9-19900K"},
    {"id": "F09", "group": "fabricated", "slot": "CPU", "name": "AMD Ryzen 9 9999X3D"},
    {"id": "F10", "group": "fabricated", "slot": "쿨러", "name": "모름브랜드 쿨러 Z1"},
    # ── 2. 잘 되어야 하는 실제 부품 (정답 확신) ─────────────────────────────────────────────
    {"id": "R01", "group": "real", "slot": "쿨러", "name": "be quiet! Dark Rock Pro 5",
     "expect": {"cooling_type": "Air", "height_mm": 168}},
    {"id": "R02", "group": "real", "slot": "쿨러", "name": "Noctua NH-U12A",
     "expect": {"cooling_type": "Air", "height_mm": 158}},
    {"id": "R03", "group": "real", "slot": "쿨러", "name": "Noctua NH-D15",
     "expect": {"cooling_type": "Air", "height_mm": 168}},
    {"id": "R04", "group": "real", "slot": "쿨러", "name": "Arctic Liquid Freezer II 360",
     "expect": {"cooling_type": "Liquid (AIO)", "radiator_mm": 360}},
    {"id": "R05", "group": "real", "slot": "파워", "name": "Corsair RM1000x",
     "expect": {"wattage_w": 1000}},
    {"id": "R06", "group": "real", "slot": "파워", "name": "Seasonic FOCUS GX-750",
     "expect": {"wattage_w": 750}},
    {"id": "R07", "group": "real", "slot": "RAM", "name": "Kingston FURY Beast DDR4 3200 16GB",
     "expect": {"mem_type": "DDR4", "speed_mts": 3200, "capacity_gb": 16}},
    {"id": "R08", "group": "real", "slot": "저장장치", "name": "Crucial P5 Plus 1TB",
     "expect": {"capacity_gb": [1000, 1024], "interface": "NVMe"}},
    {"id": "R09", "group": "real", "slot": "저장장치", "name": "Samsung 870 EVO 1TB",
     "expect": {"capacity_gb": [1000, 1024], "interface": "SATA"}},
    {"id": "R10", "group": "real", "slot": "메인보드", "name": "ASUS ROG STRIX B550-F GAMING",
     "expect": {"mem_type": "DDR4", "form_factor": "ATX"}},
    {"id": "R11", "group": "real", "slot": "메인보드", "name": "MSI MAG B660M MORTAR WIFI DDR4",
     "expect": {"mem_type": "DDR4", "form_factor": ["mATX", "Micro-ATX", "M-ATX", "Micro ATX"]}},
    {"id": "R12", "group": "real", "slot": "CPU", "name": "AMD Ryzen 5 5600X",
     "expect": {"socket": "AM4", "mem_type": "DDR4"}},
    # ── 3. 낯선 제조사의 실제 부품 (정답 미확정 — 사람이 출처로 확인) ─────────────────────────
    {"id": "O01", "group": "obscure", "slot": "쿨러", "name": "PCCOOLER RZ620"},
    {"id": "O02", "group": "obscure", "slot": "쿨러", "name": "ID-COOLING FROSTFLOW X 240"},
    {"id": "O03", "group": "obscure", "slot": "쿨러", "name": "Jonsbo CR-1000 EVO"},
    {"id": "O04", "group": "obscure", "slot": "파워", "name": "Montech Century II 850W"},
    {"id": "O05", "group": "obscure", "slot": "파워", "name": "darkFlash UPMOST 850W"},
    {"id": "O06", "group": "obscure", "slot": "케이스", "name": "darkFlash DLX22"},
    {"id": "O07", "group": "obscure", "slot": "케이스", "name": "Montech AIR 903 MAX"},
    {"id": "O08", "group": "obscure", "slot": "저장장치", "name": "Biwin NV7200 1TB"},
]

VARIANT_SUFFIX = " 99,000원 x2 12345678"          # 가격·수량·상품코드를 붙인 두 번째 조회용
RETRY_STATS = {"rate_limited": 0}                  # OpenAI 토큰 한도(429)로 기다린 횟수 — 운영 부하 참고용


def _lookup(conn, text: str, slot: str | None = None):
    """서비스는 429 에 한 번만 짧게 재시도하고 그래도 안 되면 ServiceUnavailable(busy)을 올린다. 평가 도구는
    그걸 받아 더 길게 기다렸다 다시 시도한다 — 한도에 걸려 사례가 빠지면 평가가 성립하지 않는다."""
    for attempt in range(6):
        try:
            return lsl.lookup_with_meta(conn, text, slot=slot)
        except ServiceUnavailable:
            RETRY_STATS["rate_limited"] += 1
            conn.rollback()
            time.sleep(15 * (attempt + 1))
    return lsl.lookup_with_meta(conn, text, slot=slot)


def _agree(want, got) -> bool:
    options = want if isinstance(want, list) else [want]
    for opt in options:
        if isinstance(opt, (int, float)):
            if isinstance(got, (int, float)) and not isinstance(got, bool) and abs(got - opt) <= max(1, opt * 0.01):
                return True
        else:
            norm = lambda x: str(x).lower().replace(" ", "").replace("-", "")      # noqa: E731
            if norm(opt) in norm(got):
                return True
    return False


def _fields(outcome) -> dict:
    return {k: v for k, v in outcome.result.supported_fields.model_dump().items() if v is not None}


def _run_case(dsn: str, case: dict) -> dict:
    try:
        return _run_case_inner(dsn, case)
    except Exception as exc:  # noqa: BLE001 — 사례 하나의 오류가 전체 평가를 멈추지 않게
        return {**case, "relevant": False, "fields": {}, "found": False, "first_cached": False,
                "second_cached": False, "second_same_result": False, "first_ms": 0, "second_ms": 0,
                "verdict": "오류", "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def _run_case_inner(dsn: str, case: dict) -> dict:
    conn = psycopg.connect(dsn)
    try:
        t0 = time.perf_counter()
        first = _lookup(conn, case["name"], case["slot"])
        first_ms = (time.perf_counter() - t0) * 1000
        t1 = time.perf_counter()
        second = _lookup(conn, case["name"] + VARIANT_SUFFIX, case["slot"])
        second_ms = (time.perf_counter() - t1) * 1000
        fields = _fields(first)
        record = {**case, "relevant": first.result.relevant, "fields": fields, "source_url": first.result.source_url,
                  "first_ms": round(first_ms), "first_cached": first.cached,
                  "second_cached": second.cached, "second_ms": round(second_ms),
                  "second_same_result": _fields(second) == fields and second.result.relevant == first.result.relevant}
        found = first.result.relevant and bool(fields)
        record["found"] = found
        if case["group"] == "fabricated":
            record["verdict"] = "환각(오탐)" if found else "정상(못 찾음)"
        elif case["group"] == "real":
            checks = {}
            for key, want in case["expect"].items():
                got = fields.get(key)
                checks[key] = {"want": want, "got": got,
                               "result": "없음" if got is None else ("정답" if _agree(want, got) else "오답")}
            record["checks"] = checks
            record["verdict"] = ("못 찾음" if not found else
                                 "오답 포함" if any(c["result"] == "오답" for c in checks.values()) else
                                 "정답" if all(c["result"] == "정답" for c in checks.values()) else "일부 누락")
        else:
            record["verdict"] = "사람 확인 필요" if found else "못 찾음"
        return record
    finally:
        conn.rollback()
        conn.close()


def _price_cases(dsn: str, count: int) -> list[dict]:
    from src.repo.catalog_repo import load_candidates_by_slot_from_db

    with psycopg.connect(dsn) as conn:
        pool = [(slot, cand) for slot, cands in load_candidates_by_slot_from_db(conn).items() for cand in cands]
    pool.sort(key=lambda sc: (sc[0], sc[1].name))
    picked = random.Random(20261004).sample(pool, min(count, len(pool)))
    return [{"slot": slot, "name": cand.name, "catalog_price": cand.price} for slot, cand in picked]


def _run_price(dsn: str, case: dict) -> dict:
    try:
        return _run_price_inner(dsn, case)
    except Exception as exc:  # noqa: BLE001
        return {**case, "relevant": False, "reference_price": None, "ms": 0, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


def _run_price_inner(dsn: str, case: dict) -> dict:
    conn = psycopg.connect(dsn)
    try:
        t0 = time.perf_counter()
        outcome = _lookup(conn, case["name"], case["slot"])
        ms = round((time.perf_counter() - t0) * 1000)
        price = outcome.reference_price
        rec = {**case, "relevant": outcome.result.relevant, "reference_price": price, "ms": ms,
               "source_url": outcome.reference_price_source_url}
        if price:
            rec["diff_pct"] = round((price - case["catalog_price"]) / case["catalog_price"] * 100, 1)
        return rec
    finally:
        conn.rollback()
        conn.close()


def _summary(cases: list[dict], prices: list[dict]) -> dict:
    def group(name):
        return [c for c in cases if c["group"] == name]

    fab, real, obs = group("fabricated"), group("real"), group("obscure")
    field_rows = [chk for c in real for chk in c.get("checks", {}).values()]
    returned = [chk for chk in field_rows if chk["result"] != "없음"]
    uncached = [c["first_ms"] for c in cases if not c["first_cached"]]
    summary = {
        "errors": sum(c["verdict"] == "오류" for c in cases) + sum("error" in p for p in prices),
        "rate_limited_waits": RETRY_STATS["rate_limited"],
        "fabricated": {"n": len(fab), "hallucinated": sum(c["found"] for c in fab),
                       "relevant_true_but_empty": sum(c["relevant"] and not c["found"] for c in fab)},
        "real": {"n": len(real), "found": sum(c["found"] for c in real),
                 "all_fields_correct": sum(c["verdict"] == "정답" for c in real),
                 "contains_wrong_value": sum(c["verdict"] == "오답 포함" for c in real),
                 "field_total": len(field_rows), "field_returned": len(returned),
                 "field_correct": sum(c["result"] == "정답" for c in returned),
                 "field_wrong": sum(c["result"] == "오답" for c in returned)},
        "obscure": {"n": len(obs), "found": sum(c["found"] for c in obs)},
        "normalization": {"n": len(cases), "second_cached": sum(c["second_cached"] for c in cases),
                          "second_same_result": sum(c["second_same_result"] for c in cases)},
        "latency_ms_uncached": {"n": len(uncached), "median": round(statistics.median(uncached)) if uncached else None,
                                "max": max(uncached) if uncached else None},
    }
    if prices:
        filled = [p for p in prices if p.get("reference_price")]
        diffs = [abs(p["diff_pct"]) for p in filled]
        summary["reference_price"] = {
            "n": len(prices), "filled": len(filled),
            "within_15pct": sum(d <= 15 for d in diffs), "within_30pct": sum(d <= 30 for d in diffs),
            "median_abs_diff_pct": round(statistics.median(diffs), 1) if diffs else None}
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--price-count", type=int, default=10, help="참고가 평가에 쓸 카탈로그 부품 수(0이면 생략)")
    parser.add_argument("--keep-store", action="store_true", help="평가 전에 임시 저장소의 사람이 확인하지 않은 행을 지우지 않는다")
    parser.add_argument("--out", default=str(ROOT / "outputs" / "live_lookup_eval.json"))
    args = parser.parse_args()

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL 환경변수가 필요합니다.", file=sys.stderr)
        return 2
    if not lsl.available():
        print("실시간 검색이 꺼져 있습니다(LIVE_PART_LOOKUP=1, MOCK_MODE=0, OPENAI_API_KEY 필요).", file=sys.stderr)
        return 2

    # 평가는 서비스 전체 상한(운영 보호용)을 걸지 않고, 동시 호출 수만 --workers 로 조절한다.
    lsl.LIVE_LOOKUP_GLOBAL_LIMIT_PER_MIN = 10_000
    if not args.keep_store:        # 이전 평가가 남긴 행이 새 측정을 가리지 않게 — 사람이 확인한(confirmed) 행은 남긴다
        import psycopg
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("DELETE FROM catalog.live_spec_lookup_cache WHERE status <> 'confirmed'")
    lsl.LIVE_REFERENCE_PRICE = False                      # 운영 기본값 그대로 — 스펙 평가는 참고가 끄고
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        cases = list(pool.map(lambda c: _run_case(dsn, c), CASES))
    print(f"[1/2] 스펙 평가 {len(cases)}건 완료 ({time.time() - started:.0f}초)")
    raw_path = Path(args.out).with_suffix(".raw.json")        # 요약 계산이 실패해도 호출 결과는 남긴다
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    prices: list[dict] = []
    if args.price_count:
        lsl.LIVE_REFERENCE_PRICE = True                   # 참고가 평가만 켜고
        targets = _price_cases(dsn, args.price_count)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            prices = list(pool.map(lambda c: _run_price(dsn, c), targets))
        print(f"[2/2] 참고가 평가 {len(prices)}건 완료 ({time.time() - started:.0f}초)")

    result = {"model": os.environ.get("LLM_MODEL"), "ran_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "summary": _summary(cases, prices), "cases": cases, "prices": prices}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=True))
    print(f"결과 저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
