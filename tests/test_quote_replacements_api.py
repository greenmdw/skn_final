"""교체 추천 API — 교체 대상 조회, 교체 목록 담기·빼기(서버 저장). 실제(DB) 카탈로그를 쓴다 — 제품 ID가 있어야 교체를 담을 수 있다."""
from __future__ import annotations

import os

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
        yield c


def _weakest_gpu(catalog):
    return min((c for c in catalog["GPU"] if c.product_id and c.specs.get("perf_tier") is not None), key=lambda c: c.specs["perf_tier"])


def _draft(client, monkeypatch, catalog, gpu, conditions='{"purpose":"game","resolution":"4K"}'):
    items = [{"category": "GPU", "raw_text": gpu.name}]
    for slot, label in (("CPU", "CPU"), ("RAM", "RAM"), ("메인보드", "메인보드"), ("저장장치", "저장장치"), ("파워", "파워")):
        cand = min((c for c in catalog[slot] if c.product_id and c.price), key=lambda c: c.price)
        items.append({"category": label, "raw_text": cand.name})
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: True)
    monkeypatch.setattr(spec_extraction_agent, "extract_items_from_image", lambda _url: items)
    r = client.post("/pc/review-drafts", files=[("images", ("q.png", PNG, "image/png"))], data={"conditions": conditions})
    assert r.status_code == 201, r.text
    return r.json()


def _analyze(client, draft):
    r = client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis")
    assert r.status_code == 200, r.text


def test_targets_need_an_analysis_first(client, monkeypatch, catalog):
    draft = _draft(client, monkeypatch, catalog, _weakest_gpu(catalog))
    r = client.get(f"/pc/review-drafts/{draft['draft_id']}/replacement-targets")
    assert r.status_code == 409 and r.json()["error"]["code"] == "analysis_required"
    pick = next(c for c in catalog["GPU"] if c.product_id)
    put = client.put(f"/pc/review-drafts/{draft['draft_id']}/replacements/GPU", json={"expected_version": draft["version"], "candidate_product_id": pick.product_id})
    assert put.status_code == 409 and put.json()["error"]["code"] == "analysis_required"


def test_a_weak_gpu_is_a_replace_target_and_its_candidates_are_never_lower(client, monkeypatch, catalog):
    gpu = _weakest_gpu(catalog)
    draft = _draft(client, monkeypatch, catalog, gpu)
    _analyze(client, draft)
    body = client.get(f"/pc/review-drafts/{draft['draft_id']}/replacement-targets").json()
    assert set(body["counts"]) == {"replace", "verify", "keep"} and body["draft_version"] >= 1 and body["analysis_stale"] is False
    targets = {t["slot"]: t for t in body["targets"]}
    target = targets["GPU"]
    assert target["kind"] == "replace" and target["rank"] >= 1 and target["reasons"] and target["current_name"] == gpu.name
    assert target["candidates"], target
    pool = {c.product_id: c for c in catalog["GPU"]}
    for cand in target["candidates"]:
        assert pool[cand["product_id"]].specs["perf_tier"] >= gpu.specs["perf_tier"] and cand["name"] != gpu.name
    assert [t["kind"] for t in body["targets"]][0] == "replace"            # 바꿀 부품이 가장 먼저


def test_a_replacement_is_saved_on_the_server_and_can_be_undone(client, monkeypatch, catalog):
    gpu = _weakest_gpu(catalog)
    draft = _draft(client, monkeypatch, catalog, gpu)
    _analyze(client, draft)
    base = f"/pc/review-drafts/{draft['draft_id']}"
    version = client.get(f"{base}/replacements").json()["draft_version"]
    gpu_target = next(t for t in client.get(f"{base}/replacement-targets").json()["targets"] if t["slot"] == "GPU")
    cand = gpu_target["candidates"][0]
    put = client.put(f"{base}/replacements/GPU", json={"expected_version": version, "candidate_product_id": cand["product_id"]})
    assert put.status_code == 200, put.text
    state = put.json()
    assert state["draft_version"] == version + 1 and [r["slot"] for r in state["replacements"]] == ["GPU"]
    assert state["replacements"][0]["candidate"]["name"] == cand["name"] and state["replacements"][0]["from"]["name"] == gpu.name
    assert set(state["compat"]) == {"before", "after", "new_issues", "resolved_issues"} and "delta_total" in state["price"]
    again = client.get(f"{base}/replacements").json()                                  # 새로 읽어도 남아 있다(서버 저장)
    assert [r["slot"] for r in again["replacements"]] == ["GPU"]
    gone = client.request("DELETE", f"{base}/replacements/GPU", json={"expected_version": again["draft_version"]})
    assert gone.status_code == 200 and gone.json()["replacements"] == []
    assert client.request("DELETE", f"{base}/replacements/GPU", json={"expected_version": gone.json()["draft_version"]}).json()["replacements"] == []


def test_a_replacement_is_rejected_for_a_stale_version_a_non_catalog_product_and_a_stranger(client, monkeypatch, catalog):
    draft = _draft(client, monkeypatch, catalog, _weakest_gpu(catalog))
    _analyze(client, draft)
    base = f"/pc/review-drafts/{draft['draft_id']}"
    version = client.get(f"{base}/replacements").json()["draft_version"]
    pick = next(c for c in catalog["GPU"] if c.product_id)
    assert client.put(f"{base}/replacements/GPU", json={"expected_version": version + 3, "candidate_product_id": pick.product_id}).status_code == 409
    assert client.put(f"{base}/replacements/GPU", json={"expected_version": version, "candidate_product_id": "not-a-product"}).status_code == 422
    assert client.put(f"{base}/replacements/모니터", json={"expected_version": version, "candidate_product_id": pick.product_id}).status_code == 422
    with TestClient(app) as stranger:
        assert stranger.get(f"{base}/replacement-targets").status_code == 404
        assert stranger.put(f"{base}/replacements/GPU", json={"expected_version": version, "candidate_product_id": pick.product_id}).status_code == 404


def test_a_lower_part_can_still_be_picked_but_is_flagged_and_changing_conditions_marks_the_targets_stale(client, monkeypatch, catalog):
    best = max((c for c in catalog["GPU"] if c.product_id and c.specs.get("perf_tier") is not None), key=lambda c: c.specs["perf_tier"])
    weakest = _weakest_gpu(catalog)
    draft = _draft(client, monkeypatch, catalog, best)
    _analyze(client, draft)
    base = f"/pc/review-drafts/{draft['draft_id']}"
    version = client.get(f"{base}/replacements").json()["draft_version"]
    state = client.put(f"{base}/replacements/GPU", json={"expected_version": version, "candidate_product_id": weakest.product_id}).json()
    assert "grade_lower" in state["replacements"][0]["warnings"]                       # 막지 않고 경고로 알린다
    patched = client.patch(f"{base}/conditions", json={"expected_version": state["draft_version"], "conditions": {"resolution": "FHD_144"}}).json()
    assert patched["analysis_stale"] is True
    assert client.get(f"{base}/replacement-targets").json()["analysis_stale"] is True
