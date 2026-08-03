"""
Запускающий: доигрывает обновление и только потом стартует приложение.

    python -m scripts.update_launcher            # применить и запустить
    python -m scripts.update_launcher --status   # что установлено и что ждёт
    python -m scripts.update_launcher --no-apply # запустить, ничего не трогая

## Зачем отдельный процесс

Подменять дерево, из которого уже импортирован работающий код, нельзя. На
Windows это просто не выйдет — файлы заняты. На Linux выйдет, и это хуже:
процесс останется со старыми открытыми файлами, а любой ленивый импорт
после подмены притащит в него новый код, и падать оно будет в местах, по
которым причину не восстановить.

Поэтому переключение делает ЭТОТ модуль — до того, как импортировано хоть
что-то из дерева приложения, — а приложение запускается отдельным
процессом, уже из нового дерева. `Updater.apply_pending()` это же и
проверяет: он отказывается трогать каталог, внутри которого сам находится.

В управляемой установке запускающий лежит ВНЕ `home/app` и обновляется
вместе с установщиком, а не через этот канал.

## Что делает при старте

1. `recover()` — доигрывает переключение, оборванное на прошлом запуске:
   вперёд, если новое дерево готово, назад, если нет. Это единственное
   место, где пользователь может остаться без приложения, поэтому оно
   первое.
2. `apply_pending()` — применяет подготовленное, если оно есть.
3. запускает `main.py` из `home/app`.

Сеть здесь не трогается вовсе: скачивает и проверяет само приложение, когда
ему удобно, а запускающий только переключает уже проверенное. Так обрыв
связи не мешает запуску.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.updates import UpdateError, Updater          # noqa: E402
from core.updates.home import default_home, is_managed  # noqa: E402


def status(updater: Updater) -> int:
    state = updater.state
    print(f"каталог:     {updater.home.root}")
    print(f"установлено: {state.app_version() or '—'} "
          f"(выпуск {state.app_sequence()})")
    pending = state.pending()
    print(f"подготовлено: {pending['version']} (выпуск {pending['sequence']})"
          if pending else "подготовлено: нет")
    ring = updater.keyring
    if not ring.configured:
        print("ключи:       НЕТ — эта сборка не примет ни обновление, "
              "ни пакет")
    else:
        print(f"ключи:       набор {ring.sequence()}, активные: "
              f"{', '.join(ring.fingerprints())}")
    for dropped in ring.dropped:
        print(f"  внимание:  {dropped}")
    packages = state.packages()
    print(f"пакеты:      {', '.join(sorted(packages)) or '—'}")
    return 0


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true",
                        help="показать состояние и выйти")
    parser.add_argument("--no-apply", action="store_true",
                        help="не применять подготовленное")
    parser.add_argument("--home", default="", metavar="PATH",
                        help="управляемый каталог (иначе — по умолчанию)")
    args, rest = parser.parse_known_args(argv)

    from core.updates.updater import UpdateHome
    home = UpdateHome(Path(args.home).expanduser()) if args.home \
        else default_home()
    updater = Updater(home)

    if args.status:
        return status(updater)

    if not args.no_apply:
        try:
            applied = updater.apply_pending()
            if applied:
                print(f"установлена версия {applied['version']} "
                      f"(выпуск {applied['sequence']})")
        except UpdateError as exc:
            # Не срываем запуск: не применилось — работаем на прежней версии.
            # Оставить пользователя без программы из-за неудачного
            # обновления хуже, чем оставить его на старой.
            print(f"обновление не применено: {exc}", file=sys.stderr)

    if not is_managed(home):
        print(f"Каталог {home.app} не похож на установленное приложение — "
              f"запускать нечего. Из чекаута запускают main.py напрямую.",
              file=sys.stderr)
        return 1

    entry = home.app / "main.py"
    if not entry.exists():
        print(f"В дереве приложения нет {entry}.", file=sys.stderr)
        return 1
    return subprocess.call([sys.executable, str(entry), *rest], cwd=home.app)


if __name__ == "__main__":
    raise SystemExit(main())
