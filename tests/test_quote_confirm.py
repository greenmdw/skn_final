"""받은 견적 확정(재기획 3단계) — 교체한 부품은 purchase_line, 유지한 부품은 kept_part_line 으로 얼리고 리포트가 둘 다 보여 준다."""
from __future__ import annotations

import os
from uuid import uuid4

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from fastapi.testclient import TestClient

    from src.agent import spec_extraction_agent
    from src.api import app
    from src.auth import ratelimit
    from src.engine.stage3_0_candidates import load_pc_catalog

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
def _env():
    ratelimit.reset_all()
    yield
    ratelimit.reset_all()


@pytest.fixture(scope="module")
def catalog():
    return load_pc_catalog(lambda _msg: None)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        r = c.post("/auth/signup", json={"email": f"qc-{uuid4().hex[:12]}@example.test", "password": "abcd1234", "display_name": "확정",
                                          "terms_agreed": True, "privacy_agreed": True, "marketing_agreed": False})
        assert r.status_code == 201, r.text
        yield c


def _weakest_gpu(catalog):
    return min((c for c in catalog["GPU"] if c.product_id and c.specs.get("perf_tier") is not None), key=lambda c: c.specs["perf_tier"])


def _draft(client, monkeypatch, catalog, gpu, *, extra=None):
    items = [{"category": "GPU", "raw_text": gpu.name}]
    for slot in ("CPU", "RAM", "메인보드", "저장장치", "파워"):
        cand = min((c for c in catalog[slot] if c.product_id and c.price), key=lambda c: c.price)
        items.append({"category": slot, "raw_text": cand.name})
    items += extra or []
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: True)
    monkeypatch.setattr(spec_extraction_agent, "extract_items_from_image", lambda _url: items)
    r = client.post("/pc/review-drafts", files=[("images", ("q.png", PNG, "image/png"))], data={"conditions": '{"purpose":"game","resolution":"4K"}'})
    assert r.status_code == 201, r.text
    return r.json()


def _analyzed(client, monkeypatch, catalog, **kw):
    draft = _draft(client, monkeypatch, catalog, _weakest_gpu(catalog), **kw)
    assert client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis").status_code == 200
    base = f"/pc/review-drafts/{draft['draft_id']}"
    return base, client.get(f"{base}/replacements").json()["draft_version"]


def _body(version, **kw):
    return {"expected_version": version, "name": "받은 견적 확정", **kw}


def test_confirming_without_an_analysis_is_refused(client, monkeypatch, catalog):
    draft = _draft(client, monkeypatch, catalog, _weakest_gpu(catalog))
    r = client.post(f"/pc/review-drafts/{draft['draft_id']}/confirm", json=_body(draft["version"]))
    assert r.status_code == 409 and r.json()["error"]["code"] == "analysis_required"


def test_confirming_freezes_replaced_and_kept_parts_in_one_report(client, monkeypatch, catalog):
    base, version = _analyzed(client, monkeypatch, catalog)
    gpu_target = next(t for t in client.get(f"{base}/replacement-targets").json()["targets"] if t["slot"] == "GPU")
    cand = gpu_target["candidates"][0]
    put = client.put(f"{base}/replacements/GPU", json={"expected_version": version, "candidate_product_id": cand["product_id"]})
    assert put.status_code == 200, put.text
    r = client.post(f"{base}/confirm", json=_body(put.json()["draft_version"], memo="메모"))
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["source"] == "quote_check" and report["memo"] == "메모"
    assert [i["slot"] for i in report["items"]] == ["GPU"] and report["items"][0]["product"]["name"] == cand["name"]
    assert {k["slot"] for k in report["kept_parts"]} == {"CPU", "RAM", "메인보드", "저장장치", "파워"}
    assert all(k["qty"] >= 1 for k in report["kept_parts"])
    assert report["quote_check"]["replacements"][0]["slot"] == "GPU" and "compat" in report["quote_check"]
    kept_known = sum(k["line_amount"] for k in report["kept_parts"] if k["line_amount"] is not None)
    assert report["total"] == report["items"][0]["price"] * report["items"][0]["qty"] + kept_known
    # 유지 부품에 견적 가격이 없으면 0원이 아니라 null 이고, 합계가 일부만 더한 값임을 알린다.
    assert all(k["line_amount"] is None for k in report["kept_parts"]) and report["quote_check"]["total_partial"] is True
    # 다시 확정해도 같은 리포트(중복 저장 없음).
    again = client.post(f"{base}/confirm", json=_body(put.json()["draft_version"]))
    assert again.status_code == 200 and len(again.json()["kept_parts"]) == len(report["kept_parts"])
    assert client.get(f"/lists/{report['list_id']}/report").json()["kept_parts"] == report["kept_parts"]


def test_confirming_with_no_replacements_keeps_every_part(client, monkeypatch, catalog):
    base, version = _analyzed(client, monkeypatch, catalog)
    report = client.post(f"{base}/confirm", json=_body(version)).json()
    assert report["items"] == [] and len(report["kept_parts"]) == 6 and report["source"] == "quote_check"


def test_confirm_needs_a_current_version_a_fresh_analysis_and_the_owner(client, monkeypatch, catalog):
    base, version = _analyzed(client, monkeypatch, catalog)
    assert client.post(f"{base}/confirm", json=_body(version + 5)).status_code == 409
    changed = client.patch(f"{base}/conditions", json={"expected_version": version, "conditions": {"resolution": "QHD_165"}})
    assert changed.status_code == 200, changed.text
    stale = client.post(f"{base}/confirm", json=_body(changed.json()["version"]))
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "analysis_stale"
    with TestClient(app) as stranger:
        assert stranger.post(f"{base}/confirm", json=_body(version)).status_code in (401, 404)


def test_a_quote_report_cannot_seed_a_new_revision(client, monkeypatch, catalog):
    base, version = _analyzed(client, monkeypatch, catalog)
    report = client.post(f"{base}/confirm", json=_body(version)).json()
    r = client.post(f"/lists/{report['list_id']}/revisions", json={"from_revision_no": report["revision_no"]})
    assert r.status_code == 422 and r.json()["error"]["code"] == "quote_report_not_editable"


def test_a_kept_part_name_drops_the_category_prefix_of_text_quotes():
    from src.services.quote_confirm_service import _display_name
    assert _display_name({"category": "CPU", "normalized_name": "CPU: AMD Ryzen 5 7500F", "raw_text": "x"}) == "AMD Ryzen 5 7500F"
    assert _display_name({"category": "GPU", "normalized_name": "RTX 5060 Ti", "raw_text": "x"}) == "RTX 5060 Ti"
    assert _display_name({"category": "CPU", "normalized_name": "", "raw_text": "i5-14400F"}) == "i5-14400F"
