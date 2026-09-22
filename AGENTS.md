# Agent Guide

## Running pytest

Use this as the default command when validating changes that may affect the database:

```bash
docker compose up -d db
PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache TRUEFIT_REQUIRE_TEST_DB=1 uv run pytest -q
```

Always set `TRUEFIT_REQUIRE_TEST_DB=1` for completion checks. It turns PostgreSQL setup failures into errors instead of allowing database tests to be silently skipped.

At the start of a pytest session, the test harness automatically:

1. Creates a unique `truefit_test_<UUID>` database on the running PostgreSQL server.
2. Runs `db/setup_all.py` to apply the four baseline migrations and all seeds.
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
- The current database baseline must contain exactly these four files:
  - `db/migrations/0000_schema.sql`
  - `db/migrations/0001_constraints.sql`
  - `db/migrations/0002_indexes.sql`
  - `db/migrations/0003_triggers.sql`
