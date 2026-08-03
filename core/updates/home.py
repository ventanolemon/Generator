"""
Где лежит управляемый каталог: состояние, ключи, пакеты, подготовленное.

Не рядом с исходниками. Приложение может стоять там, куда пользователю
нельзя писать (Program Files, /opt, /usr/local), и обычно так и стоит; а
пакеты узлов и цепочку ключей писать надо. Поэтому каталог — в
пользовательских данных, и путь у каждой ОС свой.

`GENERATOR_UPDATE_HOME` перекрывает всё — этим пользуются тесты, портативные
сборки и запуск нескольких копий рядом.

## Управляемая установка и обычный запуск из исходников

Подменять дерево приложения имеет смысл только там, где это дерево положил
установщик: `home/app`. Запуск из чекаута (разработка, тесты) — не
управляемая установка, и обновлять там нечего; `is_managed()` отвечает
именно на этот вопрос.

Пакеты узлов при этом работают и там, и там: они не трогают дерево
приложения, а живут в `home/packages`. Разработчик ставит пакет так же, как
пользователь, — иначе воспроизвести его проблему было бы нечем.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .updater import UpdateHome

ENV_VAR = "GENERATOR_UPDATE_HOME"
_APP_DIR = "Generator"


def default_root() -> Path:
    override = os.environ.get(ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return Path(base or Path.home()) / _APP_DIR
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / _APP_DIR
    base = os.environ.get("XDG_DATA_HOME", "").strip()
    return Path(base or (Path.home() / ".local" / "share")) / _APP_DIR


def default_home() -> UpdateHome:
    """Управляемый каталог этой машины. Не создаётся до первой записи."""
    return UpdateHome(default_root())


def is_managed(home: UpdateHome | None = None) -> bool:
    """Положил ли дерево приложения установщик — то есть есть ли что
    подменять. Запуск из чекаута сюда не попадает и попадать не должен."""
    return (home or default_home()).app.is_dir()
