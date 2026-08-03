"""
Впечатать набор ключей выпуска в сборку — шаг выпуска, не разработки.

    python -m scripts.stamp_keyset --from-server https://api.example.org
    python -m scripts.stamp_keyset --from-file keyset.json
    python -m scripts.stamp_keyset --show

Переписывает `BUNDLED_KEYSET` в `core/updates/bundled.py`. Это корень
доверия клиента: всё, что приложение потом принимает — обновления, пакеты
узлов, следующие наборы ключей, — проверяется отсюда.

## Почему `payload` копируется, а не собирается

Подпись покрывает ТЕКСТ набора, а не его смысл. Пересобери его здесь хоть с
другим порядком ключей, хоть с пробелом после двоеточия — и проверка
сломается сразу у всех, кто получит следующую ротацию. Поэтому строка
переносится ровно как есть, а `--from-file` ждёт целиком ответ
`GET /updates/keys`, а не «ключ».

## Чем это НЕ является

Не способом раздать ключ пользователям по сети. Скачивание с сервера здесь
делает ВЫПУСКАЮЩИЙ, один раз, на своей машине, и обязан сверить отпечаток
глазами (`--expect-fingerprint`) с тем, что у него записано. Клиент,
который берёт ключ у того же сервера, что и обновление, не проверяет
ничего: подменивший сервер подменит и ключ.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.updates.keyring import parse_keyset          # noqa: E402
from core.updates.trust import key_fingerprint         # noqa: E402

TARGET = _ROOT / "core" / "updates" / "bundled.py"
_ASSIGNMENT = re.compile(
    r"^BUNDLED_KEYSET: dict = \{.*?^\}", re.MULTILINE | re.DOTALL)


def fetch(base_url: str) -> dict:
    url = base_url.rstrip("/") + "/updates/keys"
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode())


def render(payload: str, signature: str) -> str:
    return ("BUNDLED_KEYSET: dict = {\n"
            f"    \"payload\": {json.dumps(payload, ensure_ascii=False)},\n"
            f"    \"signature\": {json.dumps(signature, ensure_ascii=False)},\n"
            "}")


def show() -> int:
    from core.updates.bundled import BUNDLED_KEYSET
    payload = BUNDLED_KEYSET.get("payload") or ""
    if not payload.strip():
        print("В сборке нет набора ключей: клиент отвергнет всё.")
        return 1
    sequence, keys = parse_keyset(payload)
    print(f"набор sequence={sequence}, подписан: "
          f"{'да' if BUNDLED_KEYSET.get('signature') else 'нет (первый)'}")
    for key in keys:
        print(f"  {key['status']:<8} {key['id']}")
    return 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-server", metavar="URL",
                        help="взять GET /updates/keys с этого адреса")
    source.add_argument("--from-file", metavar="PATH",
                        help="файл с ответом GET /updates/keys целиком")
    source.add_argument("--show", action="store_true",
                        help="показать, что впечатано сейчас")
    parser.add_argument("--expect-fingerprint", action="append", default=[],
                        metavar="FP",
                        help="сверить отпечаток активного ключа; "
                             "не совпало — ничего не менять")
    args = parser.parse_args(argv)

    if args.show:
        return show()

    if args.from_server:
        response = fetch(args.from_server)
    else:
        response = json.loads(Path(args.from_file).read_text(encoding="utf-8"))

    if not response.get("configured"):
        print("Сервер сообщает, что набор ключей не настроен.", file=sys.stderr)
        return 2
    payload = response.get("payload") or ""
    signature = response.get("signature") or ""

    sequence, keys = parse_keyset(payload)           # заодно проверит канон
    active = [k for k in keys if k["status"] == "active"]
    if not active:
        print("В наборе нет активных ключей — впечатывать нечего.",
              file=sys.stderr)
        return 2

    fingerprints = {key_fingerprint(k["public_key"]) for k in active}
    if args.expect_fingerprint:
        expected = set(args.expect_fingerprint)
        if not expected <= fingerprints:
            print(f"Отпечатки не сошлись: ожидали {sorted(expected)}, "
                  f"в наборе {sorted(fingerprints)}. Ничего не изменено.",
                  file=sys.stderr)
            return 3

    source_text = TARGET.read_text(encoding="utf-8")
    if not _ASSIGNMENT.search(source_text):
        print(f"Не нашёл присваивание BUNDLED_KEYSET в {TARGET}.",
              file=sys.stderr)
        return 4
    TARGET.write_text(
        _ASSIGNMENT.sub(lambda _: render(payload, signature), source_text,
                        count=1),
        encoding="utf-8")

    print(f"Впечатан набор sequence={sequence} в {TARGET}")
    for fingerprint in sorted(fingerprints):
        print(f"  активный ключ {fingerprint}")
    if not signature:
        print("  (первый набор, подписи нет — это норма)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
