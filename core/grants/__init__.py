"""Выдача предметов преподавателям: клиент серверных прав (см.
docs/subject_grants.md)."""

from .client import GrantsClient, GrantsError

__all__ = ["GrantsClient", "GrantsError"]
