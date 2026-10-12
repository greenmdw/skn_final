"""사용기 분석의 입력·출력 계약(개발_확정사양.md 3~5장, 구현 순서 5).

글 하나를 분석해 `FeelObservation`(체감 점수의 입력, `peripheral_feel`)을 만들기까지의 모양을 정한다.
이 모듈은 순수하다 — DB·언어 모델을 모른다. 언어 모델이 본문에서 문장을 뽑는 일(추출)과 결과를 저장하는 일은
이 계약을 따라 따로 만든다.

```
글(PostInput) ──▶ 추출(PostExtraction, 언어 모델이 채움) ──▶ analyze_post(): 확인 여섯 가지 ──▶ PostAnalysis
                                                                         └▶ observations(): FeelObservation
```

## 확인 여섯 가지(사양 4.5)와 결과 상태

| 확인 | 어기면 |
|---|---|
| ① 본문에 글자 그대로 있는 문장인가 | excluded `sentence_not_in_body` |
| ② 연결한 제품(과 옵션)에 대한 말인가 | excluded `unknown_product` / `product_not_scorable` |
| ③ 그 종류의 속성(또는 기타)인가 | excluded `attribute_not_for_kind` |
| ④ 직접 겪은 것인가 | excluded `not_experienced` |
| ⑤ 부정·비교 대상·상황이 보존됐는가 | 비교 문장은 excluded `comparison`, 값이 속성 종류와 맞지 않으면 excluded `invalid_value` |
| ⑥ 수치(스펙)와 체감을 구분했는가 | excluded `spec_statement` |

확신이 낮은 추출(`confidence=low`)과 본문 속 지시문이 있는 글은 `held`(보류)이고 점수에서 뺀다. 통과하면 `confirmed`다.
속성이 "기타"인 문장은 `confirmed` 여도 점수에 넣지 않고 문장 검색의 대상으로만 둔다(`scorable` 이 False).

글감 조건: 내구성은 사용 기간이 `feel.durability_min_months` 이상이라고 밝힌 문장만 센다(사양 4.2).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from src.engine.peripheral_feel import FeelObservation
from src.engine.peripheral_intent import Kind, kinds_all_order, looks_like_injected_instruction
from src.engine.peripheral_rules import (
    feel_attributes, feel_config, load_peripheral_rules, purpose_codes, situations,
)

OTHER = "other"        # 맞는 속성이 없는 직접 겪은 문장(사양 4.4)
PostStatus = Literal["published", "hidden", "deleted"]
Confidence = Literal["low", "medium", "high"]
ItemStatus = Literal["confirmed", "held", "excluded"]
HandSize = Literal["small", "medium", "large"]


# ── 입력: 글 ───────────────────────────────────────────────────────────────
class LinkedProduct(BaseModel):
    """글에 연결된 제품 하나(커뮤니티 요청서 B-1, 최대 5개). `product_id` 가 없으면 "목록에 없는 제품"이다."""

    index: int = Field(ge=0)
    product_id: str | None = None
    kind: Kind | None = None
    name: str = ""
    option_label: str | None = None


class PostInput(BaseModel):
    post_id: str
    author_id: str
    board: str                                  # 사용기 게시판 코드(요청서 6장: review)
    body: str                                   # 글자만 뽑은 본문(HTML/Markdown 변환은 읽는 쪽이 한다)
    products: list[LinkedProduct] = Field(default_factory=list)
    status: PostStatus = "published"
    is_example: bool = False
    written_at: datetime | None = None


# ── 출력: 추출 결과(언어 모델이 채우는 모양) ───────────────────────────────────
class ExtractedAuthor(BaseModel):
    """작성자 조건. 글에 밝히지 않았으면 비워 둔다 — 지어내지 않는다(사양 4.1)."""

    purposes: list[str] = Field(default_factory=list)
    situations: list[str] = Field(default_factory=list)
    hand_size: HandSize | None = None
    hand_cm: float | None = Field(default=None, gt=0)       # cm 가 적혀 있으면 원래 값도 함께 둔다


class ExtractedItem(BaseModel):
    sentence: str                                  # 본문 문장 그대로
    product_index: int = Field(ge=0)               # PostInput.products 의 index
    attribute: str                                 # feel.attributes[kind] 의 코드 또는 "other"
    direction: Literal["good", "bad", "mixed"] | None = None      # 평가 속성
    side: str | None = None                        # 성향 축의 쪽 코드
    evaluated_in: list[str] = Field(default_factory=list)         # 이 평가가 나온 상황·목적 코드
    option_label: str | None = None                # 스위치처럼 옵션에 달린 속성이면 작성자가 적은 옵션
    months_used: float | None = Field(default=None, ge=0)         # 사용 기간(개월), 밝힌 경우만
    experienced: bool = True                       # 직접 겪은 내용인가
    comparison: bool = False                       # "A가 B보다 …" 같은 비교 문장
    spec_statement: bool = False                   # 수치·스펙을 옮긴 문장
    confidence: Confidence = "high"


class PostExtraction(BaseModel):
    is_review: bool
    reject_reason: str | None = None               # question·chatter·ad·unboxing·planned·store_demo·hearsay·sale 등
    author: ExtractedAuthor = Field(default_factory=ExtractedAuthor)
    items: list[ExtractedItem] = Field(default_factory=list)


# ── 분석 결과 ──────────────────────────────────────────────────────────────
class AnalyzedItem(BaseModel):
    item: ExtractedItem
    kind: Kind | None = None
    product_id: str | None = None
    status: ItemStatus
    reasons: list[str] = Field(default_factory=list)       # held·excluded 의 이유 코드

    @property
    def scorable(self) -> bool:
        return self.status == "confirmed" and self.item.attribute != OTHER


class PostAnalysis(BaseModel):
    post_id: str
    analyzable: bool                                       # False 면 이 글에서는 아무것도 점수에 넣지 않는다
    skip_reason: str | None = None
    author: ExtractedAuthor = Field(default_factory=ExtractedAuthor)
    items: list[AnalyzedItem] = Field(default_factory=list)

    def observations(self, post: PostInput) -> list[FeelObservation]:
        """점수에 들어가는 관측만 `FeelObservation` 으로 바꾼다. 제품이 카탈로그에 없으면 만들지 않는다."""
        if not self.analyzable:
            return []
        author = self.author
        out: list[FeelObservation] = []
        for analyzed in self.items:
            if not analyzed.scorable or analyzed.product_id is None:
                continue
            item = analyzed.item
            out.append(FeelObservation(
                author_id=post.author_id, product_id=analyzed.product_id, attribute=item.attribute,
                direction=item.direction, side=item.side,
                purposes=frozenset(author.purposes), situations=frozenset(author.situations),
                hand_size=author.hand_size, evaluated_in=frozenset(item.evaluated_in),
                written_at=post.written_at, is_example=post.is_example,
            ))
        return out


# ── 분석 ──────────────────────────────────────────────────────────────────
def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def hand_size_from_cm(cm: float | None, rules: dict | None = None) -> HandSize | None:
    """손 길이(cm)를 단계로 바꾼다(사양 4.1, 잠정 17.5cm 미만 작은 편 / 19cm 초과 큰 편). cm 가 없으면 None."""
    if cm is None:
        return None
    cfg = feel_config(rules or load_peripheral_rules())
    if cm < cfg["hand_small_below_cm"]:
        return "small"
    if cm > cfg["hand_large_above_cm"]:
        return "large"
    return "medium"


def _normalize_author(author: ExtractedAuthor, rules: dict) -> ExtractedAuthor:
    sit = set(situations(rules))
    codes = set(purpose_codes(rules)) | sit
    purposes = [c for c in dict.fromkeys(author.purposes) if c in codes and c not in sit]
    sits = [c for c in dict.fromkeys([*author.situations, *(c for c in author.purposes if c in sit)]) if c in sit]
    return ExtractedAuthor(
        purposes=purposes, situations=sits,
        hand_size=hand_size_from_cm(author.hand_cm, rules) or author.hand_size, hand_cm=author.hand_cm,
    )


def _value_matches(attr: dict, item: ExtractedItem) -> bool:
    if attr["type"] == "rating":
        return item.direction is not None and item.side is None
    return item.side in attr["sides"] and item.direction is None


def analyze_post(post: PostInput, extraction: PostExtraction, rules: dict | None = None) -> PostAnalysis:
    """추출 결과를 확인 여섯 가지로 걸러 `PostAnalysis` 를 만든다. 글이 점수에 쓰일 수 없는 경우(게시되지 않음,
    사용기 아님, 점수를 낼 수 있는 연결 제품 없음)는 `analyzable=False` 와 이유만 남긴다."""
    rules = rules or load_peripheral_rules()
    cfg = feel_config(rules)

    def _skip(reason: str) -> PostAnalysis:
        return PostAnalysis(post_id=post.post_id, analyzable=False, skip_reason=reason)

    if post.status != "published":
        return _skip("not_published")
    if not extraction.is_review:
        return _skip(extraction.reject_reason or "not_a_review")
    if not any(p.product_id and p.kind for p in post.products):
        return _skip("no_catalog_product")

    products = {p.index: p for p in post.products}
    body = _squash(post.body)
    injected = looks_like_injected_instruction(post.body)       # 본문 속 지시문은 따르지 않고 글을 보류한다(사양 3장)
    author = _normalize_author(extraction.author, rules)

    items: list[AnalyzedItem] = []
    for item in extraction.items:
        product = products.get(item.product_index)
        reasons: list[str] = []
        kind = product.kind if product else None
        product_id = product.product_id if product else None

        if _squash(item.sentence) == "" or _squash(item.sentence) not in body:
            reasons.append("sentence_not_in_body")
        if product is None:
            reasons.append("unknown_product")
        elif not (product.product_id and product.kind):
            reasons.append("product_not_scorable")
        attrs = feel_attributes(kind, rules) if kind else {}
        if kind and item.attribute != OTHER and item.attribute not in attrs:
            reasons.append("attribute_not_for_kind")
        if not item.experienced:
            reasons.append("not_experienced")
        if item.comparison:
            reasons.append("comparison")
        if item.spec_statement:
            reasons.append("spec_statement")
        if kind and item.attribute in attrs and not _value_matches(attrs[item.attribute], item):
            reasons.append("invalid_value")
        if (kind and item.attribute == "durability"
                and (item.months_used is None or item.months_used < cfg["durability_min_months"])):
            reasons.append("durability_period_short")

        if reasons:
            items.append(AnalyzedItem(item=item, kind=kind, product_id=product_id, status="excluded", reasons=reasons))
        elif injected or item.confidence == "low":
            held = ["instruction_in_body"] if injected else ["low_confidence"]
            items.append(AnalyzedItem(item=item, kind=kind, product_id=product_id, status="held", reasons=held))
        else:
            items.append(AnalyzedItem(item=item, kind=kind, product_id=product_id, status="confirmed"))
    return PostAnalysis(post_id=post.post_id, analyzable=True, author=author, items=items)


@dataclass(frozen=True)
class CorpusSummary:
    posts: int
    confirmed: int
    held: int
    excluded: int


def summarize(analyses: list[PostAnalysis]) -> CorpusSummary:
    items = [i for a in analyses if a.analyzable for i in a.items]
    return CorpusSummary(
        posts=sum(1 for a in analyses if a.analyzable),
        confirmed=sum(1 for i in items if i.status == "confirmed"),
        held=sum(1 for i in items if i.status == "held"),
        excluded=sum(1 for i in items if i.status == "excluded"),
    )


def supported_kinds(post: PostInput) -> list[str]:
    """글에 연결된 점수 낼 수 있는 제품의 종류(고정 순서)."""
    return kinds_all_order([p.kind for p in post.products if p.kind and p.product_id])
