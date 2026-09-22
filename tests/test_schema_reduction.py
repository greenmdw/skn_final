"""현재 4개 baseline 마이그레이션, PC 카탈로그 및 축소 DB 계약 검증.

실제 PostgreSQL의 테이블 목록과 마이그레이션 체크섬, 시드 멱등성을 검증한다.
리스트 항목의 소유권·참조 무결성은 test_p0_list_item_integrity.py에서 검사한다.
"""
from __future__ import annotations

import os
import hashlib
import subprocess
import sys
from pathlib import Path

import psycopg
import pytest

from src.schemas import ConditionState, RecommendResultOut

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "db/migrations"

# The compact migration chain creates only objects that survive in the final schema.
EXPECTED_CHAIN = [
    "0000_schema.sql", "0001_constraints.sql", "0002_indexes.sql", "0003_triggers.sql",
]
# 현재 baseline의 명시적 계약. 같은 개수의 다른 테이블로 바뀌어도 실패해야 한다.
EXPECTED_TABLES = {
    "assets.file_object",
    "assets.material_applicability",
    "assets.material_revision",
    "assets.product_material",
    "catalog.case_spec",
    "catalog.cooler_spec",
    "catalog.cpu_spec",
    "catalog.gpu_spec",
    "catalog.keyboard_spec",
    "catalog.mainboard_spec",
    "catalog.merchant",
    "catalog.monitor_spec",
    "catalog.mouse_spec",
    "catalog.offer",
    "catalog.offer_observation",
    "catalog.peripheral_price_snapshot",
    "catalog.product",
    "catalog.product_category",
    "catalog.product_fact",
    "catalog.product_variant",
    "catalog.psu_spec",
    "catalog.ram_spec",
    "catalog.speaker_spec",
    "catalog.ssd_spec",
    "community.pc_build",
    "community.pc_build_component",
    "community.pc_build_version",
    "community.review",
    "community.review_revision",
    "config.domain",
    "config.domain_version",
    "engine.feedback_event",
    "engine.recommendation_candidate",
    "engine.recommendation_run",
    "engine.validation_result",
    "evidence.evidence",
    "evidence.review_aggregate",
    "evidence.review_aggregate_member",
    "evidence.review_subject",
    "evidence.review_summary",
    "evidence.source",
    "identity.app_user",
    "identity.conversation",
    "identity.message",
    "notification.price_watch",
    "planning.plan",
    "planning.plan_condition",
    "planning.plan_node",
    "planning.plan_revision",
    "planning.purchase_line",
    "planning.requirement",
}
# 제거된 저장 구조는 다시 생성하지 않는다.
REMOVED_TABLES = [
    "planning.owned_item", "planning.fulfillment_allocation",
    "identity.user_preference", "catalog.product_category_membership",
    "engine.candidate_evidence", "engine.validation_target", "engine.validation_evidence",
    "notification.notification_event", "notification.price_watch_evaluation",
]
REMOVED_SCHEMAS = ["rag", "dataset", "shared"]
# 통합 planning.item 모델은 현재 계약에 없다.
NEVER_TABLES = ["planning.item"]


def test_migration_chain_matches_current_baseline_exactly():
    actual = sorted(f.name for f in MIGRATIONS.glob("*.sql"))
    assert actual == EXPECTED_CHAIN, (
        "baseline migration set drifted — got extra/missing files: "
        f"{set(actual) ^ set(EXPECTED_CHAIN)}"
    )


def test_no_full_reduction_migration_survives():
    """The rag-branch's own destructive-reduction filenames must be gone, not just unused."""
    names = {f.name for f in MIGRATIONS.glob("*.sql")}
    for stale in (
        "0010_schema_reduction_v1.sql", "0011_schema_reduction_completion.sql",
        "0012_schema_reduction_destructive.sql", "0013_schema_reduction_scope_constraints.sql",
        "0014_item_reference_integrity.sql", "0015_auth_version.sql",
    ):
        assert stale not in names, f"{stale} should have been replaced by the develop chain"


def test_removed_objects_are_never_created_or_dropped():
    sql = "\n".join(path.read_text(encoding="utf-8") for path in MIGRATIONS.glob("*.sql"))
    for schema in REMOVED_SCHEMAS:
        assert f"CREATE SCHEMA {schema}" not in sql
        assert f"DROP SCHEMA {schema}" not in sql
    for table in REMOVED_TABLES:
        assert f"CREATE TABLE {table}" not in sql
        assert f"DROP TABLE {table}" not in sql
    assert "CREATE EXTENSION IF NOT EXISTS vector" not in sql


def test_baseline_contains_final_schema_columns():
    sql = (MIGRATIONS / "0000_schema.sql").read_text(encoding="utf-8")
    assert "DROP TABLE" not in sql and "DROP SCHEMA" not in sql and "ALTER COLUMN" not in sql
    for addition in ("ui_settings", "notification_settings", "category_id", "evidence_refs", "issues"):
        assert addition in sql


def test_condition_and_recommendation_contract_round_trip():
    state = ConditionState.model_validate({
        "list_id": "list", "category": "computer", "fields": [{"key": "purpose", "label": "주요 용도", "value": "game", "status": "confirmed"}],
    })
    assert state.accepts_spec_file is False
    result = RecommendResultOut.model_validate({
        "list_id": "list", "run_id": "run",
        "status": "done", "category": "computer", "budget_max": 1500000,
        "items": [], "totals": {"selected_price": 0, "selected_units": 0},
    })
    assert result.model_dump()["status"] == "done"
    assert ConditionState(list_id="pc-list", category="computer").category == "computer"


DSN = os.getenv("RAG_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
pytestmark_db = pytest.mark.skipif(not DSN, reason="set DATABASE_URL/RAG_TEST_DATABASE_URL to a disposable database")


@pytestmark_db
@pytest.mark.db
def test_real_db_has_exact_current_table_set():
    """실제 DB의 테이블 이름 전체를 비교한다(누락과 예상하지 않은 추가 모두 검출)."""
    with psycopg.connect(DSN) as conn:
        for schema in REMOVED_SCHEMAS:
            row = conn.execute(
                "SELECT 1 FROM information_schema.schemata WHERE schema_name=%s", (schema,)
            ).fetchone()
            assert row is None, f"schema {schema} should not exist (develop drops it)"
        for qualified in REMOVED_TABLES + NEVER_TABLES:
            schema, table = qualified.split(".")
            row = conn.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
                (schema, table),
            ).fetchone()
            assert row is None, f"{qualified} must not exist"
        actual = {row[0] for row in conn.execute(
            "SELECT table_schema || '.' || table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog','information_schema','_migrations') "
            "AND table_type='BASE TABLE'"
        )}
        assert actual == EXPECTED_TABLES, (
            f"missing={EXPECTED_TABLES - actual}, unexpected={actual - EXPECTED_TABLES}"
        )


@pytestmark_db
@pytest.mark.db
@pytest.mark.parametrize("schema,table,column,data_type,nullable,default", [
    ("identity", "app_user", "ui_settings", "jsonb", "NO", "'{}'::jsonb"),
    ("identity", "app_user", "notification_settings", "jsonb", "NO", "'{}'::jsonb"),
    ("catalog", "product", "category_id", "uuid", "YES", None),
    ("engine", "recommendation_candidate", "evidence_refs", "jsonb", "NO", "'[]'::jsonb"),
    ("engine", "validation_result", "issues", "jsonb", "NO", "'[]'::jsonb"),
])
def test_reduced_storage_columns(schema, table, column, data_type, nullable, default):
    with psycopg.connect(DSN) as conn:
        row = conn.execute(
            "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
            "WHERE table_schema=%s AND table_name=%s AND column_name=%s",
            (schema, table, column),
        ).fetchone()
    assert row == (data_type, nullable, default)


@pytestmark_db
@pytest.mark.db
def test_baseline_tracking_functions_and_triggers():
    expected = {path.stem: hashlib.sha256(path.read_bytes()).hexdigest()[:16]
                for path in MIGRATIONS.glob("*.sql")}
    with psycopg.connect(DSN) as conn:
        applied = dict(conn.execute(
            "SELECT version, checksum FROM _migrations.schema_migrations"
        ).fetchall())
        assert applied == expected
        assert conn.execute(
            "SELECT n.nspname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE p.proname='set_updated_at'"
        ).fetchall() == [("public",)]
        assert conn.execute(
            "SELECT count(*) FROM pg_trigger t JOIN pg_proc p ON p.oid=t.tgfoid "
            "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE NOT t.tgisinternal "
            "AND t.tgname='set_updated_at' AND n.nspname <> 'public'"
        ).fetchone()[0] == 0


@pytestmark_db
@pytest.mark.db
def test_setup_all_is_idempotent():
    tables = ("catalog.product", "catalog.product_variant", "catalog.offer",
              "catalog.offer_observation", "catalog.peripheral_price_snapshot",
              "evidence.review_summary")
    with psycopg.connect(DSN) as conn:
        before = tuple(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables)
    result = subprocess.run([sys.executable, "db/setup_all.py"], cwd=ROOT,
                            env={**os.environ, "DATABASE_URL": DSN},
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr
    with psycopg.connect(DSN) as conn:
        after = tuple(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in tables)
    assert after == before
