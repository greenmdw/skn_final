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


def _confirm_relation(client, draft_id, version, mode="single"):
    """사진이 2장 이상이고 관계가 애매한 초안은 사용자가 확인해야 일반 분석을 할 수 있다 — 확인하고 새 버전을 돌려준다."""
    r = client.patch(f"/pc/review-drafts/{draft_id}/source-relation", json={"expected_version": version, "mode": mode})
    assert r.status_code == 200, r.text
    return r.json()["version"]


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
    version = _confirm_relation(client, draft["draft_id"], 1)
    client.patch(f"/pc/review-drafts/{draft['draft_id']}/items", json={
        "expected_version": version, "selected_item_by_category": {"GPU": gpu_b["id"]}})
    r = client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["list_id"] == draft["draft_id"] and body["draft_version"] == version + 1
    used = {i["category"]: i["normalized_name"] for i in body["used_items"]}
    assert used["GPU"] == gpu_b["normalized_name"]                  # 고른 GPU만 — 다른 GPU는 분석에 안 들어간다
    assert {p["part"] for p in body["parts"]} == set(used)
    assert body["compat"]["checks"] and body["computed_at"]
    saved = client.get(f"/pc/reviews/{draft['draft_id']}")
    assert saved.status_code == 200 and saved.json()["input"]["input_hash"] == body["input"]["input_hash"]


def test_items_without_a_price_are_listed_as_excluded_from_the_total(client, monkeypatch):
    draft = _draft(client, monkeypatch)
    _confirm_relation(client, draft["draft_id"], 1)
    body = client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis").json()
    no_price = [i for i in body["used_items"] if i["quote_price_type"] == "unknown"]
    assert {e["item_id"] for e in body["price_excluded"]} == {i["id"] for i in no_price}
    assert no_price and all("제외" in e["reason"] for e in body["price_excluded"])


def test_conditions_are_kept_and_reach_the_analysis(client, monkeypatch):
    _fake_extraction(monkeypatch, TWO_IMAGES)
    draft = _upload(client, ["a", "b"], conditions='{"purpose": "game", "resolution": "FHD_144"}').json()
    assert draft["conditions"]["purpose"] == "game"
    _confirm_relation(client, draft["draft_id"], draft["version"])
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
    assert client.post(url).status_code == 409                                        # 사진 관계를 확인하기 전에는 합쳐 분석하지 않는다
    _confirm_relation(client, body["draft_id"], body["version"])
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


# ── 사용자가 고치는 기능: 부품군 변경 · 삭제 · 직접 추가 ──────────────────────────────

def _patch(client, draft, *, edits=None, selected=None, version=None):
    body = {"expected_version": version or draft["version"], "items": edits or []}
    if selected is not None:
        body["selected_item_by_category"] = selected
    return client.patch(f"/pc/review-drafts/{draft['draft_id']}/items", json=body)


def test_user_can_delete_an_item_the_model_misread(client, monkeypatch):
    draft = _draft(client, monkeypatch)
    cpu = _items(draft, "CPU")[0]
    r = _patch(client, draft, edits=[{"id": cpu["id"], "delete": True}])
    assert r.status_code == 200, r.text
    body = r.json()
    assert _items(body, "CPU") == [] and "CPU" not in body["selected_item_by_category"]      # 기준 선택도 함께 사라진다
    assert {i["id"] for g in body["groups"] for i in [{"id": x} for x in g["item_ids"]]}.isdisjoint({cpu["id"]})
    assert body["version"] == 2


def test_deleting_the_selected_item_falls_back_to_the_next_one_in_that_category(client, monkeypatch):
    draft = _draft(client, monkeypatch)
    first, second = _items(draft, "GPU")
    assert draft["selected_item_by_category"]["GPU"] == first["id"]
    body = _patch(client, draft, edits=[{"id": first["id"], "delete": True}]).json()
    assert body["selected_item_by_category"]["GPU"] == second["id"]
    assert [i["selected_for_analysis"] for i in _items(body, "GPU")] == [True]


def test_user_can_move_an_item_to_the_right_category_and_it_is_rematched_there(client, monkeypatch):
    draft = _draft(client, monkeypatch)
    cpu = _items(draft, "CPU")[0]
    body = _patch(client, draft, edits=[{"id": cpu["id"], "category": "GPU"}]).json()
    moved = next(i for i in body["items"] if i["id"] == cpu["id"])
    assert moved["category"] == "GPU" and moved["user_edited"] is True
    assert "CPU" not in body["selected_item_by_category"]                                   # 옛 부품군의 기준 선택은 버린다
    assert moved["match_status"] in ("unmatched", "inferred")                               # CPU 이름이 GPU 카탈로그에서 확정될 수 없다
    assert _patch(client, body, edits=[{"id": cpu["id"], "category": "케이스지롱"}]).status_code == 422


def test_deleted_item_cannot_be_chosen_as_the_analysis_basis_in_the_same_request(client, monkeypatch):
    draft = _draft(client, monkeypatch)
    first, _second = _items(draft, "GPU")
    r = _patch(client, draft, edits=[{"id": first["id"], "delete": True}], selected={"GPU": first["id"]})
    assert r.status_code == 422


def test_user_can_add_a_part_the_model_missed(client, monkeypatch):
    draft = _draft(client, monkeypatch)
    r = client.post(f"/pc/review-drafts/{draft['draft_id']}/items", json={
        "expected_version": 1, "category": "파워", "raw_text": "Seasonic FOCUS GX-750 -1234567 140,000원"})
    assert r.status_code == 201, r.text
    body = r.json()
    added = _items(body, "파워")[0]
    assert added["normalized_name"] == "Seasonic FOCUS GX-750" and added["product_code"] == "1234567"
    assert added["quote_line_total"] == 140000 and added["user_edited"] is True and added["source_ids"] == ["manual"]
    assert body["selected_item_by_category"]["파워"] == added["id"] and added["selected_for_analysis"] is True
    assert body["sources"][-1]["type"] == "manual" and body["version"] == 2
    _confirm_relation(client, draft["draft_id"], body["version"])
    analysis = client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis").json()
    assert "파워" in {i["category"] for i in analysis["used_items"]}                        # 추가한 항목도 분석에 들어간다


def test_added_item_can_belong_to_one_uploaded_quote_and_bad_input_is_rejected(client, monkeypatch):
    draft = _two_quotes(client, monkeypatch)
    url = f"/pc/review-drafts/{draft['draft_id']}/items"
    ok = client.post(url, json={"expected_version": 1, "category": "케이스", "raw_text": "다크플래쉬 DLM21 RGB Mesh", "source_id": "source-1"})
    assert ok.status_code == 201
    assert any(i["category"] == "케이스" and i["source_ids"] == ["source-1"] for i in ok.json()["items"])
    assert client.post(url, json={"expected_version": 2, "category": "케이스", "raw_text": "x", "source_id": "nope"}).status_code == 422
    assert client.post(url, json={"expected_version": 2, "category": "모니터", "raw_text": "x"}).status_code == 422
    assert client.post(url, json={"expected_version": 1, "category": "케이스", "raw_text": "x"}).status_code == 409     # 버전이 지났다


def test_an_uncertain_reading_is_never_confirmed_and_the_quote_total_is_kept(client, monkeypatch):
    """흐린 글자로 읽은 이름은 카탈로그 제품으로 확정하지 않고(제품 확인 필요), 사진에 적힌 총액은 그 견적(source)에 남는다."""
    class Found(list):
        quote_total = 2_280_000
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: True)
    monkeypatch.setattr(spec_extraction_agent, "extract_items_from_image", lambda _url: Found([
        {"category": "CPU", "raw_text": "AMD Ryzen 5 7500F"},
        {"category": "CPU", "raw_text": "AMD Ryzen 5 7500F", "uncertain": True}]))
    body = _upload(client, ["x"]).json()
    cpu = _items(body, "CPU")
    assert body["sources"][0]["quote_total"] == 2_280_000
    assert any(i["match_status"] != "confirmed" and i.get("uncertain") for i in cpu)


def test_two_full_builds_are_hinted_as_separate_quotes_and_one_split_quote_as_single(client, monkeypatch):
    """부품군이 5개 이상 보이는 사진이 둘 이상이면 서로 다른 견적(separate), 한 견적을 나눠 찍은 것 같으면 single 이 기본 선택이다."""
    full = lambda tag: [{"category": c, "raw_text": f"{c} {tag}"} for c in ("CPU", "GPU", "RAM", "메인보드", "저장장치", "파워")]    # noqa: E731
    _fake_extraction(monkeypatch, {"a": full("A"), "b": full("B")})
    assert _upload(client, ["a", "b"]).json()["source_mode_hint"] == "separate"
    _fake_extraction(monkeypatch, {"a": [{"category": "CPU", "raw_text": "R5 7500F"}, {"category": "GPU", "raw_text": "RTX 4060"}],
                                   "b": [{"category": "RAM", "raw_text": "DDR5 16GB"}, {"category": "파워", "raw_text": "600W"}]})
    assert _upload(client, ["a", "b"]).json()["source_mode_hint"] == "single"


def test_accessory_lines_are_left_out_of_the_analysis_and_reported_on_their_source(client, monkeypatch):
    """튜닝 킷·케이블 같은 줄은 부품군으로 억지 분류하지 않고 분석에서 빼며, 어떤 줄을 뺐는지 그 사진(source)에 남긴다."""
    _fake_extraction(monkeypatch, {"a": [{"category": "CPU", "raw_text": "AMD Ryzen 5 7500F"},
                                         {"category": "RAM", "raw_text": "램 튜닝 킷 (방열판)"},
                                         {"category": "기타", "raw_text": "알 수 없는 액세서리"}]})
    body = _upload(client, ["a"]).json()
    assert [i["category"] for i in body["items"]] == ["CPU"]
    assert body["sources"][0]["ignored_lines"] == ["램 튜닝 킷 (방열판)", "알 수 없는 액세서리"]


def test_a_low_quality_photo_gets_a_warning_and_nothing_from_it_is_confirmed(client, monkeypatch):
    """작거나 흐린 사진은 안내를 붙이고, 그 사진에서 읽은 부품은 카탈로그로 확정하지 않는다(분석은 한다)."""
    from src.engine import image_prep
    monkeypatch.setattr(image_prep, "assess_quality", lambda data: {"low": True, "reason": "blurry", "width": 1000, "blur": 300.0})
    _fake_extraction(monkeypatch, {"a": [{"category": "CPU", "raw_text": "AMD Ryzen 5 7500F"}]})
    body = _upload(client, ["a"]).json()
    assert "흐려" in body["sources"][0]["quality_warning"]
    assert all(i["match_status"] != "confirmed" for i in body["items"]) and body["items"][0]["uncertain"] is True


def test_a_clear_photo_has_no_warning_and_no_ignored_lines(client, monkeypatch):
    _fake_extraction(monkeypatch, {"a": [{"category": "CPU", "raw_text": "AMD Ryzen 5 7500F"}]})
    source = _upload(client, ["a"]).json()["sources"][0]
    assert source["quality_warning"] is None and source["ignored_lines"] == []


def test_a_blurry_photo_that_was_read_clearly_keeps_its_warning_but_may_still_be_confirmed(client, monkeypatch):
    from src.engine import image_prep
    monkeypatch.setattr(image_prep, "assess_quality", lambda data: {"low": True, "reason": "blurry", "width": 1000, "blur": 300.0})
    full = [{"category": c, "raw_text": t} for c, t in (("CPU", "AMD Ryzen 5 7500F"), ("GPU", "RTX 4060"), ("RAM", "DDR5 16GB"),
                                                        ("파워", "600W"), ("케이스", "빈 케이스"))]
    _fake_extraction(monkeypatch, {"a": full})
    source = _upload(client, ["a"]).json()["sources"][0]
    assert "흐려" in source["quality_warning"] and "자동으로 확정하지 않고" not in source["quality_warning"]


def test_each_item_carries_the_reason_it_was_not_confirmed(client, monkeypatch):
    """확정된 항목은 이유가 없고, 카탈로그에 없는 항목은 not_in_catalog 로 이유가 붙는다. 사용자가 이름을 고치면 이유도 다시 계산한다."""
    _fake_extraction(monkeypatch, {"a": [{"category": "CPU", "raw_text": "Intel Core i5-14600K"},
                                         {"category": "케이스", "raw_text": "1stPlayer Mi5 WING"}]})
    body = _upload(client, ["a"]).json()
    cpu, case = _items(body, "CPU")[0], _items(body, "케이스")[0]
    assert cpu["match_status"] == "confirmed" and cpu["match_reason"] is None
    assert case["match_reason"]["code"] == "not_in_catalog" and "같은 모델이 없어요" in case["match_reason"]["message"]
    url = f"/pc/review-drafts/{body['draft_id']}/items"
    fixed = client.patch(url, json={"expected_version": body["version"], "items": [{"id": case["id"], "normalized_name": "NZXT H5 Flow"}]}).json()
    fixed_case = _items(fixed, "케이스")[0]
    assert fixed_case["match_status"] == "confirmed" and fixed_case["match_reason"] is None


def test_a_photo_flagged_as_low_quality_gets_the_low_quality_reason(client, monkeypatch):
    from src.engine import image_prep
    monkeypatch.setattr(image_prep, "assess_quality", lambda data: {"low": True, "reason": "blurry", "width": 1000, "blur": 300.0})
    _fake_extraction(monkeypatch, {"a": [{"category": "CPU", "raw_text": "Intel Core i5-14600K"}]})
    item = _items(_upload(client, ["a"]).json(), "CPU")[0]
    assert item["match_status"] == "candidate" and item["match_reason"]["code"] == "low_quality_photo"
    assert item["match_reason"]["candidates"][0]["name"] == "Intel Core i5-14600K"


def _patch_conditions(client, draft_id, version, conditions):
    return client.patch(f"/pc/review-drafts/{draft_id}/conditions", json={"expected_version": version, "conditions": conditions})


def test_conditions_are_patched_partially_and_null_clears_one(client, monkeypatch):
    _fake_extraction(monkeypatch, {"a": [{"category": "CPU", "raw_text": "Intel Core i5-14600K"}]})
    created = _upload(client, ["a"], conditions='{"purpose":"game","resolution":"QHD_165","budget_max":2500000}').json()
    assert created["conditions"] == {"purpose": "game", "resolution": "QHD_165", "budget_max": 2500000} and created["analysis_stale"] is False
    patched = _patch_conditions(client, created["draft_id"], created["version"], {"resolution": "4K", "priority": "performance"}).json()
    assert patched["conditions"] == {"purpose": "game", "resolution": "4K", "budget_max": 2500000, "priority": "performance"}
    assert patched["version"] == created["version"] + 1
    cleared = _patch_conditions(client, created["draft_id"], patched["version"], {"budget_max": None, "games": []}).json()
    assert "budget_max" not in cleared["conditions"] and cleared["conditions"]["purpose"] == "game"


def test_changing_conditions_after_an_analysis_marks_the_result_stale(client, monkeypatch):
    _fake_extraction(monkeypatch, {"a": [{"category": "CPU", "raw_text": "Intel Core i5-14600K"}]})
    created = _upload(client, ["a"], conditions='{"purpose":"game","resolution":"QHD_165"}').json()
    assert client.post(f"/pc/review-drafts/{created['draft_id']}/analysis", json={}).status_code == 200
    assert client.get(f"/pc/review-drafts/{created['draft_id']}").json()["analysis_stale"] is False        # 분석 직후엔 오래되지 않았다
    patched = _patch_conditions(client, created["draft_id"], created["version"], {"resolution": "4K"}).json()
    assert patched["analysis_stale"] is True
    assert client.post(f"/pc/review-drafts/{created['draft_id']}/analysis", json={}).status_code == 200
    assert client.get(f"/pc/review-drafts/{created['draft_id']}").json()["analysis_stale"] is False        # 다시 분석하면 풀린다


def test_a_conditions_patch_rejects_a_stale_version_a_bad_value_and_someone_elses_draft(client, monkeypatch):
    _fake_extraction(monkeypatch, {"a": [{"category": "CPU", "raw_text": "Intel Core i5-14600K"}]})
    created = _upload(client, ["a"]).json()
    assert _patch_conditions(client, created["draft_id"], created["version"] + 5, {"purpose": "game"}).status_code == 409
    assert _patch_conditions(client, created["draft_id"], created["version"], {"purpose": "spaceship"}).status_code == 422
    with TestClient(app) as other:
        assert _patch_conditions(other, created["draft_id"], created["version"], {"purpose": "game"}).status_code == 404


def test_the_draft_reports_how_the_photos_relate_and_the_user_can_overrule_it(client, monkeypatch):
    full = lambda tag: [{"category": c, "raw_text": f"{c} {tag}"} for c in ("CPU", "GPU", "RAM", "메인보드", "파워", "케이스")]    # noqa: E731
    _fake_extraction(monkeypatch, {"a": full("A"), "b": full("B")})
    body = _upload(client, ["a", "b"]).json()
    relation = body["source_relation"]
    assert relation["applies"] and relation["mode"] == "separate" and relation["confidence"] == "high" and relation["confirmed"] is False
    assert body["source_mode_hint"] == "separate"
    flipped = client.patch(f"/pc/review-drafts/{body['draft_id']}/source-relation", json={"expected_version": body["version"], "mode": "single"}).json()
    assert flipped["source_relation"]["mode"] == "single" and flipped["source_relation"]["confirmed"] is True and flipped["version"] == body["version"] + 1


def test_separate_quotes_cannot_be_analysed_as_one_but_one_quote_can_be_picked(client, monkeypatch):
    full = lambda tag: [{"category": c, "raw_text": f"{c} {tag}"} for c in ("CPU", "GPU", "RAM", "메인보드", "파워", "케이스")]    # noqa: E731
    _fake_extraction(monkeypatch, {"a": full("A"), "b": full("B")})
    body = _upload(client, ["a", "b"]).json()
    url = f"/pc/review-drafts/{body['draft_id']}/analysis"
    refused = client.post(url)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "source_relation_separate"
    assert client.post(url, json={"source_ids": ["source-1"]}).status_code == 200            # 한 견적을 골라 분석하는 것은 된다


def test_an_unclear_relation_blocks_plain_analysis_until_the_user_confirms(client, monkeypatch):
    body = _two_quotes(client, monkeypatch)                         # 같은 부품군(GPU)에 서로 다른 제품이 하나뿐 — 근거가 약하다
    assert body["source_relation"]["confidence"] == "low"
    refused = client.post(f"/pc/review-drafts/{body['draft_id']}/analysis")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "source_relation_unconfirmed"


def test_a_single_photo_has_no_relation_to_confirm(client, monkeypatch):
    _fake_extraction(monkeypatch, {"a": [{"category": "CPU", "raw_text": "Intel Core i5-14600K"}]})
    body = _upload(client, ["a"]).json()
    assert body["source_relation"]["applies"] is False
    assert client.patch(f"/pc/review-drafts/{body['draft_id']}/source-relation", json={"expected_version": body["version"], "mode": "single"}).status_code == 422
    assert client.post(f"/pc/review-drafts/{body['draft_id']}/analysis").status_code == 200


def _analysis_of(client, monkeypatch, entries, total=None):
    class Found(list):
        quote_total = total
    monkeypatch.setattr(spec_extraction_agent, "available", lambda: True)
    monkeypatch.setattr(spec_extraction_agent, "extract_items_from_image", lambda _url: Found(entries))
    draft = _upload(client, ["x"]).json()
    return client.post(f"/pc/review-drafts/{draft['draft_id']}/analysis").json()


def test_price_view_says_no_price_information_instead_of_zero(client, monkeypatch):
    view = _analysis_of(client, monkeypatch, [{"category": "CPU", "raw_text": "Intel Core i5-14600K"}])["price_view"]
    assert view["mode"] == "none" and view["label"] == "가격 정보 없음" and view["line_total"] is None and view["quote_total"] is None


def test_price_view_uses_the_photo_total_when_only_the_total_is_written(client, monkeypatch):
    view = _analysis_of(client, monkeypatch, [{"category": "CPU", "raw_text": "Intel Core i5-14600K"}], total=2_280_000)["price_view"]
    assert view["mode"] == "total_only" and view["label"] == "사진 총액" and view["quote_total"] == 2_280_000 and view["line_total"] is None


def test_price_view_counts_only_the_priced_parts_when_some_have_no_price(client, monkeypatch):
    entries = [{"category": "CPU", "raw_text": "Intel Core i5-14600K 331,500원"}, {"category": "GPU", "raw_text": "NVIDIA GeForce RTX 4060"}]
    view = _analysis_of(client, monkeypatch, entries)["price_view"]
    assert view["mode"] == "line" and view["priced_count"] == 1 and view["total_count"] == 2 and view["line_total"] == 331_500
    assert "1개의 합계" in view["label"] and "가격 정보가 없어" in view["note"]
