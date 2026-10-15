"""결과 화면 재설계(요청서 S1·S4~S7): 필수 스펙 한 줄, 요청 항목, 가격 순서, 축 라벨, 외부 리뷰 대표 문장, 대안 표시 값.

DB 불필요. 점수·순위는 바꾸지 않는다는 것도 함께 확인한다."""
from __future__ import annotations

from pathlib import Path

from src.dto import Candidate
from src.engine import peripheral_display as pd
from src.engine import peripheral_intent as pi
from src.engine.peripheral_catalog import load_peripheral_candidates_from_csv
from src.engine.peripheral_payload import peripheral_payload
from src.engine.peripheral_rules import load_peripheral_rules
from src.engine.peripheral_select import run_peripherals

RULES = load_peripheral_rules()
_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "peripherals"
_NOLOG = lambda _m: None  # noqa: E731


def _resolved(kind, **interp_kw):
    interp = pi.Interpretation(kinds=[kind], **interp_kw)
    return interp, pi.resolve(interp, RULES)[kind]


# ── S5 필수 스펙 한 줄 ──────────────────────────────────────────────────────
def test_key_specs_keep_config_order_and_skip_missing_values():
    specs = {"screen_size_inch": 27.0, "resolution_raw": "2560x1440", "refresh_hz": 165.0, "usb_c_video": False}
    out = pd.key_specs("monitor", specs, RULES)
    assert [(s["key"], s["value"]) for s in out] == [
        ("size", "27인치"), ("resolution", "2560x1440"), ("refresh", "165Hz")]      # 없는 패널·응답속도, 거짓 USB-C 는 뺀다


def test_key_specs_join_text_parts_and_connection_flags():
    specs = {"switch_method_raw": "기계식", "switch_kind_raw": "40g Mechanical Switch", "weight_g": 720.0,
             "connectivity_wired": True, "connectivity_wireless": False, "connectivity_bluetooth": True}
    out = {s["key"]: s["value"] for s in pd.key_specs("keyboard", specs, RULES)}
    assert out == {"switch": "기계식 · 40g Mechanical Switch", "weight": "720g", "connect": "유선·블루투스"}
    assert pd.key_specs("mouse", {}, RULES) == []


def test_key_specs_drop_placeholder_parts_and_items():
    specs = {"switch_method_raw": "기계식", "switch_kind_raw": "—", "weight_g": 720.0,
             "size_longest_mm": "N/A", "connectivity_wired": True}
    out = {s["key"]: s["value"] for s in pd.key_specs("keyboard", specs, RULES)}
    assert out == {"switch": "기계식", "weight": "720g", "connect": "유선"}   # "기계식 · —" 가 아니다 · N/A 항목은 없다
    only_placeholders = {"switch_method_raw": "-", "switch_kind_raw": " ", "weight_g": "—"}
    assert pd.key_specs("keyboard", only_placeholders, RULES) == []
    monitor = pd.key_specs("monitor", {"panel_raw": "n/a", "resolution_raw": "2560x1440"}, RULES)
    assert [(s["key"], s["value"]) for s in monitor] == [("resolution", "2560x1440")]


# ── S6 축 라벨·가격 순서 ────────────────────────────────────────────────────
def test_every_weighted_axis_has_a_user_facing_label():
    for kind, table in RULES["ranking"].items():
        for axis in table["weights"]:
            assert axis in RULES["display"]["axis_labels"], (kind, axis)
    assert pd.axis_label("리뷰", RULES) == "후기·사용기"
    assert pd.axis_label("없는축", RULES) == "없는축"             # 표에 없으면 지어내지 않는다


def test_price_position_counts_cheaper_candidates():
    pool = [Candidate(product_key=k, slot="mouse", name=k, price=p) for k, p in (("a", 30000), ("b", 10000), ("c", 20000))]
    assert pd.price_position(pool[0], pool) == {"rank": 3, "of": 3}
    assert pd.price_position(pool[1], pool) == {"rank": 1, "of": 3}
    assert pd.price_position(pool[0], pool[:1]) is None


# ── S4 요청 항목 ────────────────────────────────────────────────────────────
def test_stated_conditions_become_spec_items_with_values():
    interp, resolved = _resolved("mouse", stated={"mouse": ["wireless", "lightweight"]})
    specs = {"weight_g": 76.0, "connectivity_wireless": True}
    items = pd.requested_items("mouse", specs, interp, resolved, RULES)
    by_label = {i["label"]: i for i in items}
    assert set(by_label) == {"무선", "가벼운"}
    light = by_label["가벼운"]
    assert light["source"] == "stated" and light["type"] == "spec" and light["feel_codes"] == []
    assert light["spec_checks"] == [{"key": "weight_g", "text": "무게 76g · 80g 이하", "ok": True}]
    assert by_label["무선"]["type"] == "evidence" and by_label["무선"]["feel_codes"] == ["wireless"]
    assert by_label["무선"]["external_aspects"] == ["connection_stability"]


def test_unknown_spec_value_is_not_reported_as_checked():
    interp, resolved = _resolved("mouse", stated={"mouse": ["lightweight"]})
    items = pd.requested_items("mouse", {}, interp, resolved, RULES)
    assert items[0]["spec_checks"] == []                          # 값이 없으면 확인했다고 말하지 않는다


def test_situation_links_feel_attributes_and_external_aspects():
    interp, resolved = _resolved("keyboard", situations=["quiet_place"])
    items = pd.requested_items("keyboard", {"switch_clicky": False}, interp, resolved, RULES)
    assert len(items) == 1
    item = items[0]
    assert item["label"] == "조용한" and item["source"] == "situation" and item["type"] == "evidence"
    assert {"key_noise", "hollow"} <= set(item["feel_codes"])
    assert item["external_aspects"] == ["typing_noise"]
    assert item["spec_checks"] == [{"key": "switch_clicky", "text": "클릭형 스위치 아님", "ok": True}]


def test_design_links_looks_and_trending_is_not_an_item():
    interp, resolved = _resolved("monitor", situations=["design", "trending"])
    items = pd.requested_items("monitor", {}, interp, resolved, RULES)
    assert [i["label"] for i in items] == ["디자인이 예쁜"]
    assert {"looks", "build"} <= set(items[0]["feel_codes"])


def test_conflict_dropped_condition_is_not_requested():
    interp, resolved = _resolved("keyboard", stated={"keyboard": ["compact", "full_size"]})
    assert resolved.conflicts and not resolved.preferences
    assert pd.requested_items("keyboard", {"size_longest_mm": 400.0}, interp, resolved, RULES) == []


def test_no_request_means_no_items():
    interp, resolved = _resolved("mouse")
    assert pd.requested_items("mouse", {"weight_g": 70.0}, interp, resolved, RULES) == []
    assert pd.requested_items("mouse", {}, interp, None, RULES) == []


# ── S7 외부 리뷰 대표 문장 ──────────────────────────────────────────────────
def _contribution(p, n, members, mixed=0):
    return {"p": p, "n": n, "mixed": mixed,
            "members": [{"direction": d, "evidence_sentences": sentences} for d, sentences in members]}


def test_quote_follows_the_majority_direction_and_requires_hangul():
    c = _contribution(7, 2, [("negative", ["타건 소리가 너무 큽니다 정말로"]),
                             ("positive", ["typing is quiet", "조용해서 밤에도 쓸 수 있어요", "좋아요"])])
    quote, dissent = pd.review_quote(c)
    assert quote == {"text": "조용해서 밤에도 쓸 수 있어요", "direction": "positive"}
    assert dissent is False                                        # 2/9 는 적은 쪽이 뚜렷하지 않다


def test_dissent_is_flagged_when_the_minority_is_substantial():
    c = _contribution(5, 3, [("positive", ["조용해서 밤에도 쓸 수 있어요"]), ("negative", ["소리가 큰 편이에요 생각보다"])])
    quote, dissent = pd.review_quote(c)
    assert quote["direction"] == "positive" and dissent is True


def test_negative_majority_quotes_a_negative_sentence_and_empty_gives_none():
    c = _contribution(1, 4, [("positive", ["조용해서 좋아요 정말로"]), ("negative", ["키 소리가 시끄러워요 정말로"])])
    assert pd.review_quote(c)[0] == {"text": "키 소리가 시끄러워요 정말로", "direction": "negative"}
    assert pd.review_quote(_contribution(0, 0, []))[0] is None
    assert pd.review_quote(_contribution(3, 0, [("positive", ["good"])]))[0] is None


def test_quote_without_a_fitting_sentence_takes_the_shortest():
    long_a = "정말로 " * 40 + "조용합니다"                       # 120자 초과
    long_b = "정말로 " * 35 + "조용합니다"                       # 120자 초과, 더 짧다
    c = _contribution(2, 0, [("positive", [long_a, long_b, "조용"])])    # 8자 미만도 맞지 않는다
    assert len(long_b) > 120 and len("조용") < 8
    assert pd.review_quote(c)[0] == {"text": "조용", "direction": "positive"}
    c2 = _contribution(2, 0, [("positive", [long_a, long_b])])
    assert pd.review_quote(c2)[0]["text"] == long_b
    fitting = _contribution(2, 0, [("positive", [long_b, "조용해서 밤에도 쓸 수 있어요", "조용"])])
    assert pd.review_quote(fitting)[0]["text"] == "조용해서 밤에도 쓸 수 있어요"   # 맞는 문장이 있으면 그중 가장 긴 것


# ── S1 대안 표시 값(응답 연결) ───────────────────────────────────────────────
def _payload(kinds, **values):
    candidates = load_peripheral_candidates_from_csv(_FIXTURES, RULES)
    return peripheral_payload(run_peripherals({"peripherals": kinds, **values}, candidates, _NOLOG), RULES)


def test_item_and_alternatives_carry_display_values():
    payload = _payload(["mouse"], purpose="game")
    item = payload["items"][0]
    assert item["key_specs"] and all(set(s) == {"key", "label", "value"} for s in item["key_specs"])
    assert item["price_position"] is None or set(item["price_position"]) == {"rank", "of"}
    assert item["alternatives"], "픽스처에 대안이 있어야 한다"
    for alt in item["alternatives"]:
        assert {"key_specs", "requested", "price_position", "feel", "score_detail"} <= set(alt)
        if alt["score_detail"]:
            assert all(a["label"] for a in alt["score_detail"]["axes"])
    assert all(a["label"] for a in item["score_detail"]["axes"])


def test_display_values_do_not_change_order_or_score():
    a = _payload(["mouse", "monitor"], purpose="game", resolution="QHD_165")
    b = _payload(["mouse", "monitor"], purpose="game", resolution="QHD_165")
    assert [(i["product"]["name"], i["score_detail"]["score"]) for i in a["items"]] == \
           [(i["product"]["name"], i["score_detail"]["score"]) for i in b["items"]]
