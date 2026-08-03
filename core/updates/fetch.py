"""
Скачивание артефакта: карантин, ограничение размера, сверка хеша.

Порядок здесь важнее кода. Подпись проверяется ДО скачивания — она
покрывает манифест, в котором уже лежат `size_bytes` и `sha256`. То есть к
моменту, когда мы вообще открываем соединение, нам уже известно, какой
длины и с каким хешем должен приехать файл, и известно это из подписанного
источника.

Отсюда три свойства:

* **Размер ограничен подписанным** `size_bytes`. Без ограничения сервер
  (или тот, кто им притворился) отдаёт бесконечный поток и забивает диск;
  проверка хеша от этого не спасает — она случится, когда места уже нет.
* **Файл падает в карантин**, а не туда, где его кто-то подхватит.
  Скачанный, но не сверенный файл — не «почти обновление», а чужие байты.
* **Хеш считается на лету** и сверяется с подписанным. Не сошёлся — файл
  удаляется сразу, а не остаётся «на всякий случай»: единственное, для чего
  он потом сгодится, — быть случайно запущенным.

`sha256` отвечает на «не побился ли файл в пути», подпись — на «тот ли его
выпустил». Одно другого не заменяет, поэтому здесь есть и то, и другое.
"""

from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path
from typing import Callable, Optional

# path, expected_size → байты. Инжектируем ради тестов: боевой ходит в сеть,
# тестовый отдаёт из памяти.
Downloader = Callable[[str, int], bytes]

CHUNK = 1 << 16


class DownloadError(RuntimeError):
    """Не скачалось, приехало не то или приехало слишком много."""


def http_downloader(timeout: int = 120) -> Downloader:
    def download(url: str, expected_size: int) -> bytes:
        # Читаем не более подписанного размера плюс один байт: лишний байт —
        # признак того, что отдают не то, что подписано, и повод оборвать
        # чтение, а не докачивать до конца ради красивой диагностики.
        limit = int(expected_size or 0)
        chunks: list[bytes] = []
        received = 0
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            while True:
                block = resp.read(CHUNK)
                if not block:
                    break
                received += len(block)
                if limit and received > limit:
                    raise DownloadError(
                        f"Артефакт длиннее подписанного размера "
                        f"({limit} байт) — скачивание оборвано.")
                chunks.append(block)
        return b"".join(chunks)
    return download


def fetch_verified(url: str, *, expected_size: int, expected_sha256: str,
                   quarantine: Path, downloader: Optional[Downloader] = None,
                   ) -> Path:
    """
    Скачать в карантин и сверить с подписанным описанием.

    Возвращает путь к файлу в карантине. Не сошлось — файла не остаётся.
    """
    downloader = downloader or http_downloader()
    quarantine = Path(quarantine)
    quarantine.parent.mkdir(parents=True, exist_ok=True)

    try:
        data = downloader(url, int(expected_size or 0))
    except DownloadError:
        raise
    except Exception as exc:
        raise DownloadError(f"Не удалось скачать {url}: {exc}") from exc

    if expected_size and len(data) != int(expected_size):
        raise DownloadError(
            f"Размер не совпал с подписанным: приехало {len(data)} байт, "
            f"подписано {int(expected_size)}.")

    digest = hashlib.sha256(data).hexdigest()
    if digest != (expected_sha256 or "").lower():
        raise DownloadError(
            f"sha256 не совпал с подписанным: приехало {digest}, "
            f"подписано {expected_sha256}. Файл повреждён или подменён.")

    quarantine.write_bytes(data)
    return quarantine
