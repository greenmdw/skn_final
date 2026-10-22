"""`python -m src.workers.review_embedding_batch` CLI(main) — 실제 로직은 워커·임베더 테스트에서 이미
검증했으므로, 여기서는 argparse 연결과 dry-run 출력·종료 코드만 확인한다. MOCK_MODE=1(기본,
tests/conftest.py)이라 OpenAIEmbedder가 실제 OpenAI를 부르지 않는다."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import psycopg
import pytest

from src.workers import review_embedding_batch

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.db


def test_main_opens_connection_with_autocommit_true(monkeypatch):
    """배치별 커밋이 실제로 디스크에 남으려면 CLI가 autocommit=True로 연결해야 한다
    (src/workers/review_embedding_batch.py 모듈 docstring, _require_commit_safe_conn 참고) —
    평범한 autocommit=False 커넥션으로 열면 run()이 ValueError로 거절한다."""
    captured = {}
    real_connect = psycopg.connect

    def spy_connect(dsn, *args, **kwargs):
        captured["autocommit"] = kwargs.get("autocommit")
        return real_connect(dsn, *args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", spy_connect)
    exit_code = review_embedding_batch.main(["--dry-run"])
    assert exit_code == 0
    assert captured["autocommit"] is True


def test_dry_run_reports_missing_count_and_exits_zero(capsys):
    exit_code = review_embedding_batch.main(["--dry-run"])
    assert exit_code == 0
    out = capsys.readouterr().out.strip()
    result = json.loads(out)
    assert result["embedded"] == 0
    assert result["failed"] == 0
    assert result["batches"] == 0
    assert isinstance(result["remaining"], int) and result["remaining"] >= 0


def test_dry_run_and_rebuild_together_is_a_usage_error():
    with pytest.raises(SystemExit) as exc_info:
        review_embedding_batch.main(["--dry-run", "--rebuild"])
    assert exc_info.value.code == 2


@pytest.mark.parametrize("options", [["--limit", "-1"], ["--batch-size", "0"], ["--batch-size", "-1"]])
def test_invalid_options_are_rejected_before_connecting_to_the_db(monkeypatch, options):
    def connect_must_not_be_called(*args, **kwargs):
        raise AssertionError("invalid options must be rejected before DB access")

    monkeypatch.setattr(psycopg, "connect", connect_must_not_be_called)
    with pytest.raises(SystemExit) as caught:
        review_embedding_batch.main(["--rebuild", *options])
    assert caught.value.code == 2


def test_real_run_embeds_at_least_one_missing_review(capsys):
    dsn = os.environ["DATABASE_URL"]
    with psycopg.connect(dsn, autocommit=True) as conn:
        if "test" not in conn.info.dbname.lower():
            raise AssertionError(f"CLI db test requires a test database, got {conn.info.dbname!r}")
        before = conn.execute(
            "SELECT count(*) FROM evidence.review_document d "
            "LEFT JOIN evidence.review_embedding e ON e.review_id = d.id "
            "WHERE e.review_id IS NULL"
        ).fetchone()[0]

    if before == 0:
        pytest.skip("no pre-existing review is missing an embedding to exercise a real (non-dry) run")

    exit_code = review_embedding_batch.main(["--limit", "1", "--batch-size", "1"])
    assert exit_code == 0
    out = capsys.readouterr().out.strip()
    result = json.loads(out)
    assert result == {"embedded": 1, "failed": 0, "remaining": before - 1, "batches": 1}


def test_module_entry_point_runs_inside_the_deploy_image_layout():
    """배포 이미지는 scripts/를 복사하지 않는다(Dockerfile) — 서버에서는
    `python -m src.workers.review_embedding_batch`로 돌리므로 그 진입점이 실제로 동작해야 한다."""
    import subprocess

    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
    completed = subprocess.run(
        [sys.executable, "-m", "src.workers.review_embedding_batch", "--dry-run"],
        cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["embedded"] == 0 and result["batches"] == 0


def test_guard_errors_exit_2_with_a_message(monkeypatch, capsys):
    def refuse(*args, **kwargs):
        raise ValueError("가짜 벡터를 테스트용이 아닌 DB에 저장하려 한다")

    monkeypatch.setattr(review_embedding_batch, "run", refuse)
    assert review_embedding_batch.main(["--limit", "1"]) == 2
    captured = capsys.readouterr()
    assert "오류: 가짜 벡터를" in captured.err
    assert captured.out == ""
