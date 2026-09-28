"""카테고리 정의 파일 로더.

config/categories/<category>.yaml 을 읽어 슬롯 구조·필수 입력·질문 세트·기본값·검증 분기를
제공한다. 엔진 코드에 `if category == "computer"` 를 하드코딩하지 않고 전부 이 정의를 통해 분기한다.
"""
from __future__ import annotations

from functools import lru_cache

import yaml

from src.config import CATEGORY_DIR


@lru_cache(maxsize=8)
def load_category(category: str) -> dict:
    """카테고리 정의 dict 반환.

    Returns keys: category, label, modes, required_inputs, slot_structure,
    slot_schema, defaults, question_sets, verify_branch(set|per_item), status(optional).
    """
    path = CATEGORY_DIR / f"{category}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"카테고리 정의 없음: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def verify_branch(category: str) -> str:
    """'set' = [4] 세트 최적화 → [3-C] 세트 검증(완성 세트 1건, 컴퓨터가 이 값을 쓴다).

    'per_item' = [4] 없이 [3-A] 하드 필터 → [3-B] 랭킹 → [3-C] 품목별 검증(품목 각각을
    독립적으로 판정 — 계획 §3.3 E11, `stage3c_verify.verify_per_item`). 아직 이 값을 쓰는
    카테고리는 없다(`pipeline._run_per_item_branch`가 그 자리를 예약해 둔다). 주변기기
    (모니터·키보드·마우스·스피커)가 이 판정 방식을 실제로 쓰지만, 독립 카테고리가 아니라
    컴퓨터 요청의 부속 결과라서 `verify_branch`가 아니라 컴퓨터(set) 분기 뒤
    `pipeline._run_peripherals`가 `peripherals` 조건이 있을 때만 별도로 부른다
    (`src/engine/peripheral_select.run_peripherals`).
    """
    return load_category(category)["verify_branch"]


def available_categories() -> list[str]:
    """정의 파일이 실재하는 카테고리 코드 목록 (정렬).

    config.domain 에는 RAG 평가용처럼 런타임 카테고리가 아닌 행도 있을 수 있으므로,
    세션이 도메인을 고를 때 후보를 이 목록으로 제한한다.
    """
    return sorted(p.stem for p in CATEGORY_DIR.glob("*.yaml"))
