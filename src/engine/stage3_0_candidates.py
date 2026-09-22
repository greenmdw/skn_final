"""[3-0] 후보 수집.

[2]와 [3-A] 사이의 별도 스텝. 실시간 커머스 데이터 API 호출·캐시·재시도를
필터 로직에서 격리한다. 재탐색 시에는 스킵(이미 수집된 후보 재사용).
데모: 로컬 합성 카탈로그만 읽음 (제휴 커머스 API는 최종에서).

"""
from __future__ import annotations

import os

from src.dto import Candidate, RequirementSpec
from src.engine import LogFn
from src.repo.catalog_repo import load_candidates_by_slot, load_candidates_by_slot_from_db


def load_pc_catalog(log: LogFn) -> dict[str, list[Candidate]]:
    """PC 카탈로그 로드 — [3-0]과 견적 점검의 매칭 미리보기(owned_parts.preview_current_specs)가
    함께 쓴다. 같은 카탈로그를 봐야 화면에 보이는 매칭과 실제 추천 계산의 매칭이 어긋나지 않는다.

    CATALOG_SOURCE=mock — 실제 DB 카탈로그를 건너뛰고 합성 카탈로그만 쓴다
    (DB 없이 빠르게 돌리고 싶을 때, 테스트에서 DB 상태에 기대지 않으려 할 때).
    그 외(기본값)에는 실제 수집 카탈로그(0015_pc_parts_category_specs.sql)를
    먼저 시도하고, DB에 접속 못 하면(DATABASE_URL 미설정·연결 실패 등) 조용히
    실패로 죽지 않고 합성 카탈로그로 자동 강등한다 — 팀원 각자 로컬 DB를 항상
    띄워두는 건 아니라서, 기본 데모가 DB 유무에 깨지면 안 된다."""
    if os.environ.get("CATALOG_SOURCE") != "mock":
        try:
            from src.db import get_conn

            with get_conn() as conn:
                by_slot = load_candidates_by_slot_from_db(conn)
            if any(by_slot.values()):
                summary = " / ".join(f"{s} {len(c)}" for s, c in by_slot.items())
                log(f"      [DB] 실제 수집 카탈로그 로드 → 슬롯별 후보: {summary}")
                return by_slot
            log("      [DB] 실제 카탈로그가 비어 있음 → 합성 카탈로그로 대체")
        except Exception as e:  # noqa: BLE001 — DB 미가용은 데모를 막을 이유가 아니다
            log(f"      [DB] 접속/조회 실패({type(e).__name__}) → 합성 카탈로그로 대체")
    by_slot = load_candidates_by_slot()
    summary = " / ".join(f"{s} {len(c)}" for s, c in by_slot.items())
    log(f"      [MOCK] 합성 카탈로그 로드 → 슬롯별 후보: {summary}")
    return by_slot


def run(spec: RequirementSpec, log: LogFn) -> dict[str, list[Candidate]]:
    log("[3-0] 후보 수집 ...")
    if spec.category == "computer":
        return load_pc_catalog(log)
    raise NotImplementedError(f"stage3_0: 지원하지 않는 카테고리입니다: {spec.category}")

