"""
Клиентская половина доставки кода: обновление приложения и пакеты узлов.

Серверная лежит в GenerationWeb (`core/updates.py`, `core/node_packages.py`,
`core/signing_keys.py`) и делает ровно одно — хранит и раздаёт подписанное,
не подписывая. Смысл ей придаёт эта половина: сервер входит в модель угроз,
и подлинность даёт не он, а подпись, проверенная здесь ключом, который
приложение носит с собой (`bundled.py`).

Что откуда:

    trust.py      канонизация и Ed25519 — зеркало серверного core/signing.py
    bundled.py    зашитый в сборку набор ключей: корень доверия
    keyring.py    цепочка доверия и приём ротации
    state.py      что установлено (и главное — с каким `sequence`)
    fetch.py      скачивание в карантин со сверкой размера и хеша
    updater.py    обновление приложения: проверка, подготовка, переключение
    packages.py   пакеты узлов: то же самое плюс подключение в реестр

Разделение, из которого всё следует: функционал приезжает ПОЛНЫМИ
обновлениями приложения, данные (предметы, разделы, графы) — обычной
синхронизацией (`core/sync`). Граф — композиция существующих узлов, то есть
данные. Новый ТИП узла — Python-код, и приезжает он только сюда.
"""

from .fetch import DownloadError
from .home import default_home, default_root, is_managed
from .keyring import Keyring, KeyringError
from .packages import (
    PackageError, PackageInstaller, load_installed, registry_with_packages,
)
from .state import InstallState
from .trust import TrustError
from .updater import UpdateError, UpdateHome, Updater

__all__ = [
    "DownloadError", "InstallState", "Keyring", "KeyringError",
    "PackageError", "PackageInstaller", "TrustError", "UpdateError",
    "UpdateHome", "Updater", "default_home", "default_root", "is_managed",
    "load_installed", "registry_with_packages",
]
