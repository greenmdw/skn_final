"""
A 방식 — Odoo 를 협상의 "거울"로 쓴다.

seller 쪽: /api/offer 가 오면 자기 Odoo 에 sale.order(견적요청) 미러를 만들고,
           라운드/낙찰 결과를 chatter 노트로 남긴다. (판매 화면 타임라인에 표시)
buyer 쪽:  구매담당자가 Odoo 에서 만든 purchase.order(초안)를 폴링으로 읽어
           협상을 트리거하고, 결과를 그 PO 의 chatter 로 되돌려 쓴다.

- 전부 best-effort: Odoo 미설정/장애면 조용히 no-op, 협상 자체는 절대 안 막는다.
- 레코드는 txid 로 식별한다 (표준 필드 재사용, 커스텀 필드/모듈 불필요):
    sale.order.client_order_ref  = "NEGO:<txid>"
    purchase.order.partner_ref   = "NEGO:<txid>"   (미처리 초안은 partner_ref 가 빈 값)
"""

from __future__ import annotations

import logging
import os

from .client import OdooJson2Client
from .config import OdooSettings
from .rpc import OdooRpc

log = logging.getLogger("odoo.sync")

TAG = "NEGO:"
BOT_PARTNER_NAME = "협상 브로커"
GPU_NAMES = [
    "NVIDIA RTX PRO 6000 Blackwell",
    "NVIDIA L40S",
    "NVIDIA H100 NVL",
    "NVIDIA RTX 6000 Ada Generation",
    "NVIDIA A100 80GB PCIe",
]


def sync_enabled() -> bool:
    if os.environ.get("ODOO_SYNC", "off").strip().lower() not in {"on", "1", "true", "yes"}:
        return False
    return not OdooSettings.from_env().configuration_errors()


def _rpc() -> OdooRpc:
    return OdooRpc(OdooJson2Client(OdooSettings.from_env()))


def _safe(fn, *a, default=None, what=""):
    try:
        return fn(*a)
    except Exception as exc:  # noqa: BLE001 - best-effort by design
        log.warning("odoo sync 실패(%s): %s", what or getattr(fn, "__name__", "?"), exc)
        return default


# ── 공용 조회/시드 ──────────────────────────────────────────────

def _bot_partner_id(rpc: OdooRpc) -> int | None:
    found = rpc.search_read("res.partner", [["name", "=", BOT_PARTNER_NAME]], ["id"], limit=1)
    if found:
        return found[0]["id"]
    return rpc.create("res.partner", {"name": BOT_PARTNER_NAME, "company_type": "company"})


def _product_id(rpc: OdooRpc, name: str) -> int | None:
    found = rpc.search_read("product.product", [["name", "=", name]], ["id"], limit=1)
    if found:
        return found[0]["id"]
    return rpc.create("product.product", {"name": name, "list_price": 0, "type": "consu"})


def seed(role: str = "both") -> dict:
    """협상봇 파트너 + GPU 5종 product 를 idempotent 하게 만든다."""
    if not sync_enabled():
        return {"ok": False, "reason": "ODOO_SYNC off 또는 Odoo 미설정"}
    rpc = _rpc()
    partner = _safe(_bot_partner_id, rpc, what="partner")
    products = {n: _safe(_product_id, rpc, n, what=f"product {n}") for n in GPU_NAMES}
    return {"ok": True, "role": role, "bot_partner_id": partner, "products": products}


# ── seller: sale.order 미러 ────────────────────────────────────

class SalesMirror:
    model = "sale.order"

    def __init__(self) -> None:
        self.rpc = _rpc()

    def _find(self, txid: str) -> int | None:
        rows = self.rpc.search_read(self.model, [["client_order_ref", "=", TAG + txid]], ["id"], limit=1)
        return rows[0]["id"] if rows else None

    def ensure_quote(self, txid: str, item: str, qty: int, spec: str) -> int | None:
        existing = self._find(txid)
        if existing:
            return existing
        partner = _bot_partner_id(self.rpc)
        product = _product_id(self.rpc, item)
        if not partner or not product:
            return None
        vals = {
            "partner_id": partner,
            "client_order_ref": TAG + txid,
            "note": f"[협상 RFQ] 사양: {spec or '불문'}",
            "order_line": [[0, 0, {"product_id": product, "product_uom_qty": qty, "price_unit": 0}]],
        }
        soid = self.rpc.create(self.model, vals)
        if soid:
            self.rpc.post_note(self.model, soid, f"협상 브로커로부터 견적 요청 수신 (txid {txid})")
        return soid

    def note(self, txid: str, text: str) -> None:
        rid = self._find(txid)
        if rid:
            self.rpc.post_note(self.model, rid, text)

    def outcome(self, txid: str, won: bool, price: int) -> None:
        rid = self._find(txid)
        if not rid:
            return
        msg = f"✅ 낙찰 — 확정 단가 {price:,}원" if won else "❌ 미낙찰 (다른 셀러에게 낙찰)"
        self.rpc.post_note(self.model, rid, msg)


# ── buyer: purchase.order 폴링 ────────────────────────────────

def _parse_notes(raw: str) -> tuple[str, str]:
    """'spec: GDDR6 48GB ECC | priority: price_min' → (spec, priority)"""
    spec, priority = "", "price_min"
    for chunk in (raw or "").split("|"):
        if ":" not in chunk:
            continue
        k, v = chunk.split(":", 1)
        k, v = k.strip().lower(), v.strip()
        if k in {"spec", "사양"}:
            spec = v
        elif k in {"priority", "우선순위"} and v in {"price_min", "spec_max"}:
            priority = v
    return spec, priority


class PurchaseInbox:
    model = "purchase.order"

    def __init__(self) -> None:
        self.rpc = _rpc()

    def next_new_rfq(self) -> dict | None:
        rows = self.rpc.search_read(
            self.model,
            [["state", "=", "draft"], ["partner_ref", "in", [False, ""]]],
            ["id", "order_line", "notes"],
            limit=1, order="id desc",
        )
        if not rows:
            return None
        po = rows[0]
        lines = self.rpc.search_read(
            "purchase.order.line",
            [["order_id", "=", po["id"]]],
            ["product_id", "product_qty", "price_unit"],
            limit=1,
        )
        if not lines:
            return None
        ln = lines[0]
        prod = ln.get("product_id")
        item = prod[1] if isinstance(prod, (list, tuple)) and len(prod) > 1 else str(prod)
        spec, priority = _parse_notes(po.get("notes") or "")
        return {
            "po_id": po["id"],
            "item": item,
            "qty": int(ln.get("product_qty") or 0),
            "cap_price": int(ln.get("price_unit") or 0),
            "spec": spec,
            "priority": priority,
        }

    def claim(self, po_id: int, txid: str) -> None:
        self.rpc.write(self.model, [po_id], {"partner_ref": TAG + txid})
        self.rpc.post_note(self.model, po_id, f"분산 협상 시작 (txid {txid})")

    def note(self, po_id: int, text: str) -> None:
        self.rpc.post_note(self.model, po_id, text)

    def outcome(self, po_id: int, status: str, seller: str, price: int) -> None:
        if status == "SETTLED":
            self.rpc.post_note(self.model, po_id, f"✅ 낙찰: {seller} · 확정 단가 {price:,}원")
        else:
            self.rpc.post_note(self.model, po_id, f"협상 종료: {status}")
