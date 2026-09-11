"""identity.* 저장소."""
from __future__ import annotations
from uuid import UUID
from src.db.base import Repo

class ConversationRepo(Repo):
    def create(self, *, user_id: UUID | None, guest_session_hash: str | None) -> UUID:
        row = self._one("INSERT INTO identity.conversation (user_id, guest_session_hash) VALUES (%s, %s) RETURNING id", (user_id, guest_session_hash))
        return row["id"]

class UserRepo(Repo):
    pass
