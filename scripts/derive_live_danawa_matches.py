"""Conservatively promote checked page titles to model-family matches.

Matching is only for collection research. It does not approve review use or
confirm SKU-specific claims. Ambiguous variants and duplicate pcodes remain out.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.build_danawa_review_queue import DEFAULT_OUTPUT as DEFAULT_QUEUE
from scripts.verify_danawa_candidate_titles import gpu_model_match, psu_model_match, ram_model_match


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHECKS = [ROOT / "outputs/danawa_review_queue_20260927/live_title_single.json",
                  ROOT / "outputs/danawa_review_queue_20260927/live_title_multiple_first.json"]
DEFAULT_OUTPUT = ROOT / "outputs/danawa_review_queue_20260927/live_verified_matches.json"
VARIANT_MARKERS = (" BTF", " Momentum Edition", " North Mesh", " North XL Mesh",
                   " North TG", " North XL RC", " Torrent Solid", " Torrent Nano")
KNOWN_TITLE_AMBIGUITIES = {"ssd:western-digital:wd_black-sn770m"}  # SN770 M.2 is not SN770M.
NONCANONICAL_DUPLICATE_KEYS = {
    "gpu:nvidia:geforce-rtx-3050-6gb",
    "gpu:nvidia:geforce-rtx-3060-12gb",
    "gpu:nvidia:rtx-6000-ada-generation",
}


def derive(checks: list[dict], queue: list[dict]) -> tuple[list[dict], list[dict]]:
    existing_pcodes = {candidate["pcode"]: row["product_key"] for row in queue
                       for candidate in row["danawa_candidates"]
                       if candidate["model_match_status"] == "model_family_matched"}
    claimed = dict(existing_pcodes)
    matches: list[dict] = []
    rejected: list[dict] = []
    for row in checks:
        key, pcode, title = row["product_key"], row["pcode"], row.get("source_title") or ""
        reason = None
        if row.get("error") or not title:
            reason = "page_error_or_missing_title"
        elif key in NONCANONICAL_DUPLICATE_KEYS:
            reason = "duplicate_catalog_model_uses_canonical_key"
        elif any(marker.casefold() in title.casefold() and marker.casefold() not in row["catalog_model"].casefold()
                 for marker in VARIANT_MARKERS):
            reason = "distinct_named_variant"
        elif key in KNOWN_TITLE_AMBIGUITIES:
            reason = "short_model_collides_with_format_text"
        elif row["sheet"] == "RAM" and " J " in title.upper() and " J " not in row["catalog_model"].upper():
            reason = "distinct_named_ram_variant"
        elif not (gpu_model_match(row["catalog_model"], title) if row["sheet"] == "GPU" else
                  ram_model_match(row["catalog_model"], title) if row["sheet"] == "RAM" else
                  psu_model_match(row["catalog_model"], title) if row["sheet"] == "PSU" else
                  ("SILENT LOOP 3 420" in title.upper()) if key == "cooler:be-quiet!:silent-loop-3-420mm" else
                  ("9100 PRO" in title.upper() and "히트싱크" in title) if key == "ssd:samsung:9100-pro-with-heatsink" else
                  row["model_text_present"]):
            reason = "model_or_capacity_not_verified"
        elif pcode in claimed and claimed[pcode] != key:
            reason = "pcode_already_claimed_by_another_catalog_key"
        if reason:
            rejected.append({"product_key": key, "pcode": pcode, "reason": reason,
                             "source_title": title})
            continue
        claimed[pcode] = key
        matches.append({"product_key": key, "pcode": pcode, "source_title": title,
                        "verification_method": "live_page_title_model_family"})
    return matches, rejected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checks", type=Path, action="append", default=[])
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    paths = args.checks or DEFAULT_CHECKS
    checks = [row for path in paths for row in json.loads(path.read_text(encoding="utf-8"))["checks"]]
    queue = [json.loads(line) for line in args.queue.read_text(encoding="utf-8").splitlines() if line.strip()]
    matches, rejected = derive(checks, queue)
    output = {"status": "live_title_model_family_verified_not_review_usage_approved",
              "matches": matches, "rejected": rejected}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"matches": len(matches), "rejected": len(rejected)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
