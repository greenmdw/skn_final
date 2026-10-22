"""내 현재 PC · 사용자별 JSON 문서 · 견적서별 부가 정보 저장소(마이그레이션 0018).

규칙 판단(키 이름·크기·개수 제한, 소유권)은 서비스(src/services/me_service.py)가 하고, 여기는 쿼리만 한다."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from src.db.base import Repo


class MeRepo(Repo):
    # ── 내 현재 PC ──────────────────────────────────────────────────────────────────
    def get_pc(self, user_id: UUID) -> dict | None:
        return self._one("SELECT parts, source, title, saved_at FROM identity.user_pc WHERE user_id = %s", (user_id,))

    def put_pc(self, user_id: UUID, *, parts: dict[str, str], source: str, title: str) -> dict:
        return self._one(
            """INSERT INTO identity.user_pc (user_id, parts, source, title, saved_at) VALUES (%s, %s, %s, %s, now())
               ON CONFLICT (user_id) DO UPDATE SET parts = EXCLUDED.parts, source = EXCLUDED.source, title = EXCLUDED.title, saved_at = now()
               RETURNING parts, source, title, saved_at""",
            (user_id, Jsonb(parts), source, title))

    def delete_pc(self, user_id: UUID) -> bool:
        return self._one("DELETE FROM identity.user_pc WHERE user_id = %s RETURNING user_id", (user_id,)) is not None

    # ── 사용자별 JSON 문서 ───────────────────────────────────────────────────────────
    def list_data(self, user_id: UUID) -> list[dict]:
        return self._all(
            "SELECT key, pg_column_size(value) AS size_bytes, updated_at FROM identity.user_data WHERE user_id = %s ORDER BY key", (user_id,))

    def count_data(self, user_id: UUID) -> int:
        return int(self._one("SELECT count(*) AS n FROM identity.user_data WHERE user_id = %s", (user_id,))["n"])

    def data_exists(self, user_id: UUID, key: str) -> bool:
        return self._one("SELECT 1 AS x FROM identity.user_data WHERE user_id = %s AND key = %s", (user_id, key)) is not None

    def get_data(self, user_id: UUID, key: str) -> dict | None:
        return self._one("SELECT key, value, updated_at FROM identity.user_data WHERE user_id = %s AND key = %s", (user_id, key))

    def put_data(self, user_id: UUID, key: str, value: Any) -> dict:
        return self._one(
            """INSERT INTO identity.user_data (user_id, key, value) VALUES (%s, %s, %s)
               ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value
               RETURNING key, value, updated_at""",
            (user_id, key, Jsonb(value)))

    def delete_data(self, user_id: UUID, key: str) -> bool:
        return self._one("DELETE FROM identity.user_data WHERE user_id = %s AND key = %s RETURNING key", (user_id, key)) is not None

    # ── 견적서(목록)별 부가 정보 ─────────────────────────────────────────────────────
    def get_extras(self, plan_id: UUID) -> dict | None:
        return self._one("SELECT extras, updated_at FROM planning.plan_extras WHERE plan_id = %s", (plan_id,))

    def put_extras(self, plan_id: UUID, extras: dict) -> dict:
        return self._one(
            """INSERT INTO planning.plan_extras (plan_id, extras) VALUES (%s, %s)
               ON CONFLICT (plan_id) DO UPDATE SET extras = EXCLUDED.extras
               RETURNING extras, updated_at""",
            (plan_id, Jsonb(extras)))

    def delete_extras(self, plan_id: UUID) -> bool:
        return self._one("DELETE FROM planning.plan_extras WHERE plan_id = %s RETURNING plan_id", (plan_id,)) is not None

    def list_extras_for_user(self, user_id: UUID, limit: int) -> list[dict]:
        """내 활성 목록의 부가 정보 전부(최근 수정순). 사이드바·마이페이지가 한 번에 읽는다."""
        return self._all(
            """SELECT e.plan_id, e.extras, e.updated_at
               FROM planning.plan_extras e JOIN planning.plan p ON p.id = e.plan_id
               WHERE p.owner_user_id = %s AND p.status = 'active' ORDER BY e.updated_at DESC LIMIT %s""",
            (user_id, limit))
