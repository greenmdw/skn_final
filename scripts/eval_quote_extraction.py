"""받은 견적 점검 사양 추출(이미지·텍스트) 평가 — 전체_테스트_시나리오_실행_기획.md §8(6번).

실제 OpenAI 호출(비전·텍스트)을 한다 — 비용이 든다(기본: 이미지 12종 + 텍스트 6종, 각 2회 = 약 36회).
  MOCK_MODE=0 PYTHONPATH=. uv run python scripts/eval_quote_extraction.py --images-dir <견적 이미지 폴더> --out outputs/<파일>.json

이미지 폴더에는 아래 CASES 의 file 이름(1.webp·2.png … 7.png)과, make_extraction_samples.py 가 만든 derived/ 가 있어야 한다. 정답은 사람이 이미지를 보고 적은 기준(모델명 토큰)이다.
점검 항목: 항목 회수율(정답 부품이 부품군·모델 토큰까지 맞게 읽혔나) · 오탐(정답에 없는 부품·조립비·OS·합계가 항목이 됐나) ·
가격 정확도(가격이 있는 항목) · 재현성(같은 입력 2회의 결과가 같은가) · 지어낸 브랜드를 그럴듯한 다른 이름으로 고치지 않는가 ·
PC 무관 이미지는 항목이 0개인가. 판정은 코드가 하고 LLM은 추출만 한다."""
from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.agent import spec_extraction_agent  # noqa: E402
from src.engine.quote_items import split_line  # noqa: E402

# (부품군, [모델 토큰 — 전부 들어 있어야 맞게 읽은 것], 기대 가격(없으면 None))
IMAGE_CASES = [
    {"id": "I1", "file": "1.webp", "note": "컴퓨존 견적서(2쪽, 15행, 조립비 4행·합계)",
     "expect": [("저장장치", ["990", "pro"], 954990), ("CPU", ["9800x3d"], 636500), ("파워", ["sf-1000f14ge"], 189000),
                ("메인보드", ["b850"], 326750), ("GPU", ["5080"], 2598000), ("케이스", ["o11d"], 279000),
                ("RAM", ["t-create"], 779100), ("쿨러", ["masterliquid"], 180990)],
     "optional": [("쿨러", ["p14"], None), ("쿨러", ["p12"], None)],            # PC 쿨링팬 — 쿨러로 읽어도 틀린 건 아니다
     "forbidden": ["조립", "6,099,580", "안정화"]},
    {"id": "I2", "file": "2.png", "note": "광고 격자(가격 없음, CPU 2모델 병기, 부가 사은품·조립)",
     "expect": [("CPU", ["7500x3d"], None), ("CPU", ["7800x3d"], None), ("메인보드", ["b650m", "k"], None), ("RAM", ["5600"], None),
                ("GPU", ["5060"], None), ("저장장치", ["c715"], None), ("쿨러", ["120", "se"], None), ("케이스", ["1stplayer"], None),
                ("파워", ["600w"], None)],
     "optional": [], "forbidden": ["bios", "선정리", "장패드", "키보드", "190"]},
    {"id": "I3", "file": "3.png", "note": "특별견적 카드(283만원 합계, 8부품)",
     "expect": [("CPU", ["7500x3d"], None), ("쿨러", ["ag620"], None), ("메인보드", ["b650em"], None), ("RAM", ["5600"], None),
                ("GPU", ["9070"], None), ("저장장치", ["legend"], None), ("케이스", ["mi5"], None), ("파워", ["850"], None)],
     "optional": [], "forbidden": ["283"]},
    {"id": "I4", "file": "4.webp", "note": "사양변경 목록(HDD·DVD 미포함, OS·사운드카드, 합계)",
     "expect": [("CPU", ["14400f"], None), ("쿨러", ["x92"], None), ("메인보드", ["h610m"], None), ("RAM", ["3200"], None),
                ("GPU", ["5050"], None), ("저장장치", ["p300"], None), ("파워", ["600w"], None), ("케이스", ["d4"], None)],
     "optional": [], "forbidden": ["미포함", "윈도우", "1,319,990", "1,503,290", "62,637"]},
    {"id": "I5", "file": "5.webp", "note": "컴퓨존 견적서(조립비 2행·Windows)",
     "expect": [("CPU", ["7500x3d"], 316000), ("메인보드", ["b650em"], 175040), ("RAM", ["ud238"], 320000), ("저장장치", ["pm9a1"], 380500),
                ("GPU", ["5050"], 449000), ("케이스", ["d7"], 49110), ("파워", ["sth-800b"], 59900), ("쿨러", ["rt620"], 39900)],
     "optional": [], "forbidden": ["조립", "windows", "2,044,450", "205,000"]},
    {"id": "I6", "file": "6.webp", "note": "영문 견적(USD, SSD 가격 없음, OS·모니터 칸 비어 있음)",
     "expect": [("CPU", ["7800x3d"], None), ("쿨러", ["corequid", "a13"], None), ("메인보드", ["b650e"], None), ("RAM", ["vengeance"], None),
                ("저장장치", ["p31"], None), ("GPU", ["9070"], None), ("케이스", ["north"], None), ("파워", ["rm850x"], None)],
     "optional": [], "forbidden": ["$"], "usd": True},
    {"id": "I7", "file": "7.png", "note": "부품 사진 격자(CPU 2모델 병기, 조립 서비스)",
     "expect": [("CPU", ["7500x3d"], None), ("CPU", ["7800x3d"], None), ("메인보드", ["b650m", "k"], None), ("RAM", ["5600"], None),
                ("GPU", ["9070"], None), ("저장장치", ["c715"], None), ("쿨러", ["120", "se"], None), ("케이스", ["d7"], None),
                ("파워", ["800w"], None)],
     "optional": [], "forbidden": ["bios", "선정리"]},
]
# 이미지 I6 의 쿨러 정답 토큰 오타 방지(corequid → coreliquid)
IMAGE_CASES[5]["expect"][1] = ("쿨러", ["coreliquid", "a13"], None)

DEGRADED = [("D1", "5.webp", "해상도 45%로 줄였다 늘림(저해상도)", "lowres"), ("D2", "5.webp", "JPEG 품질 20(압축 잡음)", "jpeg"),
            ("D3", "5.webp", "가우시안 블러 반경 2(흐림)", "blur"), ("D4", "1.webp", "해상도 40%(저해상도, 15행)", "lowres")]

TEXT_CASES = [
    {"id": "T1", "note": "줄바꿈 key: value + 수량·가격",
     "text": "CPU: AMD Ryzen 5 7500F 238,000원\n메인보드: MSI B650 TOMAHAWK 250,000원\n램: DDR5 5600 16GB 2개 90,000원",
     "expect": [("CPU", ["7500f"]), ("메인보드", ["b650"]), ("RAM", ["5600"])], "forbidden": []},
    {"id": "T2", "note": "쉼표로 이은 한 줄(한글 표기)",
     "text": "라이젠 5 7500F, 지포스 RTX 4060, 삼성 DDR5 16GB, 크루셜 P3 Plus 1TB, 시소닉 GX-750, 다크플래쉬 DLM21",
     "expect": [("CPU", ["7500f"]), ("GPU", ["4060"]), ("RAM", ["ddr5"]), ("저장장치", ["p3"]), ("파워", ["gx-750"]), ("케이스", ["dlm21"])],
     "forbidden": []},
    {"id": "T3", "note": "줄글 자유 서술",
     "text": "저는 지금 라이젠 5 5600에 RTX 3060 쓰고 있고 램은 DDR4 16기가 2개 꽂았어요. 파워는 시소닉 550W 쓰는데 케이스는 NZXT H510이에요",
     "expect": [("CPU", ["5600"]), ("GPU", ["3060"]), ("RAM", ["ddr4"]), ("파워", ["550"]), ("케이스", ["h510"])], "forbidden": []},
    {"id": "T4", "note": "같은 부품군 두 제품(GPU 2개)",
     "text": "CPU: AMD Ryzen 5 7500F\nGPU: AMD Radeon RX 7600 438,000원\nGPU: MSI RTX 4060 VENTUS 2X BLACK OC 8GB 419,000원",
     "expect": [("CPU", ["7500f"]), ("GPU", ["7600"]), ("GPU", ["4060"])], "forbidden": []},
    {"id": "T5", "note": "조립비·OS·합계가 섞임",
     "text": "CPU: Intel Core i5-14400F 238,000원\n조립비: 30,000원\nWindows 11 Home 205,000원\n합계: 473,000원",
     "expect": [("CPU", ["14400f"])], "forbidden": ["조립", "windows", "473,000", "합계"]},
    {"id": "T6", "note": "영문·달러 표기",
     "text": "CPU: Ryzen 5 7500F $199\nGPU: RTX 4060 $299\nTotal: $498",
     "expect": [("CPU", ["7500f"]), ("GPU", ["4060"])], "forbidden": ["total", "498"], "usd": True},
]

FAKE_LINES = ["CPU  ZyraTech Nova X9000 8-Core 4.2GHz        199,000", "GPU  Glimmer RTX 9099 SuperTi 24GB          1,990,000",
              "RAM  Qortex Blaze DDR5-7777 32GB               99,000", "CPU  AMD Ryzen 7 9800X3D 8-Core                 636,500"]
FAKE_EXPECT = [("CPU", ["nova", "x9000"], 199000), ("GPU", ["9099"], 1990000), ("RAM", ["blaze", "7777"], 99000), ("CPU", ["9800x3d"], 636500)]


def _data_url(path: Path | None = None, raw: bytes | None = None, mime: str | None = None) -> str:
    if raw is None:
        raw = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or ("image/webp" if path.suffix == ".webp" else "image/png")
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def _score(items: list[dict], case: dict) -> dict:
    """items: [{category, raw_text}] — 정답과 대조."""
    rows = [{"category": i["category"], "raw": i["raw_text"], "low": i["raw_text"].lower(), **split_line(i["raw_text"])} for i in items]
    used: set[int] = set()
    found, missing, price_ok, price_checked = [], [], 0, 0
    for exp in case["expect"]:
        category, tokens = exp[0], exp[1]
        price = exp[2] if len(exp) > 2 else None
        hit = next((n for n, r in enumerate(rows) if n not in used and r["category"] == category and all(t in r["low"] for t in tokens)), None)
        if hit is None:
            missing.append(f"{category}:{'/'.join(tokens)}")
            continue
        used.add(hit)
        found.append(f"{category}:{'/'.join(tokens)}")
        if price is not None:
            price_checked += 1
            price_ok += rows[hit]["quote_line_total"] == price
    for opt in case.get("optional", []):
        hit = next((n for n, r in enumerate(rows) if n not in used and r["category"] == opt[0] and all(t in r["low"] for t in opt[1])), None)
        if hit is not None:
            used.add(hit)
    extra = [f"{r['category']}:{r['normalized_name'][:40]}" for n, r in enumerate(rows) if n not in used]
    forbidden_hits = [f for f in case.get("forbidden", []) for r in rows if f.lower() in r["low"]]
    usd_priced = [r["raw"][:40] for r in rows if case.get("usd") and r["quote_line_total"] is not None]
    return {"expected": len(case["expect"]), "found": len(found), "missing": missing, "extra": extra, "price_checked": price_checked,
            "price_ok": price_ok, "forbidden_hits": forbidden_hits, "usd_misread_as_won": usd_priced, "n_items": len(rows)}


def _signature(items: list[dict]) -> list[str]:
    return sorted(f"{i['category']}|{split_line(i['raw_text'])['normalized_name'].lower()}" for i in items)


def _run_image(job: dict) -> dict:
    out = {"id": job["id"], "note": job["note"], "runs": []}
    for _ in range(2):
        t = time.time()
        try:
            items = spec_extraction_agent.extract_items_from_image(job["data_url"])
            out["runs"].append({"items": items, "seconds": round(time.time() - t, 1)})
        except Exception as exc:  # noqa: BLE001
            out["runs"].append({"error": f"{type(exc).__name__}: {exc}"[:200], "items": []})
    return out


def _run_text(case: dict) -> dict:
    out = {"id": case["id"], "note": case["note"], "runs": []}
    for _ in range(2):
        try:
            out["runs"].append({"items": spec_extraction_agent.extract_items(case["text"])})
        except Exception as exc:  # noqa: BLE001
            out["runs"].append({"error": f"{type(exc).__name__}: {exc}"[:200], "items": []})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images-dir", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--out", default=str(ROOT / "outputs" / "quote_extraction_eval.json"))
    args = parser.parse_args()
    if not spec_extraction_agent.available():
        print("추출 에이전트가 꺼져 있습니다(MOCK_MODE=0, OPENAI_API_KEY, SPEC_EXTRACTION_AGENT=1 필요).", file=sys.stderr)
        return 2
    folder = Path(args.images_dir)
    jobs, cases = [], {}
    for c in IMAGE_CASES:
        jobs.append({**c, "data_url": _data_url(folder / c["file"])})
        cases[c["id"]] = c
    derived = folder / "derived"            # scripts/make_extraction_samples.py 가 만든다
    degraded_files = {"D1": "D1.png", "D2": "D2.jpg", "D3": "D3.png", "D4": "D4.png"}
    for did, src, note, _mode in DEGRADED:
        base = next(c for c in IMAGE_CASES if c["file"] == src)
        jobs.append({"id": did, "note": note, "data_url": _data_url(derived / degraded_files[did])})
        cases[did] = {**base, "id": did}
    fake = {"id": "F1", "note": "지어낸 브랜드·모델 + 실제 9800X3D(환각 회귀)", "expect": FAKE_EXPECT, "optional": [], "forbidden": []}
    jobs.append({"id": "F1", "note": fake["note"], "data_url": _data_url(derived / "F1.png")})
    cases["F1"] = fake
    nonpc = {"id": "N1", "note": "PC 무관(구성도 다이어그램)", "expect": [], "optional": [], "forbidden": []}
    jobs.append({"id": "N1", "note": nonpc["note"], "data_url": _data_url(ROOT / "history" / "architecture.png")})
    cases["N1"] = nonpc
    land = {"id": "N2", "note": "PC 무관(그린 풍경)", "expect": [], "optional": [], "forbidden": []}
    jobs.append({"id": "N2", "note": land["note"], "data_url": _data_url(derived / "N2.png")})
    cases["N2"] = land

    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        image_results = list(pool.map(_run_image, jobs))
        text_results = list(pool.map(_run_text, TEXT_CASES))
    text_cases = {c["id"]: c for c in TEXT_CASES}
    report = {"seconds": round(time.time() - started), "images": [], "texts": []}
    for res, bucket, case_map in [(r, "images", cases) for r in image_results] + [(r, "texts", text_cases) for r in text_results]:
        case = case_map[res["id"]]
        scores = [_score(run["items"], case) for run in res["runs"] if "error" not in run]
        sigs = [_signature(run["items"]) for run in res["runs"] if "error" not in run]
        report[bucket].append({
            "id": res["id"], "note": res["note"], "errors": [run["error"] for run in res["runs"] if "error" in run],
            "scores": scores, "reproducible": len(sigs) == 2 and sigs[0] == sigs[1],
            "seconds": [run.get("seconds") for run in res["runs"]],
            "runs": [[{"category": i["category"], "raw": i["raw_text"][:70]} for i in run["items"]] for run in res["runs"]]})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for bucket in ("images", "texts"):
        for r in report[bucket]:
            s = r["scores"][0] if r["scores"] else {}
            print(f"{r['id']:3} found {s.get('found', '-')}/{s.get('expected', '-')} items={s.get('n_items', '-')} "
                  f"price {s.get('price_ok', '-')}/{s.get('price_checked', '-')} repro={r['reproducible']} "
                  f"missing={s.get('missing')} extra={s.get('extra')} forbidden={s.get('forbidden_hits')} err={r['errors']}")
    print("saved", args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
