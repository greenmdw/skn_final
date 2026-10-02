# Agent Guide

## Running pytest

Use this as the default command when validating changes that may affect the database:

```bash
docker compose up -d db
PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache TRUEFIT_REQUIRE_TEST_DB=1 uv run pytest -q -m "not llm_live"
```

Always set `TRUEFIT_REQUIRE_TEST_DB=1` for completion checks. It turns PostgreSQL setup failures into errors instead of allowing database tests to be silently skipped.

`-m "not llm_live"` is part of the default — `llm_live` tests call a real LLM API with `MOCK_MODE=0` and cost real money per run, so they are opt-in only (see "Run llm_live tests only" below and `docs/전체_테스트_시나리오_실행_기획.md` §2.5).

At the start of a pytest session, the test harness automatically:

1. Creates a unique `truefit_test_<UUID>` database on the running PostgreSQL server.
2. Runs `db/setup_all.py` to apply the ten baseline migrations and all seeds.
3. Runs the tests.
4. Drops the temporary database with `DROP DATABASE ... WITH (FORCE)` when the session ends.

Never run tests against the development database named `truefit`. `tests/conftest.py` blocks connections to databases whose names do not contain `test`.

### Common commands

```bash
# Run one test file
PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache TRUEFIT_REQUIRE_TEST_DB=1 \
  uv run pytest -q tests/test_schema_reduction.py

# Run one test
PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache TRUEFIT_REQUIRE_TEST_DB=1 \
  uv run pytest -q tests/test_schema_reduction.py::test_setup_all_is_idempotent

# Run fast tests that do not need PostgreSQL
PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache TRUEFIT_AUTO_TEST_DB=0 \
  uv run pytest -q -m "not db and not integration"

# Run database tests only
PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache TRUEFIT_REQUIRE_TEST_DB=1 \
  uv run pytest -q -m db

# Run integration tests only
PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache TRUEFIT_REQUIRE_TEST_DB=1 \
  uv run pytest -q -m integration

# Run llm_live tests only (real LLM calls, MOCK_MODE=0, costs money — run deliberately, not by default)
MOCK_MODE=0 PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache TRUEFIT_REQUIRE_TEST_DB=1 \
  uv run pytest -q -m llm_live
```

### Required seed inputs

Automatic database setup requires these files, which are not tracked by Git. Treat a missing file as a test setup failure.

```text
data/parts_list_modify.xlsx
data/peripherals/mouse_processed.csv
data/peripherals/monitor_processed.csv
data/peripherals/speaker_processed.csv
data/peripherals/keyboard_processed.csv
```

### Using a pre-provisioned test database

To disable automatic database creation, provide an already migrated and seeded database. Its name must contain `test`.

```bash
TEST_DATABASE_URL=postgresql://truefit:truefit@127.0.0.1:5432/truefit_test \
TRUEFIT_AUTO_TEST_DB=0 PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache \
  uv run pytest -q
```

### Troubleshooting

- If Docker access is denied, request approval to run `docker compose` in the agent environment.
- If the default uv cache is read-only, keep `UV_CACHE_DIR=/tmp/uv-cache` in the command.
- If Python raises `ModuleNotFoundError: src`, run from the repository root and set `PYTHONPATH=.`.
- If database tests are skipped, rerun with `TRUEFIT_REQUIRE_TEST_DB=1` so the underlying setup problem is reported as an error.
- The current database baseline must contain exactly these ten files:
  - `db/migrations/0000_schema.sql`
  - `db/migrations/0001_constraints.sql`
  - `db/migrations/0002_indexes.sql`
  - `db/migrations/0003_triggers.sql`
  - `db/migrations/0004_notification_events.sql` (added 2026-09-27, ACC-02: revives
    `notification.price_watch_evaluation` / `notification.notification_event`, previously removed)
  - `db/migrations/0005_preference_signal.sql` (added 2026-09-30: adds
    `identity.preference_signal`, brand-level preference/aversion signals — see
    `docs/사용자_선호비선호_기록_설계.md`)
  - `db/migrations/0006_report_soft_delete.sql` (added 2026-10-01, 개발요청 10번: adds
    `planning.plan_revision.deleted_at` so a single confirmed report can be deleted
    without deleting the whole conversation)
  - `db/migrations/0007_peripheral_line.sql` (added 2026-10-01, 개발요청 11번: adds
    `planning.peripheral_line` so a confirmed report can also freeze chosen peripherals
    — monitor/keyboard/mouse/speaker — alongside the PC build in `purchase_line`)
  - `db/migrations/0008_review_aspect.sql` (added 2026-10-02: enables the `vector` extension and
    adds `evidence.review_document`/`review_embedding`/`review_aspect_rule`/`review_aspect_observation`/
    `review_aspect_aggregate(_member)` and `engine.review_requirement_profile` for the review-evidence
    ingestion pipeline — `src/services/review_*.py`)
  - `db/migrations/0009_live_spec_lookup_cache.sql` (added 2026-10-02: adds
    `catalog.live_spec_lookup_cache` for the DB-miss live part-spec search feature — see
    `docs/미보유부품_실시간스펙검색_설계.md`)
