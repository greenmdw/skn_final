"""예시 글 정답표(data/community_examples/expectations.yaml) — 파일 자체의 검사와 비교 함수의 동작. DB·모델 호출 없음.

분석 결과가 정답표와 맞는지는 `scripts/check_example_expectations.py` 가 실제 DB 로 본다(언어 모델 결과라 시험 환경에서는 못 돈다).
여기서는 (1) 정답표 파일이 설정·글 파일과 어긋나지 않는지, (2) 비교 함수가 위반을 제대로 잡는지를 확인한다."""
from __future__ import annotations

from pathlib import Path

import yaml

from src.engine import peripheral_post_expectations as ex
from src.engine.peripheral_post_text import plain_text
from src.engine.peripheral_rules import load_peripheral_rules

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "data" / "community_examples"
EXPECT = EXAMPLES / "expectations.yaml"
DATA = ex.load_expectations(EXPECT)


# ── 정답표 파일 ─────────────────────────────────────────────────────────────
def _front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return yaml.safe_load(text.split("\n---\n", 1)[0].removeprefix("---\n"))


def _post_files() -> dict[str, Path]:
    """글 파일(머리말이 있는 .md). 묶음 폴더의 README.md 같은 안내 문서는 글이 아니다."""
    out = {}
    for path in EXAMPLES.glob("[A-F]/*.md"):
        if path.name.lower() == "readme.md" or not path.read_text(encoding="utf-8").startswith("---"):
            continue
        out[_front_matter(path)["id"]] = path
    return out


def test_expectation_attributes_and_values_exist_in_config():
    attributes = load_peripheral_rules()["feel"]["attributes"]["mouse"]
    assert ex.validate_expectations(DATA, attributes) == []


def test_every_expected_post_has_a_file_and_the_same_product():
    files = _post_files()
    for pid, spec in DATA["posts"].items():
        assert pid in files, f"{pid}: 글 파일이 없다"
        products = _front_matter(files[pid])["products"]
        assert f"{products[0]['brand']} {products[0]['model']}" == spec["product"], pid


def test_each_product_has_four_expected_posts_and_a_negative_must_has_a_matching_post_type():
    from collections import Counter
    counts = Counter(spec["product"] for spec in DATA["posts"].values())
    assert set(counts.values()) == {4}, counts


def test_no_evidence_posts_are_not_scored_posts():
    assert all(p.startswith("F") for p in DATA["no_evidence"])
    assert "F12" not in DATA["no_evidence"]        # F12 는 원글이 사용기이고 수정 뒤에만 근거가 사라진다(다른 점검)


def test_durability_allowed_posts_state_six_months_or_more():
    files = _post_files()
    for pid in DATA["durability_allowed"]:
        title = _front_matter(files[pid])["title"]
        assert "개월" in title or "년" in title, pid


# ── 비교 함수 ───────────────────────────────────────────────────────────────
def _row(post, attribute, direction=None, side=None, **kw):
    return {"post_id": post, "attribute": attribute, "direction": direction, "side": side, "sentence": kw.pop("sentence", "문장"),
            "hand_size": kw.pop("hand_size", None), "purposes": kw.pop("purposes", []), "situations": kw.pop("situations", []), **kw}


def test_check_post_counts_hits_misses_and_conflicts():
    rows = [_row("A1", "grip", "good"), _row("A1", "weight_feel", side="light"), _row("A1", "battery", "bad")]
    r = ex.check_post("A1", rows, {"grip": "good", "weight_feel": "light", "battery": "good", "wheel": "good"}, {"battery": "bad"})
    assert r.hits == [("grip", "good"), ("weight_feel", "light")]
    assert r.misses == [("battery", "good"), ("wheel", "good")]
    assert r.conflicts == [("battery", "bad")]
    assert ex.coverage([r]) == (2, 4)


def test_a_list_value_requires_every_direction():
    rows = [_row("A8-4", "battery", "good")]
    r = ex.check_post("A8-4", rows, {"battery": ["good", "bad"]})
    assert r.hits == [("battery", "good")] and r.misses == [("battery", "bad")]


def test_check_posts_skips_posts_not_in_scope():
    expected = {"A1": {"must": {"grip": "good"}}, "A2": {"must": {"grip": "good"}}}
    got = ex.check_posts({"A1": [_row("A1", "grip", "good")]}, expected, only={"A1"})
    assert [r.post_id for r in got] == ["A1"] and ex.coverage(got) == (1, 1)


def test_posts_that_must_have_no_evidence_are_reported_when_scored():
    rows = ex.group_by_post([_row("F9", "grip", "good"), _row("F9", "other"), _row("A1", "grip", "good")])
    assert ex.check_no_evidence(rows, ["F9", "F10"]) == [("F9", 2)]


def test_conditions_are_hidden_only_for_minus_four_posts():
    rows = ex.group_by_post([
        _row("A1-4", "grip", "good"),                                          # 문제 없음
        _row("A2-4", "grip", "good", purposes=["wrist"]),                      # 목적이 잡혔다
        _row("A3-4", "grip", "good", hand_size="large"),                       # 손 크기가 잡혔다
        _row("A4-4", "grip", "good", situations=["mic"]),                      # 문장 속 상황은 허용
        _row("A1-1", "grip", "good", hand_size="medium", purposes=["fps"]),    # -4 가 아니면 상관없다
    ])
    assert ex.check_conditions_hidden(rows) == [("A2-4", "purposes"), ("A3-4", "hand_size")]
    assert ("A4-4", "situations") in ex.check_conditions_hidden(rows, include_situations=True)


def test_durability_is_allowed_only_for_long_use_posts():
    rows = ex.group_by_post([_row("A2-1", "durability", "good"), _row("A3-1", "durability", "good"), _row("A4-1", "grip", "good")])
    assert ex.check_durability(rows, ["A2-1"]) == ["A3-1"]


def test_speculation_sentences_are_flagged_but_plain_experience_is_not():
    rows = ex.group_by_post([
        _row("A1", "weight_feel", side="light", sentence="손이 더 크다면 높이 40mm가 낮게 느껴질 수 있을 것 같습니다."),
        _row("A2", "side_button", "good", sentence="버튼 구성은 마음에 들어서 선만 없다면 계속 썼을 것 같습니다."),
        _row("A3", "grip", "good", sentence="클로로 쥐었을 때 손바닥 뒤쪽이 적당히 받쳐 줍니다."),
        _row("A4", "battery", "good", sentence="4주 동안 충전을 거의 신경 쓰지 않았습니다."),
    ])
    assert sorted(p for p, _, _ in ex.find_speculation(rows)) == ["A1", "A2"]


def test_sentence_check_runs_on_plain_text_so_markup_does_not_break_it():
    bodies = {"A1": "## 소제목\n\n**그립이 손에 착 감겨서 안정적입니다.** 무게는 63g입니다.\n\n![사진](image:abc)\n"}
    rows = ex.group_by_post([_row("A1", "grip", "good", sentence="그립이 손에 착 감겨서 안정적입니다."),
                             _row("A1", "grip", "good", sentence="본문에 없는 문장입니다.")])
    assert ex.check_sentences_in_body(rows, bodies, plain_text) == [("A1", "본문에 없는 문장입니다.")]


def test_validate_expectations_reports_unknown_attribute_and_bad_value():
    attributes = {"grip": {"type": "rating"}, "weight_feel": {"type": "taste", "sides": {"light": "가벼움", "heavy": "묵직"}}}
    data = {"posts": {"A1": {"must": {"grip": "great", "weight_feel": "light", "nope": "good"}}}}
    problems = ex.validate_expectations(data, attributes)
    assert len(problems) == 2 and any("nope" in p for p in problems) and any("great" in p for p in problems)
