"""
Корень доверия клиента: канонизация манифестов и проверка подписи Ed25519.

Это ЗЕРКАЛО серверного `core/signing.py` (репозиторий GenerationWeb) и
функции `signing_keys.canonical_keyset`. Зеркало, а не «похожая реализация»:
подписывающая сторона и проверяющая обязаны получать байт в байт одно и то
же. Разойдётся сериализация — подпись перестанет сходиться у ВСЕХ сразу, и
выглядеть это будет не как «поменяли формат», а как «сервер подсовывает
подделку», после чего сутки уходят на поиск лишнего пробела.

Поэтому:

* формат зафиксирован золотыми векторами в tests/test_updates_trust.py —
  те же байты продублированы в серверных тестах; изменение с одной стороны
  ломает тесты с обеих;
* типы приводятся явно (`int_fields` — к целому, остальное к строке): у
  клиента значения приезжают из JSON, у подписывающего скрипта — из
  argparse, и `1` против `"1"` дало бы «подпись то сходится, то нет»;
* разбирать и пересобирать `payload` набора ключей НЕЛЬЗЯ — он проверяется
  ровно теми байтами, которыми приехал.

## Почему проверка вообще на клиенте

Сервер входит в модель угроз. HTTPS защищает канал, но не отвечает на
вопрос «тот ли это выпустил»; на него отвечает только подпись, проверенная
клиентом по ключу, который клиент носит с собой. `sha256` из манифеста —
про порчу при скачивании, а не про подлинность: подменивший файл подменит и
хеш.

## Отсутствие cryptography — отказ, а не пропуск проверки

Если библиотеки нет, `verify` бросает. Принять неподписанный код, потому
что нечем проверить подпись, — ровно та ситуация, ради которой всё это
писалось.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Iterable


class TrustError(ValueError):
    """Подпись не сошлась, не разбирается или проверить её нечем."""


def canonical_manifest(payload: dict, fields: Iterable[str],
                       int_fields: Iterable[str] = ()) -> bytes:
    """
    Байты, которые подписывают и проверяют.

    `fields` задаёт СОСТАВ подписанного: добавишь поле — все ранее
    выпущенные подписи перестанут сходиться. Порядок не важен, ключи
    сортируются.
    """
    int_fields = set(int_fields)
    canonical = {}
    for field in fields:
        value = payload.get(field)
        canonical[field] = (int(value or 0) if field in int_fields
                            else str(value or ""))
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def canonical_keyset(sequence: int, keys: list) -> str:
    """
    Канонический текст набора ключей — строкой, а не байтами: именно она
    хранится и передаётся, и проверяется её же кодировкой.

    Клиенту эта функция нужна ровно для одного: убедиться, что приехавший
    `payload` действительно канонизирован. Без такой проверки сервер мог бы
    прислать набор, чей текст подписан, но чьё СОДЕРЖИМОЕ после разбора
    отличается от того, что подписывали (лишние поля, дубли ключей), — и
    клиент доверился бы разобранному виду, а не подписанному.
    """
    payload = {
        "sequence": int(sequence),
        "keys": sorted(
            ({"id": str(k["id"]), "public_key": str(k["public_key"]),
              "status": str(k.get("status", "active"))} for k in keys),
            key=lambda k: k["id"]),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def verify(manifest_bytes: bytes, signature_b64: str,
           public_key_b64: str) -> None:
    """Проверить подпись канонических байтов. Бросает TrustError."""
    if not (public_key_b64 or "").strip():
        raise TrustError(
            "Публичный ключ не настроен — принять подписанное содержимое, "
            "не имея чем проверить подпись, нельзя.")
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PublicKey)
    except ImportError as exc:                       # pragma: no cover
        raise TrustError(
            "Нет библиотеки cryptography — проверить подпись невозможно. "
            "Принимать без проверки нельзя.") from exc

    try:
        key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(public_key_b64, validate=True))
        signature = base64.b64decode(signature_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TrustError(f"Ключ или подпись не разбираются: {exc}") from exc

    try:
        key.verify(signature, manifest_bytes)
    except InvalidSignature as exc:
        raise TrustError(
            "Подпись не соответствует манифесту. Содержимое или его описание "
            "изменены после подписания — принимать нельзя.") from exc


def key_fingerprint(public_key_b64: str) -> str:
    """Короткий отпечаток ключа — для сверки глазами и для записи «чем
    именно проверено». Для самих проверок не годится: это не подпись."""
    try:
        raw = base64.b64decode(public_key_b64 or "", validate=True)
    except (binascii.Error, ValueError):
        return ""
    return hashlib.sha256(raw).hexdigest()[:16]


def sha256_file(path, chunk: int = 1 << 20) -> str:
    """sha256 файла потоком: артефакт может не помещаться в память."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()
