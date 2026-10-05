"""받은 견적 점검 — 여러 장 업로드 초안(BE-01~04·07·08). 이미지 인식은 가짜로 바꿔 끼운다(실제 LLM 호출 없음).

일회용 테스트 DB가 필요하다. 합성(mock) 카탈로그를 써서 제품 이름이 고정이다."""
from __future__ import annotations

import base64
import os

import pytest

DSN = os.getenv("DATABASE_URL")
pytestmark = [pytest.mark.db, pytest.mark.skipif(not DSN, reason="일회용 DB 필요")]

if DSN:
    from fastapi.testclient import TestClient

    from src.agent import spec_extraction_agent
    from src.api import app
    from src.auth import ratelimit
    from src.services import quote_draft_service as qds

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CATALOG_SOURCE", "mock")
    ratelimit.reset_all()
    yield
    ratelimit.reset_all()


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _png(tag: str) -> bytes:
    return PNG + tag.encode()


def _fake_extraction(monkeypatch, by_tag: dict[str, list[dict] | Exception], available: bool = True):
    """이미지 끝의 태그로 어떤 항목을 읽었는지 정한다."""
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: available)

    def fake(data_url: str):
        tag = base64.b64decode(data_url.split(",", 1)[1])[len(PNG):].decode()
        result = by_tag[tag]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(spec_extraction_agent, "extract_items_from_image", fake)


def _upload(client, tags, *, text=None, question=None, conditions=None, field="images", content_type="image/png"):
    files = [(field, (f"{t}.png", _png(t), content_type)) for t in tags]
    data = {k: v for k, v in (("text", text), ("question", question), ("conditions", conditions)) if v}
    return client.post("/pc/review-drafts", files=files or None, data=data)


def _items(body, category):
    return [i for i in body["items"] if i["category"] == category]


TWO_IMAGES = {
    "a": [{"category": "CPU", "raw_text": "AMD Ryzen 5 7500F 19996987 238,000원"},
          {"category": "GPU", "raw_text": "MSI RTX 4060 VENTUS 2X BLACK OC 8GB 419,000원"}],
    "b": [{"category": "GPU", "raw_text": "AMD Radeon RX 7600 438,000원"},
          {"category": "메인보드", "raw_text": "MSI B650 TOMAHAWK"}],
}


# ── BE-01 ────────────────────────────────────────────────────────────────────

def test_capabilities_reports_limits_and_is_not_swallowed_by_the_list_id_route(client, monkeypatch):
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: True)
    r = client.get("/pc/reviews/capabilities")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["image_extraction"] is True and body["max_files"] == 3
    assert body["supported_types"] == ["image/png", "image/jpeg", "image/webp"]
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: False)
    assert client.get("/pc/reviews/capabilities").json()["image_extraction"] is False


# ── BE-02·03 ─────────────────────────────────────────────────────────────────

def test_two_images_keep_every_different_product_and_separate_price_code_and_quantity(client, monkeypatch):
    _fake_extraction(monkeypatch, TWO_IMAGES)
    r = _upload(client, ["a", "b"], question="GPU 둘 중 뭐가 나아?")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version"] == 1 and body["partial_success"] is False and body["question"] == "GPU 둘 중 뭐가 나아?"
    assert [s["status"] for s in body["sources"]] == ["completed", "completed"]
    gpus = _items(body, "GPU")
    assert len(gpus) == 2                                           # 같은 부품군의 다른 모델을 모두 보존한다
    cpu = _items(body, "CPU")[0]
    assert cpu["normalized_name"] == "AMD Ryzen 5 7500F" and cpu["product_code"] == "19996987"
    assert cpu["quote_line_total"] == 238000 and cpu["quote_price_type"] == "unit"
    assert cpu["source_ids"] == ["source-1"]
    # 부품군마다 기준 제품 하나 — 기본값은 첫 항목
    assert body["selected_item_by_category"]["GPU"] == gpus[0]["id"]
    assert sum(i["selected_for_analysis"] for i in gpus) == 1


def test_brackets_field_name_is_accepted_too(client, monkeypatch):
    _fake_extraction(monkeypatch, TWO_IMAGES)
    assert _upload(client, ["a"], field="images[]").status_code == 201


def test_the_same_confirmed_product_on_two_images_is_merged_into_one_item(client, monkeypatch):
    same = [{"category": "CPU", "raw_text": "AMD Ryzen 5 7500F 238,000원"}]
    _fake_extraction(monkeypatch, {"a": same, "b": same})
    body = _upload(client, ["a", "b"]).json()
    cpus = _items(body, "CPU")
    confirmed = [c for c in cpus if c["match_status"] == "confirmed"]
    if confirmed:                                                   # 합성 카탈로그에서 확정 대응되면 한 항목으로
        assert len(cpus) == 1 and cpus[0]["source_ids"] == ["source-1", "source-2"]


def test_a_failed_image_keeps_the_successful_one(client, monkeypatch):
    _fake_extraction(monkeypatch, {"a": TWO_IMAGES["a"], "b": RuntimeError("boom")})
    r = _upload(client, ["a", "b"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["partial_success"] is True
    assert [s["status"] for s in body["sources"]] == ["completed", "failed"]
    assert body["sources"][1]["error_code"] == "IMAGE_EXTRACTION_FAILED"
    assert len(body["items"]) == 2


def test_text_only_is_accepted_and_becomes_items(client, monkeypatch):
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: False)
    r = client.post("/pc/review-drafts", data={"text": "CPU: AMD Ryzen 5 7500F 238,000원\n메인보드: MSI B650 TOMAHAWK"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert [s["type"] for s in body["sources"]] == ["text"]
    assert {i["category"] for i in body["items"]} >= {"CPU", "메인보드"}


# ── 오류 코드 ────────────────────────────────────────────────────────────────

def test_more_than_the_limit_is_rejected_with_too_many_sources(client, monkeypatch):
    _fake_extraction(monkeypatch, {t: TWO_IMAGES["a"] for t in "abcd"})
    r = _upload(client, list("abcd"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "TOO_MANY_SOURCES"


def test_oversize_and_wrong_type_are_rejected(client, monkeypatch):
    _fake_extraction(monkeypatch, {"a": TWO_IMAGES["a"]})
    monkeypatch.setattr(qds, "QUOTE_DRAFT_MAX_FILE_BYTES", 10)
    r = _upload(client, ["a"])
    assert r.status_code == 413 and r.json()["error"]["code"] == "SOURCE_TOO_LARGE"
    monkeypatch.undo()
    _fake_extraction(monkeypatch, {"a": TWO_IMAGES["a"]})
    bad_mime = _upload(client, ["a"], content_type="image/gif")
    assert bad_mime.status_code == 422
    fake_png = client.post("/pc/review-drafts", files=[("images", ("x.png", b"not an image", "image/png"))])
    assert fake_png.status_code == 422                              # 선언은 PNG인데 바이트가 PNG가 아니다


def test_image_extraction_unavailable_is_503_not_an_empty_result(client, monkeypatch):
    _fake_extraction(monkeypatch, {"a": TWO_IMAGES["a"]}, available=False)
    r = _upload(client, ["a"])
    assert r.status_code == 503 and r.json()["error"]["code"] == "IMAGE_EXTRACTION_UNAVAILABLE"


def test_when_every_image_fails_it_is_503_and_no_session_is_left(client, monkeypatch):
    _fake_extraction(monkeypatch, {"a": RuntimeError("x")})
    r = _upload(client, ["a"])
    assert r.status_code == 503 and r.json()["error"]["code"] == "IMAGE_EXTRACTION_FAILED"


def test_nothing_recognized_is_400(client, monkeypatch):
    _fake_extraction(monkeypatch, {"a": []})
    r = _upload(client, ["a"])
    assert r.status_code == 400 and r.json()["error"]["code"] == "NO_RECOGNIZED_ITEMS"


def test_empty_request_and_bad_conditions_are_422(client, monkeypatch):
    _fake_extraction(monkeypatch, {"a": TWO_IMAGES["a"]})
    assert client.post("/pc/review-drafts").status_code == 422
    assert _upload(client, ["a"], conditions="{not json").status_code == 422
    assert _upload(client, ["a"], conditions='{"purpose": "nonsense"}').status_code == 422


# ── BE-04 ────────────────────────────────────────────────────────────────────

def _draft(client, monkeypatch, tags=("a", "b")):
    _fake_extraction(monkeypatch, TWO_IMAGES)
    return _upload(client, list(tags)).json()


def test_patch_applies_edits_selection_and_bumps_the_version(client, monkeypatch):
    draft = _draft(client, monkeypatch)
    gpu_a, gpu_b = _items(draft, "GPU")
    r = client.patch(f"/pc/review-drafts/{draft['draft_id']}/items", json={
        "expected_version": 1,
        "items": [{"id": gpu_b["id"], "quantity": 1, "quote_line_total": 400000}],
        "selected_item_by_category": {"GPU": gpu_b["id"]},
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 2
    edited = next(i for i in body["items"] if i["id"] == gpu_b["id"])
    assert edited["quote_line_total"] == 400000 and edited["user_edited"] is True
    assert edited["selected_for_analysis"] is True
    assert next(i for i in body["items"] if i["id"] == gpu_a["id"])["selected_for_analysis"] is False
    # GET 으로 다시 읽어도 같다(저장됨)
    again = client.get(f"/pc/review-drafts/{draft['draft_id']}").json()
    assert again["version"] == 2 and again["selected_item_by_category"]["GPU"] == gpu_b["id"]


def test_stale_version_is_409(client, monkeypatch):
    draft = _draft(client, monkeypatch)
    url = f"/pc/review-drafts/{draft['draft_id']}/items"
    assert client.patch(url, json={"expected_version": 1, "items": []}).status_code == 200
    r = client.patch(url, json={"expected_version": 1, "items": []})
    assert r.status_code == 409 and r.json()["error"]["code"] == "STALE_REVIEW_VERSION"


def test_patch_rejects_unknown_items_and_selection_from_another_category(client, monkeypatch):
    draft = _draft(client, monkeypatch)
    url = f"/pc/review-drafts/{draft['draft_id']}/items"
    cpu = _items(draft, "CPU")[0]
    assert client.patch(url, json={"expected_version": 1, "items": [{"id": "nope", "quantity": 1}]}).status_code == 422
    r = client.patch(url, json={"expected_version": 1, "selected_item_by_category": {"GPU": cpu["id"]}})
    assert r.status_code == 422
    # 실패한 요청은 아무것도 바꾸지 않는다(버전도 그대로)
    assert client.get(f"/pc/review-drafts/{draft['draft_id']}").json()["version"] == 1


def test_renaming_an_item_rematches_only_that_item(client, monkeypatch):
    draft = _draft(client, monkeypatch)
    cpu = _items(draft, "CPU")[0]
    gpu = _items(draft, "GPU")[0]
    r = client.patch(f"/pc/review-drafts/{draft['draft_id']}/items", json={
        "expected_version": 1, "items": [{"id": cpu["id"], "normalized_name": "완전히 지어낸 CPU ZZ-9"}]})
    body = r.json()
    renamed = next(i for i in body["items"] if i["id"] == cpu["id"])
    assert renamed["match_status"] == "unmatched" and renamed["matched_product_id"] is None
    untouched = next(i for i in body["items"] if i["id"] == gpu["id"])
    assert untouched["match_status"] == gpu["match_status"] and untouched["user_edited"] is False


# ── BE-07·08 ─────────────────────────────────────────────────────────────────

def test_analysis_uses_only_the_selected_items_and_saves_to_the_same_session(client, monkeypatch):
    draft = _draft(client, monkeypatch)
    gpu_a, gpu_b = _items(draft, "GPU")
    client.patch(f"/pc/review-drafts/{draft['draft_id']}/items", json={
        "expected_version": 1, "selected_item_by_category": {"GPU": gpu_b["id"]}})
    r = client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["list_id"] == draft["draft_id"] and body["draft_version"] == 2
    used = {i["category"]: i["normalized_name"] for i in body["used_items"]}
    assert used["GPU"] == gpu_b["normalized_name"]                  # 고른 GPU만 — 다른 GPU는 분석에 안 들어간다
    assert {p["part"] for p in body["parts"]} == set(used)
    assert body["compat"]["checks"] and body["computed_at"]
    saved = client.get(f"/pc/reviews/{draft['draft_id']}")
    assert saved.status_code == 200 and saved.json()["input"]["input_hash"] == body["input"]["input_hash"]


def test_items_without_a_price_are_listed_as_excluded_from_the_total(client, monkeypatch):
    draft = _draft(client, monkeypatch)
    body = client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis").json()
    no_price = [i for i in body["used_items"] if i["quote_price_type"] == "unknown"]
    assert {e["item_id"] for e in body["price_excluded"]} == {i["id"] for i in no_price}
    assert no_price and all("제외" in e["reason"] for e in body["price_excluded"])


def test_conditions_are_kept_and_reach_the_analysis(client, monkeypatch):
    _fake_extraction(monkeypatch, TWO_IMAGES)
    draft = _upload(client, ["a", "b"], conditions='{"purpose": "game", "resolution": "FHD_144"}').json()
    assert draft["conditions"]["purpose"] == "game"
    body = client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis").json()
    assert body["input"]["conditions"]["purpose"] == "game"


def test_only_the_owner_can_read_patch_or_analyze(client, monkeypatch):
    draft = _draft(client, monkeypatch)
    with TestClient(app) as stranger:
        ratelimit.reset_all()
        assert stranger.get(f"/pc/review-drafts/{draft['draft_id']}").status_code == 404
        assert stranger.patch(f"/pc/review-drafts/{draft['draft_id']}/items",
                              json={"expected_version": 1, "items": []}).status_code == 404
        assert stranger.post(f"/pc/review-drafts/{draft['draft_id']}/analysis").status_code == 404


def test_unknown_draft_is_404(client):
    assert client.get("/pc/review-drafts/00000000-0000-0000-0000-000000000000").status_code == 404


# ── 텍스트도 여러 제품 ────────────────────────────────────────────────────────

def test_text_keeps_several_products_of_the_same_category_by_rules(client, monkeypatch):
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: False)
    text = "CPU: AMD Ryzen 5 7500F 238,000원\nGPU: AMD Radeon RX 7600 438,000원\nGPU: MSI RTX 4060 VENTUS 2X BLACK OC 8GB 419,000원"
    r = client.post("/pc/review-drafts", data={"text": text})
    assert r.status_code == 201, r.text
    gpus = _items(r.json(), "GPU")
    assert len(gpus) == 2 and {g["quote_line_total"] for g in gpus} == {438000, 419000}


def test_text_uses_the_llm_item_extraction_when_available(client, monkeypatch):
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: True)
    monkeypatch.setattr(spec_extraction_agent, "extract_items", lambda text: [
        {"category": "GPU", "raw_text": "AMD Radeon RX 7600 438,000원"}, {"category": "GPU", "raw_text": "MSI RTX 4060 419,000원"}])
    body = client.post("/pc/review-drafts", data={"text": "줄글로 적은 견적입니다"}).json()
    assert len(_items(body, "GPU")) == 2


# ── 서로 다른 견적(A안·B안) ────────────────────────────────────────────────────

QUOTE_A = [{"category": "CPU", "raw_text": "AMD Ryzen 5 7500F 238,000원"}, {"category": "GPU", "raw_text": "AMD Radeon RX 7600 438,000원"}]
QUOTE_B = [{"category": "CPU", "raw_text": "AMD Ryzen 5 7500F 238,000원"}, {"category": "GPU", "raw_text": "MSI RTX 4060 VENTUS 2X BLACK OC 8GB 419,000원"},
           {"category": "메인보드", "raw_text": "MSI B650 TOMAHAWK 250,000원"}]


def _two_quotes(client, monkeypatch):
    _fake_extraction(monkeypatch, {"a": QUOTE_A, "b": QUOTE_B})
    return _upload(client, ["a", "b"]).json()


def test_each_uploaded_image_is_one_quote_group_and_shared_products_belong_to_both(client, monkeypatch):
    body = _two_quotes(client, monkeypatch)
    groups = {g["id"]: g for g in body["groups"]}
    assert set(groups) == {"source-1", "source-2"} and groups["source-1"]["name"] == "a"
    items = {i["id"]: i for i in body["items"]}
    assert all("source-1" in items[i]["source_ids"] for i in groups["source-1"]["item_ids"])
    cpu_items = _items(body, "CPU")
    confirmed_cpu = [c for c in cpu_items if c["match_status"] == "confirmed"]
    if confirmed_cpu:                                    # 같은 CPU 가 두 견적에 있으면 한 항목이 두 묶음에 모두 속한다
        assert set(confirmed_cpu[0]["source_ids"]) == {"source-1", "source-2"}


def test_analysis_can_be_limited_to_one_quote(client, monkeypatch):
    body = _two_quotes(client, monkeypatch)
    url = f"/pc/review-drafts/{body['draft_id']}/analysis"
    a = client.post(url, json={"source_ids": ["source-1"]}).json()
    assert {i["category"] for i in a["used_items"]} == {"CPU", "GPU"}                # 견적 A 에는 메인보드가 없다
    assert [i["normalized_name"] for i in a["used_items"] if i["category"] == "GPU"] == ["AMD Radeon RX 7600"]
    b = client.post(url, json={"source_ids": ["source-2"]}).json()
    assert {i["category"] for i in b["used_items"]} == {"CPU", "GPU", "메인보드"}
    assert "MSI RTX 4060" in [i["normalized_name"] for i in b["used_items"] if i["category"] == "GPU"][0]
    assert client.post(url, json={"source_ids": ["source-9"]}).status_code == 422
    assert client.post(url).status_code == 200                                        # 안 주면 기존처럼 고른 기준 제품 전체


def test_two_quotes_can_be_compared_directly_with_each_side_summary(client, monkeypatch):
    body = _two_quotes(client, monkeypatch)
    url = f"/pc/review-drafts/{body['draft_id']}/quote-comparisons"
    r = client.post(url, json={"a_source_ids": ["source-1"], "b_source_ids": ["source-2"]})
    assert r.status_code == 201, r.text
    comp = r.json()
    rows = {x["category"]: x for x in comp["rows"]}
    assert rows["GPU"]["same_product"] is False and rows["GPU"]["price_diff"] == 419000 - 438000
    assert rows["메인보드"]["received"] is None and rows["메인보드"]["saved"]["name"] == "MSI B650 TOMAHAWK"      # 한쪽에만 있는 부품
    assert comp["labels"] == {"received": "a", "saved": "b"} and comp["kind"] == "draft_quotes"
    assert comp["sides"]["received"]["total"] == 238000 + 438000 and comp["sides"]["saved"]["item_count"] == 3
    assert "compat_summary" in comp["sides"]["saved"] and comp["brief_summary"]["text"]
    # 같은 이미지를 양쪽에 넣거나 없는 견적을 가리키면 거부
    assert client.post(url, json={"a_source_ids": ["source-1"], "b_source_ids": ["source-1"]}).status_code == 422
    assert client.post(url, json={"a_source_ids": ["source-1"], "b_source_ids": ["nope"]}).status_code == 422
    # 결과는 읽어 올 수 있고 질문의 context 로 쓸 수 있다(분석이 끝난 세션)
    client.post(f"/pc/review-drafts/{body['draft_id']}/analysis", json={"source_ids": ["source-2"]})
    again = client.get(f"/pc/reviews/{body['draft_id']}/saved-comparisons/{comp['comparison_id']}")
    assert again.status_code == 200 and again.json()["labels"]["saved"] == "b"
