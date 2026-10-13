#!/usr/bin/env python3
"""예시 글 스냅샷 — 한 DB 에서 적재·분석·임베딩을 끝낸 결과를 파일로 내보내고, 다른 DB 에 그대로 복원한다.

왜 필요한가: 분석은 언어 모델을 부르고(비용), 글 id 는 DB 마다 새로 만들어진다. 그래서 각자 DB 에서 다시 돌리는 대신
한 곳에서 끝낸 결과(글 + 연결 제품 + 분석 대기·근거 문장 + 문장 벡터)를 묶어 나눈다.

내보내는 것(예시 글 `is_example AND external_id IS NOT NULL` 만, `--prefix` 로 글 번호 접두어 한정 가능):
    identity.app_user(작성자 계정) · community.post · community.post_image · community.post_product ·
    engine.peripheral_post_intake · engine.peripheral_post_evidence · engine.peripheral_post_evidence_embedding
    + 글에 붙은 이미지 파일(<폴더>/images/<저장 키>)

제품 id 는 DB 마다 다르므로 제품은 (brand, model) 로 적어 두고, 복원할 때 그 DB 의 catalog.product 에서 다시 찾는다.
이미지 파일은 저장소(COMMUNITY_UPLOAD_DIR)에서 읽어 함께 담고, 복원할 때 같은 저장 키로 그 DB 의 저장소에 쓴다.

    python db/community_examples_snapshot.py export data/community_examples/dump [--prefix A]
    python db/community_examples_snapshot.py restore data/community_examples/dump            # 이미 있으면 거절
    python db/community_examples_snapshot.py restore data/community_examples/dump --replace  # 같은 글을 지우고 복원

작성자 계정(P01~P20)은 이메일(example-pXX@truefit.invalid)로 맞춘다 — 이 DB 에 있으면 그 계정을 쓰고, 없으면 만든다.
복원은 한 트랜잭션이다 — 하나라도 실패하면 아무것도 바뀌지 않는다. 스키마가 다르면(마이그레이션 차이) 거절한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from psycopg import sql  # noqa: E402

from src.db import get_conn  # noqa: E402
from src.services import community_service as svc  # noqa: E402

# 복원 순서. product: 제품 id 를 (brand, model) 로 다시 찾는 열.
TABLES = [
    {"name": "identity.app_user", "file": "app_user"},
    {"name": "community.post", "file": "post"},
    {"name": "community.post_image", "file": "post_image"},
    {"name": "community.post_product", "file": "post_product", "product": "product_id", "optional_product": True},
    {"name": "engine.peripheral_post_intake", "file": "peripheral_post_intake"},
    {"name": "engine.peripheral_post_evidence", "file": "peripheral_post_evidence", "product": "product_id"},
    {"name": "engine.peripheral_post_evidence_embedding", "file": "peripheral_post_evidence_embedding"},
]


def _posts_where(conn, prefix: str | None) -> str:
    where = "p.is_example AND p.external_id IS NOT NULL"
    if prefix:
        pattern = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where += " AND p.external_id LIKE " + sql.Literal(pattern).as_string(conn)
    return where


def _columns(conn, table: str) -> list[str]:
    schema, name = table.split(".")
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
        (schema, name)).fetchall()
    return [r[0] for r in rows]


def _signature(conn) -> dict[str, str]:
    return {t["name"]: hashlib.sha1(",".join(_columns(conn, t["name"])).encode()).hexdigest()[:12] for t in TABLES}


def _export_select(conn, table: dict, where: str) -> str:
    """내보낼 행을 고르는 SELECT. 제품 id 열은 그대로 두고 brand·model 을 덧붙인다."""
    name = table["name"]
    cols = ", ".join(f"t.{c}" for c in _columns(conn, name))
    extra = ", c.brand AS _brand, c.model AS _model" if table.get("product") else ""
    join = f" LEFT JOIN catalog.product c ON c.id = t.{table['product']}" if table.get("product") else ""
    base = f"SELECT p.id FROM community.post p WHERE {where}"
    scope = {
        "identity.app_user": f"t.id IN (SELECT p.author_user_id FROM community.post p WHERE {where}) "
                             f"OR t.id IN (SELECT i.owner_user_id FROM community.post_image i WHERE i.post_id IN ({base}))",
        "community.post": f"t.id IN ({base})",
        "community.post_image": f"t.post_id IN ({base})",
        "community.post_product": f"t.post_id IN ({base})",
        "engine.peripheral_post_intake": f"t.post_id IN ({base})",
        "engine.peripheral_post_evidence": f"t.post_id IN ({base})",
        "engine.peripheral_post_evidence_embedding":
            f"t.evidence_id IN (SELECT e.id FROM engine.peripheral_post_evidence e WHERE e.post_id IN ({base}))",
    }[name]
    return f"SELECT {cols}{extra} FROM {name} t{join} WHERE {scope}"


def export_snapshot(conn, out_dir: Path, *, prefix: str | None = None) -> dict:
    where = _posts_where(conn, prefix)
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for table in TABLES:
        select = _export_select(conn, table, where)
        with (out_dir / f"{table['file']}.copy").open("wb") as fh, conn.cursor() as cur:
            with cur.copy(f"COPY ({select}) TO STDOUT") as copy:
                for chunk in copy:
                    fh.write(bytes(chunk))
        counts[table["name"]] = conn.execute(f"SELECT count(*) FROM ({select}) s").fetchone()[0]

    # 이미지 파일: 저장소에서 읽어 images/<저장 키> 로 담는다. 하나라도 없으면 스냅샷이 불완전하므로 중단한다.
    keys = [r[0] for r in conn.execute(
        f"SELECT i.storage_key FROM community.post_image i JOIN community.post p ON p.id = i.post_id WHERE {where} ORDER BY 1").fetchall()]
    store = svc._store()
    missing = []
    for key in keys:
        data = store.read(key)
        if data is None:
            missing.append(key)
            continue
        target = out_dir / "images" / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if missing:
        raise ValueError(f"저장소에 이미지 파일이 없다({len(missing)}개): {missing[:3]}")
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "prefix": prefix, "counts": counts,
                "columns": _signature(conn), "images": keys}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _delete_examples(conn, post_ids: list) -> list[str]:
    """글과 그 글에 딸린 분석 결과를 지운다. 작성자 계정(P01~P20)은 다른 글도 쓰므로 지우지 않는다.
    지운 글의 이미지 저장 키를 돌려준다(파일은 커밋된 뒤에 지운다)."""
    if not post_ids:
        return []
    keys = [r[0] for r in conn.execute("SELECT storage_key FROM community.post_image WHERE post_id = ANY(%s)", (post_ids,)).fetchall()]
    conn.execute("DELETE FROM engine.peripheral_post_evidence WHERE post_id = ANY(%s)", (post_ids,))     # 임베딩은 함께 지워진다
    conn.execute("DELETE FROM engine.peripheral_post_intake WHERE post_id = ANY(%s)", (post_ids,))
    conn.execute("DELETE FROM community.post WHERE id = ANY(%s)", (post_ids,))                            # 연결 제품·이미지 행은 함께
    return keys


def restore_snapshot(conn, in_dir: Path, *, replace: bool = False, stale_keys: list[str] | None = None) -> dict:
    """스냅샷을 복원한다. `--replace` 로 지운 글의 이미지 중 새 스냅샷에 없는 파일 키는 `stale_keys` 에 담긴다
    (호출자가 커밋 뒤에 지운다)."""
    manifest = json.loads((in_dir / "manifest.json").read_text(encoding="utf-8"))
    mine = _signature(conn)
    diff = [t for t, sig in manifest["columns"].items() if mine.get(t) != sig]
    if diff:
        raise ValueError(f"테이블 열 구성이 달라 복원할 수 없다(마이그레이션 차이): {', '.join(diff)}")

    for table in TABLES:                                                  # 임시 테이블로 읽어 들인다
        cols = _columns(conn, table["name"])
        tmp = f"_snap_{table['file']}"
        conn.execute(f"CREATE TEMP TABLE {tmp} (LIKE {table['name']} INCLUDING DEFAULTS) ON COMMIT DROP")
        all_cols = list(cols)
        if table.get("product"):
            conn.execute(f"ALTER TABLE {tmp} ADD COLUMN _brand text, ADD COLUMN _model text")
            all_cols += ["_brand", "_model"]
        with conn.cursor() as cur, (in_dir / f"{table['file']}.copy").open("rb") as fh:
            with cur.copy(f"COPY {tmp} ({', '.join(all_cols)}) FROM STDIN") as copy:
                while chunk := fh.read(1 << 20):
                    copy.write(chunk)

    # 같은 글(id 또는 글 번호)이 이미 있으면 거절하거나 지우고 복원한다
    existing_posts = [r[0] for r in conn.execute(
        "SELECT p.id FROM community.post p JOIN _snap_post t ON t.id = p.id OR t.external_id = p.external_id").fetchall()]
    if existing_posts and not replace:
        raise ValueError(f"이미 있는 예시 글 {len(existing_posts)}편과 겹친다. --replace 로 지우고 복원한다.")
    old_keys = _delete_examples(conn, existing_posts)

    # 작성자 계정: 같은 이메일이 이 DB 에 있으면 그 계정 id 로 맞춘다(없으면 스냅샷의 계정을 만든다)
    conn.execute("""CREATE TEMP TABLE _snap_usermap ON COMMIT DROP AS
                    SELECT t.id AS old_id, COALESCE(u.id, t.id) AS new_id, (u.id IS NULL) AS is_new
                    FROM _snap_app_user t LEFT JOIN identity.app_user u ON u.email_normalized = t.email_normalized""")
    conn.execute("UPDATE _snap_post t SET author_user_id = m.new_id FROM _snap_usermap m WHERE t.author_user_id = m.old_id")
    conn.execute("UPDATE _snap_post_image t SET owner_user_id = m.new_id FROM _snap_usermap m WHERE t.owner_user_id = m.old_id")
    conn.execute("UPDATE _snap_peripheral_post_evidence t SET author_id = m.new_id FROM _snap_usermap m WHERE t.author_id = m.old_id")
    conn.execute("DELETE FROM _snap_app_user t USING _snap_usermap m WHERE t.id = m.old_id AND NOT m.is_new")

    # 제품을 이 DB 의 카탈로그에서 찾는다
    for table in TABLES:
        if not table.get("product"):
            continue
        tmp, col = f"_snap_{table['file']}", table["product"]
        missing = conn.execute(
            f"SELECT DISTINCT t._brand, t._model FROM {tmp} t LEFT JOIN catalog.product c ON c.brand = t._brand AND c.model = t._model "
            f"WHERE t.{col} IS NOT NULL AND c.id IS NULL").fetchall()
        ambiguous = conn.execute(
            f"SELECT t._brand, t._model FROM {tmp} t JOIN catalog.product c ON c.brand = t._brand AND c.model = t._model "
            f"WHERE t.{col} IS NOT NULL GROUP BY t._brand, t._model, t.ctid HAVING count(*) > 1 LIMIT 5").fetchall()
        if missing or ambiguous:
            raise ValueError(f"카탈로그에서 제품을 하나로 찾지 못했다: {[tuple(m) for m in (missing or ambiguous)][:5]}")
        conn.execute(
            f"UPDATE {tmp} t SET {col} = c.id FROM catalog.product c "
            f"WHERE t.{col} IS NOT NULL AND c.brand = t._brand AND c.model = t._model")

    restored: dict[str, int] = {}
    for table in TABLES:
        cols = _columns(conn, table["name"])
        tmp = f"_snap_{table['file']}"
        cur = conn.execute(f"INSERT INTO {table['name']} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM {tmp}")
        restored[table["name"]] = cur.rowcount

    # 이미지 파일을 저장소에 쓴다. 도중에 실패하면 이번에 새로 쓴 파일을 지우고 예외를 올린다(DB 는 호출자 쪽에서 롤백된다).
    store = svc._store()
    new_keys = [r[0] for r in conn.execute("SELECT storage_key FROM _snap_post_image").fetchall()]
    written: list[str] = []
    try:
        for key in new_keys:
            source = in_dir / "images" / key
            if not source.is_file():
                raise ValueError(f"스냅샷에 이미지 파일이 없다: {key}")
            existed = store.read(key) is not None
            store.save(key, source.read_bytes())
            if not existed:
                written.append(key)
    except Exception:
        for key in written:
            store.delete(key)
        raise
    if stale_keys is not None:
        stale_keys.extend(k for k in old_keys if k not in set(new_keys))
    return restored


def main() -> int:
    parser = argparse.ArgumentParser(description="예시 글 스냅샷 내보내기·복원")
    sub = parser.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export"); e.add_argument("folder", type=Path); e.add_argument("--prefix")
    r = sub.add_parser("restore"); r.add_argument("folder", type=Path); r.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    stale: list[str] = []
    try:
        with get_conn() as conn:
            if args.cmd == "export":
                manifest = export_snapshot(conn, args.folder, prefix=args.prefix)
                print(f"내보냄 → {args.folder}")
                for name, n in manifest["counts"].items():
                    print(f"  {name}: {n}")
                print(f"  이미지 파일: {len(manifest['images'])}")
            else:
                restored = restore_snapshot(conn, args.folder, replace=args.replace, stale_keys=stale)
                print("복원함")
                for name, n in restored.items():
                    print(f"  {name}: {n}")
    except (ValueError, FileNotFoundError) as exc:
        print(f"✗ {exc}")
        return 1
    if stale:                                                     # 커밋된 뒤에 교체돼 빠진 이미지 파일을 지운다
        svc._remove_files(stale)
    return 0


if __name__ == "__main__":
    sys.exit(main())
