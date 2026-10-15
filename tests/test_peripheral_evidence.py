"""체감 근거 표시(개발_확정사양 6.6, 7장): 문구, 인용 문장, 최근 사용기 수, 요즘 많이 쓰는 순서, 문장 검색.

계산 값은 `peripheral_feel` 이 정하고 이 테스트는 그것을 사람이 읽는 말로 바꾸는 규칙만 확인한다. DB 불필요."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.dto import (
    Candidate, FeelAttributeDetail, FeelDetail, ReviewAspectContribution, ReviewRequirementProfile, ReviewScoreDetail,
)
from src.engine import peripheral_evidence as ev
from src.engine import peripheral_intent as pi
from src.engine import peripheral_search as ps
from src.engine.peripheral_feel import FeelObservation as Obs
from src.engine.peripheral_feel import compute_feel
from src.engine.peripheral_rules import load_peripheral_rules
from src.engine.peripheral_select import apply_trending, run_peripherals

RULES = load_peripheral_rules()
NOW = datetime(2026, 10, 12)
MANY = RULES["feel"]["same_condition_many"]


def _detail(**kw) -> FeelAttributeDetail:
    base = dict(code="grip", label="그립 안정감", type="rating", alpha=0.2, value=0.7, state="same_condition")
    base.update(kw)
    return FeelAttributeDetail(**base)


def _text(detail, phrase="손이 큰 사용자", attr_def=None):
    return ev.attribute_text(detail, attr_def or {}, phrase, MANY)


# ── 문구(사양 7장 표) ─────────────────────────────────────────────────────
def test_many_same_condition_authors_show_counts_directly():
    state, text = _text(_detail(same_good=4, same_bad=1))
    assert state == "same_condition"
    assert text == "손이 큰 사용자 5명 중 4명이 좋게 평가했습니다"


def test_few_same_condition_authors_say_evidence_is_thin():
    state, text = _text(_detail(same_good=1, same_bad=1))
    assert state == "few_same_condition"
    assert text == "손이 큰 사용자 2명 중 1명 · 근거가 적습니다"


def test_only_other_condition_authors_say_so():
    state, text = _text(_detail(state="other_condition", rest_good=10, rest_bad=2))
    assert state == "other_condition"
    assert text == "전체 12명 중 10명 · 손이 큰 사용자의 글은 아직 없습니다"


def test_other_condition_without_a_requested_condition_is_plain_total():
    state, text = _text(_detail(state="other_condition", rest_good=3, rest_bad=1), phrase=None)
    assert state == "all_authors" and text == "전체 4명 중 3명이 좋게 평가했습니다"


def test_split_rating_shows_both_sides():
    state, text = _text(_detail(rest_good=3, rest_bad=2, state="other_condition", split=True,
                                side_counts={"good": 3, "bad": 2}))
    assert state == "split" and text == "의견이 갈립니다 (좋음 3명 · 아쉬움 2명)"


def test_split_taste_shows_people_per_side():
    d = _detail(type="taste", code="sound_volume", rest_good=3, rest_bad=1, state="other_condition", split=True,
                side_counts={"quiet": 3, "loud": 1})
    attr_def = {"sides": {"quiet": "조용한 편", "loud": "큰 편"}}
    assert _text(d, attr_def=attr_def) == ("split", "성향 평가가 갈립니다 (조용한 편 3명 · 큰 편 1명)")


def test_mismatch_and_external_only_and_no_evidence():
    assert _text(_detail(type="taste", rest_bad=9, rest_good=1, state="other_condition", mismatch=True)) == (
        "mismatch", "고르신 취향과 다릅니다")
    assert _text(_detail(state="external_only")) == ("external_only", "외부 리뷰 기준")
    assert _text(_detail(state="no_evidence")) is None


def test_taste_uses_its_own_verb():
    state, text = _text(_detail(type="taste", same_good=3, same_bad=0))
    assert text.endswith("고르신 쪽이라고 했습니다")


# ── 블록 ──────────────────────────────────────────────────────────────────
def _block(detail, interp=None, kind="mouse"):
    interp = interp or pi.Interpretation(kinds=[kind])
    return ev.build_feel_block(detail, interp, pi.resolve(interp, RULES).get(kind), kind, RULES)


def test_block_is_none_when_nothing_to_show():
    detail = FeelDetail(value=0.5, attributes=[_detail(state="no_evidence")])
    assert _block(detail) is None
    assert _block(None) is None


def test_block_labels_the_basis_and_hides_zero_recent_authors():
    detail = FeelDetail(value=0.6, basis="example", recent_authors=0, attributes=[_detail(state="external_only")])
    block = _block(detail)
    assert block["basis_text"] == "예시 글 기준" and block["recent_authors"] is None
    assert block["attributes"][0]["text"] == "외부 리뷰 기준"
    with_recent = _block(detail.model_copy(update={"recent_authors": 4}))
    assert with_recent["recent_authors"] == 4


def test_block_uses_the_requesters_stated_condition_in_the_phrase():
    detail = FeelDetail(value=0.7, basis="community", attributes=[_detail(same_good=4, same_bad=1)])
    interp = pi.Interpretation(kinds=["mouse"], hand_size="large")
    block = _block(detail, interp)
    assert block["attributes"][0]["text"].startswith("손이 큰 사용자 5명 중 4명")


# ── 계산과의 연결: 인용 문장, 최근 사용기 수 ────────────────────────────────────
def _cand(key="A", pid="pid-A"):
    detail = ReviewScoreDetail(
        profile=ReviewRequirementProfile(profile_version="t", analysis_version="t", part_type="mouse"), value=0.5,
        contributions=[ReviewAspectContribution(aspect_code="ergonomics", context_code="actual_use", alpha=0.2,
                                                p=5, n=5, q=0.5, alpha_q=0.1, evidence_state="observed")])
    return Candidate(product_key=key, slot="mouse", name=key, product_id=pid, price=100, review_detail=detail)


def test_quotes_prefer_same_condition_then_recent_and_respect_the_limit():
    limit = RULES["feel"]["quotes_per_attribute"]
    obs = [
        Obs("u1", "pid-A", "grip", direction="good", hand_size="large", written_at=NOW - timedelta(days=5),
            post_id="p1", quote_id="q1", sentence="큰 손에 잘 맞습니다."),
        Obs("u2", "pid-A", "grip", direction="good", hand_size="small", written_at=NOW - timedelta(days=1),
            post_id="p2", quote_id="q2", sentence="작은 손에도 괜찮습니다."),
        Obs("u3", "pid-A", "grip", direction="good", hand_size="large", written_at=NOW - timedelta(days=30),
            post_id="p3", quote_id="q3", sentence="한참 써도 편합니다.", photo_url="https://img/3.jpg"),
        Obs("u4", "pid-A", "grip", direction="bad", hand_size="small", written_at=NOW - timedelta(days=60),
            post_id="p4", quote_id="q4", sentence="조금 미끄럽습니다."),
    ]
    interp = pi.Interpretation(kinds=["mouse"], hand_size="large")
    cand = _cand()
    out = compute_feel("mouse", [cand], [cand], interp, pi.resolve(interp, RULES)["mouse"], obs, RULES, now=NOW)
    grip = next(a for a in out["A"].attributes if a.code == "grip")
    ids = [q.quote_id for q in grip.quotes]
    assert ids == ["q1", "q3"][:limit]                        # 같은 조건(큰 손) 먼저, 그 안에서 최근 순
    assert grip.quotes[0].photo_url is None
    assert limit == 2 and len(ids) == 2


def test_one_post_is_quoted_only_once_per_product_across_attributes():
    """예시 글 한 편이 제품의 여러 면을 쓰므로, 속성마다 같은 글을 되풀이 인용하지 않는다(같은 글로 가는 '원문 보기'가 여러 개 보이던 문제)."""
    attrs = RULES["feel"]["attributes"]["mouse"]
    codes = [code for code, entry in attrs.items() if entry.get("type") == "rating"][:3]
    assert len(codes) >= 2
    obs = []
    for i, code in enumerate(codes):
        # 같은 글 p1 이 모든 속성에 문장을 갖고, 속성마다 다른 글 하나씩이 더 있다
        obs.append(Obs(f"u{i}a", "pid-A", code, direction="good", written_at=NOW - timedelta(days=1),
                       post_id="p1", quote_id=f"p1-{code}", sentence=f"p1 {code}"))
        obs.append(Obs(f"u{i}b", "pid-A", code, direction="good", written_at=NOW - timedelta(days=10 + i),
                       post_id=f"p-{code}", quote_id=f"x-{code}", sentence=f"{code} 다른 글"))
    interp = pi.Interpretation(kinds=["mouse"])
    cand = _cand()
    out = compute_feel("mouse", [cand], [cand], interp, pi.resolve(interp, RULES)["mouse"], obs, RULES, now=NOW)
    cited = [q.post_id for a in out["A"].attributes for q in a.quotes]
    assert len(cited) == len(set(cited)), cited                  # 어떤 글도 두 번 나오지 않는다
    assert all(len(a.quotes) <= RULES["feel"]["quotes_per_attribute"] for a in out["A"].attributes)
    first = next(a for a in out["A"].attributes if a.code == codes[0])
    assert [q.post_id for q in first.quotes][0] == "p1"          # 앞선 속성이 가장 최근 글을 먼저 가져간다


def test_recent_authors_counts_distinct_authors_within_the_window():
    obs = [
        Obs("u1", "pid-A", "grip", direction="good", written_at=NOW - timedelta(days=10)),
        Obs("u1", "pid-A", "wrist", direction="good", written_at=NOW - timedelta(days=10)),   # 같은 사람 — 한 명
        Obs("u2", "pid-A", "grip", direction="good", written_at=NOW - timedelta(days=80)),
        Obs("u3", "pid-A", "grip", direction="good", written_at=NOW - timedelta(days=200)),   # 기간 밖
        Obs("u4", "pid-B", "grip", direction="good", written_at=NOW - timedelta(days=1)),     # 다른 제품
    ]
    interp = pi.Interpretation(kinds=["mouse"])
    a = _cand("A", "pid-A")
    out = compute_feel("mouse", [a], [a], interp, None, obs, RULES, now=NOW)
    assert out["A"].recent_authors == 2


# ── 요즘 많이 쓰는 ────────────────────────────────────────────────────────
def _scored(key, score, recent):
    c = Candidate(product_key=key, slot="mouse", name=key, price=100, score=score, rank=0)
    return c.model_copy(update={"feel_detail": FeelDetail(value=0.5, recent_authors=recent)})


def test_trending_reorders_only_within_the_score_margin():
    margin = RULES["feel"]["trending_margin"]
    ranked = [_scored("top", 0.80, 1), _scored("close", 0.80 - margin / 2, 9), _scored("far", 0.80 - margin * 3, 50)]
    out = apply_trending(ranked, margin)
    assert [c.product_key for c in out] == ["close", "top", "far"]
    assert [c.rank for c in out] == [1, 2, 3]
    assert [c.score for c in out] == [0.80 - margin / 2, 0.80, 0.80 - margin * 3]      # 점수는 바꾸지 않는다


def test_trending_keeps_order_without_recent_posts_or_a_single_candidate():
    ranked = [_scored("a", 0.8, 0), _scored("b", 0.79, 0)]
    assert apply_trending(ranked, 0.02) == ranked
    assert apply_trending(ranked[:1], 0.02) == ranked[:1]


def test_run_peripherals_applies_trending_only_when_the_situation_is_stated():
    a = _cand("A", "pid-A")
    b = _cand("B", "pid-B")
    # 같은 평가(좋음 1표)라 R 이 같다. 다른 점은 B 의 글만 최근이라는 것뿐이다.
    obs = {"mouse": [Obs("u1", "pid-A", "grip", direction="good", written_at=datetime.now() - timedelta(days=400)),
                     Obs("u2", "pid-B", "grip", direction="good", written_at=datetime.now() - timedelta(days=3))]}

    def run(situations):
        interp = pi.Interpretation(kinds=["mouse"], situations=situations)
        values = {"peripherals": ["mouse"], "peripheral_intent": interp, "peripheral_resolved": pi.resolve(interp, RULES),
                  "peripheral_feel_observations": obs}
        return run_peripherals(values, {"mouse": [a, b]}, lambda *_: None).picks[0].candidate.product_key

    # 가격이 같아 점수가 같다: 기본 동점 규칙(product_key 오름차순)이면 A, 요즘 많이 쓰는이면 최근 글이 있는 B
    assert run([]) == "A"
    assert run(["trending"]) == "B"


# ── 문장 검색 ─────────────────────────────────────────────────────────────
CORPUS = [
    ps.Sentence("q1", "p1", "클릭할 때 소리가 거의 안 나서 밤에도 쓰기 좋아요", "pid-A", "click"),
    ps.Sentence("q2", "p2", "휠이 부드럽게 돌아가고 소음이 적습니다", "pid-A", "wheel"),
    ps.Sentence("q3", "p3", "배터리가 오래 갑니다", "pid-A", "battery"),
    ps.Sentence("q4", "p4", "게임할 때 손바닥이 땀으로 미끄러웠습니다", "pid-A", "other"),
]


def test_keyword_search_finds_matching_sentences_and_includes_other():
    hits = ps.search_sentences("손바닥 땀", CORPUS, rules=RULES)
    assert [h.sentence.quote_id for h in hits] == ["q4"]
    assert hits[0].sentence.attribute == "other"          # 기타 문장도 검색 대상이다


def test_keyword_search_handles_particles_by_stem():
    ids = [h.sentence.quote_id for h in ps.search_sentences("소음이", CORPUS, rules=RULES)]
    assert "q2" in ids


def test_reciprocal_rank_fusion_combines_keyword_and_embedding_rankings():
    k = RULES["feel"]["rrf_k"]
    keyword_only = ps.keyword_ranking("소음", CORPUS)
    assert keyword_only == ["q2"]
    # 임베딩은 q1 을 1위, q2 를 2위로 본다. q2 는 두 순위에 모두 있어 합이 더 크다.
    hits = ps.search_sentences("소음", CORPUS, embedding_ranked=["q1", "q2"], rules=RULES)
    assert [h.sentence.quote_id for h in hits] == ["q2", "q1"]
    assert hits[0].score == pytest.approx(1 / (k + 1) + 1 / (k + 2), abs=1e-6)
    assert hits[1].score == pytest.approx(1 / (k + 1), abs=1e-6)


def test_search_respects_limit_and_ignores_unknown_ids():
    hits = ps.search_sentences("소음", CORPUS, embedding_ranked=["zzz", "q1", "q3", "q4"], rules=RULES, limit=2)
    assert len(hits) == 2 and all(h.sentence.quote_id != "zzz" for h in hits)


def test_unrecognized_phrases_without_related_sentences_are_left_out():
    out = ps.evidence_for_unrecognized(["소음", "게이밍 감성"], CORPUS, rules=RULES)
    assert list(out) == ["소음"]


def test_search_with_empty_inputs_returns_nothing():
    assert ps.search_sentences("", CORPUS, rules=RULES) == []
    assert ps.search_sentences("소음", [], rules=RULES) == []


# ── 결과 화면 재설계(S2·S3): 요청 속성 먼저 인용, 비슷한 말 건너뛰기 ─────────────────
def _monitor_cand(pid="pid-M"):
    return Candidate(product_key="M", slot="monitor", name="M", product_id=pid, price=100)


def _monitor_feel(obs, situations=("design",)):
    interp = pi.Interpretation(kinds=["monitor"], situations=list(situations))
    cand = _monitor_cand()
    resolved = pi.resolve(interp, RULES)["monitor"]
    return compute_feel("monitor", [cand], [cand], interp, resolved, obs, RULES, now=NOW)["M"]


def test_requested_attribute_picks_quotes_before_earlier_attributes():
    """설정 순서가 앞선 내구성이 가장 최근 글을 가져가 요청한 외관(looks)이 인용 없이 건수만 남던 문제."""
    obs = [
        Obs("u1", "pid-M", "durability", direction="good", written_at=NOW - timedelta(days=1),
            post_id="p1", quote_id="q-dur-1", sentence="오래 써도 멀쩡합니다."),
        Obs("u1", "pid-M", "looks", direction="good", written_at=NOW - timedelta(days=1),
            post_id="p1", quote_id="q-looks-1", sentence="베젤이 얇아서 예쁩니다."),
        Obs("u2", "pid-M", "durability", direction="good", written_at=NOW - timedelta(days=9),
            post_id="p2", quote_id="q-dur-2", sentence="두 달 썼는데 이상 없습니다."),
    ]
    detail = _monitor_feel(obs)
    by_code = {a.code: a for a in detail.attributes}
    assert [q.quote_id for q in by_code["looks"].quotes] == ["q-looks-1"]        # 요청한 속성이 p1 을 가져간다
    assert [q.quote_id for q in by_code["durability"].quotes] == ["q-dur-2"]     # 나머지는 남은 글에서
    assert list(by_code) == [a.code for a in detail.attributes]                   # 결과 배열 순서는 그대로
    plain = _monitor_feel(obs, situations=())
    assert "looks" not in {a.code for a in plain.attributes}                      # 요청이 없으면 설정 순서(내구성이 p1)
    assert [q.quote_id for q in next(a for a in plain.attributes if a.code == "durability").quotes][0] == "q-dur-1"


def test_priority_does_not_change_scores_or_counts():
    obs = [
        Obs("u1", "pid-M", "durability", direction="good", written_at=NOW, post_id="p1", quote_id="a", sentence="하나 둘 셋."),
        Obs("u1", "pid-M", "looks", direction="bad", written_at=NOW, post_id="p1", quote_id="b", sentence="넷 다섯 여섯."),
    ]
    detail = _monitor_feel(obs)
    looks = next(a for a in detail.attributes if a.code == "looks")
    assert (looks.same_good + looks.rest_good, looks.same_bad + looks.rest_bad) == (0, 1)


def test_near_duplicate_sentences_are_not_quoted_twice():
    """글은 달라도 같은 말(베젤이 얇고 뒷면이 게이밍 느낌)을 되풀이한 두 문장은 하나만 보인다."""
    obs = [
        Obs("u1", "pid-M", "looks", direction="good", written_at=NOW - timedelta(days=1), post_id="p1", quote_id="q1",
            sentence="디자인은 앞에서 보면 베젤이 얇아서 깔끔하고, 뒷면은 게이밍 느낌이 조금 있어요."),
        Obs("u2", "pid-M", "looks", direction="good", written_at=NOW - timedelta(days=2), post_id="p2", quote_id="q2",
            sentence="겉모습은 뒷면에 게이밍 모니터 느낌이 좀 있고, 앞에서 보면 베젤이 얇아서 깔끔해요."),
        Obs("u3", "pid-M", "looks", direction="good", written_at=NOW - timedelta(days=3), post_id="p3", quote_id="q3",
            sentence="겉모습은 게이밍 제품치고 과하지 않아서, 낮에 작업할 때 책상 분위기를 해치지 않아요."),
    ]
    looks = next(a for a in _monitor_feel(obs).attributes if a.code == "looks")
    assert [q.quote_id for q in looks.quotes] == ["q1", "q3"]                     # q2 는 q1 과 같은 말
    assert looks.same_good + looks.rest_good == 3                                  # 집계는 세 명 그대로


def test_distinct_sentences_are_kept_and_rules_validate_similarity():
    obs = [
        Obs("u1", "pid-M", "looks", direction="good", written_at=NOW, post_id="p1", quote_id="q1",
            sentence="생김새는 수수한 편이라 어디에 둬도 튀지 않아요."),
        Obs("u2", "pid-M", "looks", direction="good", written_at=NOW - timedelta(days=1), post_id="p2", quote_id="q2",
            sentence="뒷면이 깔끔해서 뒤쪽이 보이는 자리에 놓아도 지저분해 보이지 않더라고요."),
    ]
    looks = next(a for a in _monitor_feel(obs).attributes if a.code == "looks")
    assert len(looks.quotes) == 2
    assert 0 < RULES["feel"]["quote_similarity_max"] < 1
