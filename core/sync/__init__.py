"""
Offline-sync клиента (десктопа): локальный outbox + push→pull с курсорами.

Протокол — GenerationWeb/docs/architecture/offline_sync_protocol.md.
Чистый Python без Qt и внешних зависимостей: транспорт — urllib (или
инжектируемый callable в тестах).
"""

from .store import SyncStore
from .client import RepositorySyncListener, SyncClient, SyncReport

__all__ = ["SyncStore", "SyncClient", "SyncReport", "RepositorySyncListener"]
