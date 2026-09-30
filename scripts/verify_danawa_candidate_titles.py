"""Check unresolved catalog models against public Danawa product-page titles.

This only records short product titles and match proposals. It does not fetch
review bodies or approve any content for recommendation or database import.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.build_danawa_review_queue import DEFAULT_OUTPUT as DEFAULT_QUEUE
from scripts.derive_recorded_danawa_matches import model_tokens_match


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs/danawa_review_queue_20260927/live_title_checks.json"
TITLE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.I | re.S)
GPU_CHIP = re.compile(r"\b(RX|RTX)\s*(\d{4})(?:\s*(XT|TI|SUPER|GRE))?\b", re.I)
GPU_MEMORY = re.compile(r"\b(\d+)\s*GB\b", re.I)
DDR_SPEC = re.compile(r"DDR[45]-\d+", re.I)
RAM_CL = re.compile(r"\bCL\d+", re.I)
RAM_KIT_MODEL = re.compile(r"\((\d+)\s*GB\s*x\s*(\d+)\)", re.I)
RAM_KIT_TITLE = re.compile(r"\((?:\d+GB\s*\()?\s*(\d+)\s*Gx\s*(\d+)\s*\)?\)", re.I)
RAM_SINGLE = re.compile(r"\((\d+)\s*GB\)", re.I)
ATX_VERSION = re.compile(r"ATX\s*(3\.[01])", re.I)


def extract_title(page: bytes, charset: str = "utf-8") -> str | None:
    encodings = list(dict.fromkeys((charset, "utf-8", "cp949")))
    document = min((page.decode(encoding, errors="replace") for encoding in encodings),
                   key=lambda text: text.count("\ufffd"))
    match = TITLE.search(document)
    return html.unescape(" ".join(match.group(1).split())) if match else None


def gpu_model_match(model: str, title: str) -> bool:
    expected = GPU_CHIP.search(model)
    observed = GPU_CHIP.search(title)
    if not expected or not observed or tuple(part.casefold() if part else "" for part in expected.groups()) != tuple(
            part.casefold() if part else "" for part in observed.groups()):
        return False
    memory = GPU_MEMORY.search(model)
    return not memory or any(size == memory.group(1) for size in GPU_MEMORY.findall(title))


def ram_model_match(model: str, title: str) -> bool:
    expected_ddr, observed_ddr = DDR_SPEC.search(model), DDR_SPEC.search(title)
    if not expected_ddr or not observed_ddr or expected_ddr.group().casefold() != observed_ddr.group().casefold():
        return False
    expected_cl, observed_cl = RAM_CL.search(model), RAM_CL.search(title)
    if expected_cl and (not observed_cl or expected_cl.group().casefold() != observed_cl.group().casefold()):
        return False
    kit = RAM_KIT_MODEL.search(model)
    if kit:
        title_kit = RAM_KIT_TITLE.search(title)
        if not title_kit or kit.groups() != title_kit.groups():
            return False
    else:
        single = RAM_SINGLE.search(model)
        title_single = RAM_SINGLE.search(title)
        if not single or not title_single or RAM_KIT_TITLE.search(title) or single.group(1) != title_single.group(1):
            return False
    tail = model[(expected_cl or expected_ddr).end():]
    tail = RAM_KIT_MODEL.sub("", RAM_SINGLE.sub("", tail))
    tail = tail.replace("패키지", "").strip(" -()")
    normalized_tail = "".join(char for char in tail.casefold() if char.isalnum())
    normalized_title = "".join(char for char in title.casefold() if char.isalnum())
    return not normalized_tail or normalized_tail in normalized_title


def psu_model_match(model: str, title: str) -> bool:
    version = ATX_VERSION.search(model)
    observed = ATX_VERSION.search(title)
    if not version or not observed or version.group(1) != observed.group(1):
        return False
    base = "".join(char for char in model[:version.start()].casefold() if char.isalnum())
    normalized_title = "".join(char for char in title.casefold() if char.isalnum())
    return bool(base) and base in normalized_title


def unresolved_candidates(queue: list[dict], *, only_single: bool, max_candidates: int,
                          only_multiple: bool = False, candidate_index: int | None = None) -> list[dict]:
    targets = []
    for row in queue:
        candidates = row["danawa_candidates"]
        if not candidates or any(c["model_match_status"] == "model_family_matched" for c in candidates):
            continue
        if only_single and len(candidates) != 1:
            continue
        if only_multiple and len(candidates) == 1:
            continue
        selection = candidates[:max_candidates] if candidate_index is None else candidates[candidate_index:candidate_index + 1]
        for candidate in selection:
            targets.append({
                "product_key": row["product_key"], "sheet": row["sheet"],
                "catalog_model": row["catalog_model"], "pcode": candidate["pcode"],
                "product_url": candidate["product_url"],
            })
    return targets


def check_title(target: dict, timeout: int = 20) -> dict:
    request = Request(target["product_url"], headers={
        "User-Agent": "Mozilla/5.0 (compatible; TrueFit-research/0.1)",
        "Accept": "text/html",
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            title = extract_title(response.read(600_000), response.headers.get_content_charset() or "utf-8")
        return {**target, "source_title": title,
                "model_text_present": bool(title and model_tokens_match(target["sheet"], target["catalog_model"], title)),
                "error": None}
    except HTTPError as exc:
        return {**target, "source_title": None, "model_text_present": False, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {**target, "source_title": None, "model_text_present": False,
                "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--only-single", action="store_true")
    parser.add_argument("--only-multiple", action="store_true")
    parser.add_argument("--max-candidates", type=int, default=1)
    parser.add_argument("--candidate-index", type=int,
                        help="Zero-based candidate position to check instead of the first N")
    parser.add_argument("--max-products", type=int, default=50)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1.5)
    args = parser.parse_args()
    if args.only_single and args.only_multiple:
        parser.error("choose only one of --only-single and --only-multiple")
    if not 1 <= args.max_candidates <= 3 or not 1 <= args.max_products <= 100 or args.delay < 1:
        parser.error("max-candidates 1..3, max-products 1..100, delay >=1")
    if args.candidate_index is not None and args.candidate_index < 0:
        parser.error("candidate-index must be nonnegative")
    queue = [json.loads(line) for line in args.queue.read_text(encoding="utf-8").splitlines() if line.strip()]
    targets = unresolved_candidates(queue, only_single=args.only_single, only_multiple=args.only_multiple,
                                    max_candidates=args.max_candidates, candidate_index=args.candidate_index)
    targets = targets[args.start_index:args.start_index + args.max_products]
    results = []
    for target in targets:
        if results:
            time.sleep(args.delay)
        result = check_title(target)
        results.append(result)
        if result["error"] in ("HTTP 403", "HTTP 429"):
            break
    report = {
        "status": "model_title_proposals_not_review_usage_approved",
        "products_checked": len({row["product_key"] for row in results}),
        "pages_checked": len(results),
        "model_text_present": sum(row["model_text_present"] for row in results),
        "errors": sum(bool(row["error"]) for row in results),
        "checks": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("products_checked", "pages_checked", "model_text_present", "errors")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
