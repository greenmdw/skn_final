"""Small, read-only Danawa product-review availability pilot.

Fetches the site's public *shopping-mall product review* list, not its general
opinion board. Review bodies are processed in memory only: output contains a
hash and length, never the original text, author name, or IP address.

This is not an approved real-review import or a 322-product bulk crawler.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from scripts.plan_review_mix import DEFAULT_COUNT_PLAN, product_key


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs/review_crawl_pilot_20260927"
DEFAULT_MATCHES = ROOT / "config/review_model_family_matches.json"
BASE = "https://prod.danawa.com/info/"
LIST_ENDPOINT = BASE + "dpg/ajax/companyProductReview.ajax.php"
SHEETS = ("CPU", "MainBoard", "RAM", "GPU", "SSD", "PSU", "Case", "Cooler")
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
REVIEW_ID = re.compile(r"^danawa-prodBlog-companyReview-button-block-(\d+)$")
POSTED_DATE = re.compile(r"(20\d\d)[.\-/](\d{1,2})[.\-/](\d{1,2})")
STAR_WIDTH = re.compile(r"width\s*:\s*(\d+(?:\.\d+)?)%")
THEME_TERMS = {
    "소음": ("소음", "시끄럽", "조용", "팬소리"),
    "발열": ("발열", "온도", "뜨겁", "열감"),
    "조립": ("조립", "설치", "장착"),
    "호환": ("호환", "인식", "연결"),
    "안정성": ("안정", "오류", "고장", "불량"),
    "가격": ("가격", "가성비", "비싸", "저렴"),
}


@dataclass
class _Card:
    review_id: str | None = None
    date_parts: list[str] = field(default_factory=list)
    mall_parts: list[str] = field(default_factory=list)
    body_parts: list[str] = field(default_factory=list)
    star_width: float | None = None


class ReviewCardParser(HTMLParser):
    """Read only the fields necessary to audit availability; discard body on output."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[_Card] = []
        self._card: _Card | None = None
        self._stack: list[tuple[str, set[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if self._card is None and tag == "li" and "danawa-prodBlog-companyReview-clazz-more" in classes:
            self._card = _Card()
            self._stack = []
        if self._card is None:
            return
        if tag not in VOID_TAGS:
            self._stack.append((tag, classes))
        identifier = attributes.get("id") or ""
        match = REVIEW_ID.fullmatch(identifier)
        if match:
            self._card.review_id = match.group(1)
        if "star_mask" in classes and self._card.star_width is None:
            width = STAR_WIDTH.search(attributes.get("style") or "")
            if width:
                self._card.star_width = float(width.group(1))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self._card is None:
            return
        while self._stack:
            last_tag, _ = self._stack.pop()
            if last_tag == tag:
                break
        if tag == "li" and not self._stack:
            self.cards.append(self._card)
            self._card = None

    def handle_data(self, data: str) -> None:
        if self._card is None or not data.strip():
            return
        classes = {name for _, group in self._stack for name in group}
        if "date" in classes:
            self._card.date_parts.append(data)
        if "mall" in classes:
            self._card.mall_parts.append(data)
        if "atc_cont" in classes:
            self._card.body_parts.append(data)


def pcode_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "prod.danawa.com" or parsed.path != "/info/":
        raise ValueError(f"unexpected Danawa product URL: {url}")
    codes = parse_qs(parsed.query).get("pcode", [])
    if len(codes) != 1 or not codes[0].isdigit():
        raise ValueError(f"missing numeric pcode: {url}")
    return codes[0]


def load_model_matches(path: Path) -> set[tuple[str, str]]:
    """Explicitly reviewed pcode/model-family pairs; never infer approval from counts."""
    document = json.loads(path.read_text(encoding="utf-8"))
    pairs: set[tuple[str, str]] = set()
    for row in document["matches"]:
        pair = (row["product_key"], row["pcode"])
        if row["scope"] != "model_family" or not row.get("source_title"):
            raise ValueError(f"invalid model-family match: {pair}")
        if pair in pairs:
            raise ValueError(f"duplicate model-family match: {pair}")
        pairs.add(pair)
    return pairs


def select_pilot_products(count_plan: dict, per_sheet: int = 1,
                          model_matches: set[tuple[str, str]] | None = None) -> list[dict]:
    """Pick high-count, single-pcode examples for coverage, not approved SKU matches."""
    if not 1 <= per_sheet <= 2:
        raise ValueError("pilot permits only one or two products per sheet")
    selected: list[dict] = []
    for sheet in SHEETS:
        candidates = []
        for row in count_plan["records"]:
            urls = row.get("source_urls") or []
            if row["sheet"] != sheet or len(urls) != 1:
                continue
            try:
                pcode = pcode_from_url(urls[0])
            except ValueError:
                continue
            candidates.append((row.get("observed_family_reviews") or 0, row, pcode))
        candidates.sort(key=lambda item: (-item[0], product_key(item[1])))
        for _, row, pcode in candidates[:per_sheet]:
            key = product_key(row)
            model_matched = (key, pcode) in (model_matches or set())
            selected.append({
                "sheet": sheet, "product_key": key, "pcode": pcode,
                "product_url": BASE + "?pcode=" + pcode,
                "catalog_model": row["model"],
                "match_status": "model_family_matched" if model_matched else "needs_model_review",
            })
    return selected


def request_review_page(pcode: str, page: int, limit: int, timeout: int = 20) -> str:
    if not pcode.isdigit() or page < 1 or not 1 <= limit <= 100:
        raise ValueError("invalid review page request")
    url = LIST_ENDPOINT + "?" + urlencode({
        "prodCode": pcode, "page": page, "limit": limit,
        "score": 0, "usefullScore": "Y", "pageType": "list",
    })
    request = Request(url, headers={
        "User-Agent": "TrueFit-review-pilot/0.1 (small research availability check)",
        "Referer": BASE + "?pcode=" + pcode,
        "Accept": "text/html",
    })
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        return response.read().decode("utf-8", errors="replace")


def parse_review_page(html: str, product: dict, page: int) -> tuple[list[dict], int]:
    parser = ReviewCardParser()
    parser.feed(html)
    rows: list[dict] = []
    invalid = 0
    for card in parser.cards:
        body = " ".join(" ".join(card.body_parts).split())
        date_match = POSTED_DATE.search(" ".join(card.date_parts))
        if not card.review_id or not body:
            invalid += 1
            continue
        posted_date = None
        if date_match:
            year, month, day = map(int, date_match.groups())
            try:
                posted_date = datetime(year, month, day).date().isoformat()
            except ValueError:
                pass
        rating = None
        if card.star_width is not None:
            stars = card.star_width / 20
            if stars.is_integer() and 1 <= stars <= 5:
                rating = int(stars)
        rows.append({
            "product_key": product["product_key"],
            "source": "danawa_company_product_review",
            "displayed_mall": " ".join(" ".join(card.mall_parts).split()) or None,
            "source_pcode": product["pcode"],
            "source_product_url": product["product_url"],
            "external_review_key": card.review_id,
            "review_posted_date": posted_date,
            "review_posted_precision": "day" if posted_date else None,
            "rating": rating,
            "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "body_chars": len(body),
            "theme_mentions": [theme for theme, terms in THEME_TERMS.items() if any(term in body for term in terms)],
            "page": page,
            "model_match_status": product["match_status"],
            "sku_match_status": "not_evaluated",
            "usage_status": "unreviewed",
        })
    return rows, invalid


def run_pilot(count_plan: dict, per_sheet: int, limit: int, max_pages: int, delay: float,
              model_matches: set[tuple[str, str]] | None = None) -> tuple[list[dict], list[dict]]:
    if not 1 <= limit <= 10 or not 1 <= max_pages <= 2 or delay < 0.5:
        raise ValueError("pilot limits: limit <= 10, pages <= 2, delay >= 0.5 s")
    observations: list[dict] = []
    results: list[dict] = []
    seen: set[str] = set()
    for index, product in enumerate(select_pilot_products(count_plan, per_sheet, model_matches)):
        if index:
            time.sleep(delay)
        accepted = duplicate = invalid = pages_read = 0
        error = None
        for page in range(1, max_pages + 1):
            if page > 1:
                time.sleep(delay)
            try:
                html = request_review_page(product["pcode"], page, limit)
                rows, rejected = parse_review_page(html, product, page)
            except Exception as exc:  # a single source failure should appear in the report
                error = f"{type(exc).__name__}: {exc}"
                break
            pages_read += 1
            invalid += rejected
            for row in rows:
                key = row["external_review_key"]
                if key in seen:
                    duplicate += 1
                    continue
                seen.add(key)
                observations.append(row)
                accepted += 1
            if len(rows) < limit:
                break
        results.append({**product, "pages_read": pages_read, "review_rows": accepted,
                        "duplicates": duplicate, "invalid_cards": invalid, "error": error})
    return observations, results


def write_results(output_dir: Path, observations: list[dict], results: list[dict]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = output_dir / "review_metadata.jsonl"
    records.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in observations), encoding="utf-8")
    by_sheet = Counter(row["sheet"] for row in results if row["review_rows"])
    report = {
        "status": "pilot_metadata_only_not_import_ready",
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "products_checked": len(results),
        "products_with_reviews": sum(bool(row["review_rows"]) for row in results),
        "metadata_rows": len(observations),
        "sheets_with_reviews": sorted(by_sheet),
        "contains_original_review_text": False,
        "contains_author_name_or_ip": False,
        "usage_approved": False,
        "sku_matches_approved": False,
        "model_family_matches": sum(row["match_status"] == "model_family_matched" for row in results),
        "products": results,
    }
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count-plan", type=Path, default=DEFAULT_COUNT_PLAN)
    parser.add_argument("--matches", type=Path, default=DEFAULT_MATCHES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--per-sheet", type=int, default=1)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--max-pages", type=int, default=1)
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    plan = json.loads(args.count_plan.read_text(encoding="utf-8"))
    matches = load_model_matches(args.matches)
    observations, results = run_pilot(plan, args.per_sheet, args.limit, args.max_pages, args.delay,
                                      model_matches=matches)
    write_results(args.output_dir, observations, results)
    print(json.dumps({"products_checked": len(results), "metadata_rows": len(observations),
                      "errors": sum(bool(row["error"]) for row in results)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
