"""Build a local 50:50-slot PC review JSON from fetched text and synthetic drafts.

Missing real reviews remain null slots. Synthetic rows are never represented as
observed customer reviews, and this file is not an approved DB import.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scripts.plan_review_mix import DEFAULT_COUNT_PLAN, build_plan


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RAW = ROOT / "outputs/danawa_review_raw_20260928/reviews.json"
DEFAULT_CATALOG = ROOT / "tmp/review_plan_catalog.json"
DEFAULT_OUTPUT = ROOT / "outputs/review_mix_final_20260928"
SOURCE = "truefit_synthetic_reviews_v1"
SEED = 20260928

SPEC_FIELDS = {
    "CPU": [("소켓 규격", "보드 소켓"), ("기본 소비전력(W)", "기본 전력"),
            ("메모리 규격", "메모리 규격"), ("CPU 계열(정규)", "제품 계열")],
    "MainBoard": [("소켓 규격", "CPU 소켓"), ("폼팩터", "보드 크기"),
                  ("메모리 규격", "메모리 규격"), ("DIMM 슬롯 수", "메모리 슬롯 수"),
                  ("M.2 슬롯 수", "M.2 슬롯 수")],
    "RAM": [("메모리 규격", "메모리 규격"), ("속도(MT/s)", "표기 속도"),
            ("총 용량(GB)", "총 용량"), ("모듈 구성", "모듈 구성")],
    "GPU": [("VRAM(GB)", "VRAM 용량"), ("소비전력(W)", "표기 소비전력"),
            ("PCIe 인터페이스", "PCIe 규격"), ("전원 커넥터", "전원 커넥터")],
    "SSD": [("인터페이스", "연결 방식"), ("프로토콜", "프로토콜"),
            ("폼팩터", "폼팩터"), ("지원 용량", "용량 선택지")],
    "PSU": [("정격 출력(W)", "정격 출력"), ("효율 등급", "효율 등급"),
            ("폼팩터", "파워 규격"), ("케이블 방식", "케이블 방식")],
    "Case": [("지원 메인보드", "지원 보드"), ("CPU 쿨러 높이(mm)", "쿨러 높이 한계"),
             ("GPU 최대 길이(mm)", "그래픽카드 길이 한계"), ("PSU 폼팩터", "파워 규격")],
    "Cooler": [("냉각 방식", "냉각 방식"), ("지원 소켓", "지원 소켓"),
               ("쿨러 높이(mm)", "쿨러 높이"), ("라디에이터(mm)", "라디에이터 크기")],
}
INTRO = [
    "이번 PC 구성에 {model}을 넣어봤어요.",
    "부품을 바꾸면서 {model}을 골랐습니다.",
    "새로 맞춘 구성에서 {model}을 선택했어요.",
    "이번 조립에는 {model}을 써 보기로 했습니다.",
    "여러 부품을 비교하다가 {model}을 선택했어요.",
    "기존 구성을 손보면서 {model}을 넣었습니다.",
    "이번 견적에서는 {model}으로 결정했어요.",
    "예산을 맞춰 보다가 {model}을 골랐습니다.",
]
NOTE = [
    "제 구성에 맞는지는 다른 부품과 함께 확인해야겠네요.",
    "이 수치만으로 체감 성능을 단정하기는 어렵겠어요.",
    "실제 장착 조건은 제품 설명서도 같이 보려고 합니다.",
    "비슷한 가격대의 다른 후보와 한 번 더 비교하고 싶어요.",
    "선택 기준이 분명해져서 견적을 정리하는 데는 도움이 됐습니다.",
    "옵션이나 판매 구성에 따라 차이가 있는지도 확인할 생각이에요.",
    "제가 쓰는 보드와 케이스 조합에서 다시 확인해 보려 해요.",
    "가격이 바뀔 수 있어 구매 시점에는 다시 비교해야겠어요.",
    "긴 시간 사용했을 때의 평가는 별도 후기를 더 찾아볼 생각입니다.",
    "표기 사양과 실제 판매 제품이 같은지도 마지막에 확인하겠습니다.",
]
TOPICS = {
    "CPU": ("발열", "안정성", "조립", "가격"),
    "MainBoard": ("조립", "안정성", "확장", "가격"),
    "RAM": ("안정성", "조립", "가격"),
    "GPU": ("발열", "소음", "조립", "가격"),
    "SSD": ("안정성", "조립", "용량", "가격"),
    "PSU": ("소음", "안정성", "조립", "가격"),
    "Case": ("조립", "소음", "확장", "가격"),
    "Cooler": ("소음", "발열", "조립", "가격"),
}
TOPIC_SENTENCES = {
    "소음": "조용한 구성을 원해서 다른 부품의 팬 소음도 같이 따져봤어요.",
    "발열": "오래 쓰는 구성이라 온도 자료는 별도로 확인할 생각입니다.",
    "안정성": "장시간 안정적으로 쓸 수 있을지는 호환 조건을 더 살펴보려고요.",
    "조립": "직접 조립하면서 규격과 장착 공간을 한 번 더 확인했습니다.",
    "가격": "가격이 바뀌면 선택이 달라질 수 있어서 구매 시점에 다시 비교하려고요.",
    "확장": "나중에 부품을 더할 계획도 있어서 남는 공간을 확인해 봤습니다.",
    "용량": "필요한 용량을 먼저 정하고 다른 선택지와 비교해 봤어요.",
}
STAR_WEIGHTS = {1: 5, 2: 10, 3: 20, 4: 40, 5: 25}


def _valid_spec(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    text = str(value).strip()
    return bool(text) and len(text) <= 80 and text.lower() not in {
        "-", "n/a", "none", "null", "확인 필요", "미확인", "제조사 미공개", "해당 없음"
    }


def _specs(sheet: str, attributes: dict) -> list[tuple[str, str, str]]:
    return [(field, label, str(attributes[field]).strip())
            for field, label in SPEC_FIELDS[sheet] if _valid_spec(attributes.get(field))]


def _synthetic_text(model: str, sheet: str, attributes: dict,
                    index: int) -> tuple[str, dict | None, str]:
    specs = _specs(sheet, attributes)
    introduction = INTRO[index % len(INTRO)].format(model=model)
    note = NOTE[(index // len(INTRO)) % len(NOTE)]
    theme = TOPICS[sheet][index % len(TOPICS[sheet])]
    if specs:
        field, label, value = specs[(index // 3) % len(specs)]
        middle = f"사양표의 {label} 항목에 {value}라고 적혀 있어서 그 부분을 먼저 봤습니다."
        basis = {"field": field, "value": value, "url": attributes.get("상품 URL")}
    else:
        middle = "비교할 때는 규격과 장착 조건을 먼저 살펴보게 됩니다."
        basis = None
    return f"{introduction} {middle} {TOPIC_SENTENCES[theme]} {note}", basis, theme


def _rank_real(row: dict) -> str:
    key = f"{row['product_key']}|{row['source']}|{row['external_review_key']}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def build_mix(count_plan: dict, raw: dict, catalog: dict) -> dict:
    if raw.get("source") != "danawa_company_product_review" or not raw.get("contains_original_review_text"):
        raise ValueError("expected local raw Danawa research file")
    plan = build_plan(count_plan)
    catalog_index = {(row["sheet"], row["manufacturer"], row["model"]): row
                     for row in catalog["catalog"]}
    if len(catalog_index) != len(catalog["catalog"]):
        raise ValueError("duplicate catalog identity")
    real_by_product: dict[str, list[dict]] = defaultdict(list)
    seen_real: set[tuple[str, str]] = set()
    for row in raw["records"]:
        identity = (row["source"], str(row["external_review_key"]))
        if identity in seen_real:
            raise ValueError(f"duplicate real review ID: {identity}")
        seen_real.add(identity)
        if not row.get("text") or not row.get("text_matches_metadata_hash"):
            raise ValueError(f"missing or changed real review: {identity}")
        real_by_product[row["product_key"]].append(row)
    plan_keys = {row["product_key"] for row in plan["records"]}
    if set(real_by_product) - plan_keys:
        raise ValueError("raw review has unknown product_key")

    records: list[dict] = []
    synthetic_rows: list[dict] = []
    for item in plan["records"]:
        key = item["product_key"]
        target_half = item["real_reviews_needed_for_target"]
        catalog_row = catalog_index[(item["sheet"], item["manufacturer"], item["model"])]
        available = real_by_product.get(key, [])
        selected = sorted(available, key=_rank_real)[:target_half]
        real = [{
            "review_id": f"danawa:{row['external_review_key']}",
            "kind": "real_unreviewed",
            "product_key": key,
            "text": row["text"],
            "stars": row["rating"],
            "review_posted_date": row["review_posted_date"],
            "author_ref": None,
            "source": row["source"],
            "source_product_url": row["source_product_url"],
            "source_pcode": row["source_pcode"],
            "displayed_mall": row.get("displayed_mall"),
            "model_match_status": row["model_match_status"],
            "sku_match_status": row["sku_match_status"],
            "usage_status": "unreviewed_local_raw_research_only",
        } for row in selected]
        real.extend([None] * (target_half - len(real)))
        synthetic = []
        for index in range(target_half):
            display_name = f"{item['manufacturer']} {item['model']}"
            text, spec_basis, theme = _synthetic_text(display_name, item["sheet"],
                                                      catalog_row["attributes"], index)
            review = {
                "review_id": f"synthetic:{key}:{index + 1:03d}",
                "kind": "synthetic",
                "product_key": key,
                "text": text,
                "stars": None,
                "review_posted_date": None,
                "author_ref": None,
                "source": SOURCE,
                "source_product_url": None,
                "spec_basis": spec_basis,
                "review_theme": theme,
                "usage_status": "synthetic_demo_only",
            }
            synthetic.append(review)
            synthetic_rows.append(review)
        records.append({
            "product_key": key,
            "sheet": item["sheet"],
            "manufacturer": item["manufacturer"],
            "model": item["model"],
            "target_total": item["target_total_even"],
            "target_real": target_half,
            "target_synthetic": target_half,
            "real_available_raw": len(available),
            "real_filled": len(selected),
            "real_missing": target_half - len(selected),
            "synthetic_filled": target_half,
            "mix_complete": len(selected) == target_half,
            "real_reviews": real,
            "synthetic_reviews": synthetic,
        })

    # Rating assignment is independent of the sentence templates and themes.
    rating_pool = [star for star, weight in STAR_WEIGHTS.items() for _ in range(weight)]
    ratings = [rating_pool[index % len(rating_pool)] for index in range(len(synthetic_rows))]
    random.Random(SEED).shuffle(ratings)
    for review, stars in zip(synthetic_rows, ratings):
        review["stars"] = stars
    excluded_synthetic: list[dict] = []
    for row in records:
        keep = row["real_filled"] if row["real_filled"] else row["target_synthetic"]
        excluded_synthetic.extend(row["synthetic_reviews"][keep:])
        row["synthetic_reviews"] = row["synthetic_reviews"][:keep]
        row["synthetic_filled"] = keep
        row["synthetic_excluded_by_ratio"] = row["target_synthetic"] - keep
        row["filled_mix_balanced"] = row["real_filled"] > 0 and row["real_filled"] == keep
    retained_synthetic = [review for row in records for review in row["synthetic_reviews"]]
    summary = {
        "products": len(records),
        "target_real": sum(row["target_real"] for row in records),
        "target_synthetic": sum(row["target_synthetic"] for row in records),
        "real_filled": sum(row["real_filled"] for row in records),
        "real_missing": sum(row["real_missing"] for row in records),
        "synthetic_filled": len(retained_synthetic),
        "synthetic_excluded_by_ratio": len(excluded_synthetic),
        "products_with_full_50_50": sum(row["mix_complete"] for row in records),
        "products_with_balanced_filled_reviews": sum(row["filled_mix_balanced"] for row in records),
        "products_with_no_real": sum(row["real_filled"] == 0 for row in records),
        "products_with_missing_real": sum(row["real_missing"] > 0 for row in records),
        "filled_total": sum(row["real_filled"] + row["synthetic_filled"] for row in records),
        "observed_real_share_of_filled": round(
            sum(row["real_filled"] for row in records) / max(1, sum(
                row["real_filled"] + row["synthetic_filled"] for row in records)), 4),
        "synthetic_rating_distribution": dict(sorted(Counter(r["stars"] for r in retained_synthetic).items())),
    }
    return {
        "schema_version": 1,
        "status": "local_draft_with_missing_real_slots",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_raw_status": raw["status"],
        "usage_approved": False,
        "db_imported": False,
        "policy": {
            "per_product_max_total": 100,
            "target_ratio": "real:synthetic=1:1",
            "missing_real_representation": "null_slot",
            "ratio_adjustment": "cap_synthetic_to_filled_real_when_real_exists",
            "zero_real_products": "keep_original_synthetic_allocation",
            "synthetic_is_not_real_review_evidence": True,
            "synthetic_posted_dates_and_authors": "null_not_invented",
            "real_selection": "stable_sha256_rank_by_product_source_review_id",
            "synthetic_rating": "seeded_5_10_20_40_25_percent_independent_of_text",
        },
        "summary": summary,
        "products": records,
        "excluded_synthetic_reviews": excluded_synthetic,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count-plan", type=Path, default=DEFAULT_COUNT_PLAN)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    mix = build_mix(json.loads(args.count_plan.read_text(encoding="utf-8")),
                    json.loads(args.raw.read_text(encoding="utf-8")),
                    json.loads(args.catalog.read_text(encoding="utf-8")))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = args.output_dir / "reviews_50_50.json"
    backup_path = args.output_dir / "reviews_50_50.before_ratio_adjustment.json"
    if output_path.exists() and not backup_path.exists():
        shutil.copy2(output_path, backup_path)
    excluded = mix.pop("excluded_synthetic_reviews")
    output_path.write_text(
        json.dumps(mix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "synthetic_excluded_by_ratio.json").write_text(
        json.dumps(excluded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "report.json").write_text(
        json.dumps({"status": mix["status"], **mix["summary"]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    missing = [{"product_key": row["product_key"], "sheet": row["sheet"],
                "model": row["model"], "target_real": row["target_real"],
                "real_filled": row["real_filled"], "real_missing": row["real_missing"]}
               for row in mix["products"] if row["real_missing"]]
    (args.output_dir / "missing_real.json").write_text(
        json.dumps(missing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(mix["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
