"""
Что у клиента установлено: версия приложения и набор пакетов узлов.

Файл, а не таблица в БД: состояние нужно ДО того, как приложение поднялось
(перед импортом собственного кода надо решить, не пора ли применить
подготовленное обновление), а база к этому моменту может быть занята,
недоступна или сама подлежать миграции.

## Зачем хранить `sequence`

Защита от отката. Клиент отвергает всё, у чего счётчик не больше
установленного, — иначе можно подсунуть СТАРЫЙ, честно подписанный релиз с
уже известной дырой, и подпись от этого не спасает: она валидна. Именно
счётчик, а не версия: сравнение semver — разбор строки, на котором легко
ошибиться (`1.10` против `1.9`).

Счётчик — единственное, что здесь нельзя терять. Потеря файла состояния
означает `sequence = 0`, то есть готовность принять любой подписанный
релиз, включая старый. Поэтому файл пишется атомарно (через временный) и
никогда не переписывается частично.

## Чем это не является

Не кешем каталога и не журналом: состояние отвечает на единственный вопрос
«что сейчас стоит». История выпусков живёт на сервере, ей здесь не место.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class InstallState:
    """Состояние установки — JSON-файл с атомарной записью."""

    def __init__(self, path: Path):
        self._path = Path(path)
        self._data: dict = {"app": {}, "packages": {}, "pending": None}
        self._load()

    # ---------- приложение ----------

    def app_version(self) -> str:
        return str(self._data.get("app", {}).get("version") or "")

    def app_sequence(self) -> int:
        return int(self._data.get("app", {}).get("sequence") or 0)

    def set_app(self, *, version: str, sequence: int,
                signing_key_id: str = "") -> None:
        self._data["app"] = {"version": str(version),
                             "sequence": int(sequence),
                             "signing_key_id": str(signing_key_id)}
        self._save()

    # ---------- подготовленное обновление ----------

    def pending(self) -> Optional[dict]:
        """Проверенное и распакованное, но ещё не применённое обновление."""
        value = self._data.get("pending")
        return dict(value) if isinstance(value, dict) else None

    def set_pending(self, value: Optional[dict]) -> None:
        self._data["pending"] = dict(value) if value else None
        self._save()

    # ---------- пакеты узлов ----------

    def packages(self) -> dict:
        return dict(self._data.get("packages") or {})

    def package(self, name: str) -> Optional[dict]:
        value = (self._data.get("packages") or {}).get(name)
        return dict(value) if isinstance(value, dict) else None

    def package_sequence(self, name: str) -> int:
        entry = self.package(name)
        return int(entry.get("sequence") or 0) if entry else 0

    def set_package(self, name: str, *, version: str, sequence: int,
                    api_version: str, node_types: list,
                    signing_key_id: str = "") -> None:
        packages = dict(self._data.get("packages") or {})
        packages[name] = {"version": str(version), "sequence": int(sequence),
                          "api_version": str(api_version),
                          "node_types": sorted(str(t) for t in node_types),
                          "signing_key_id": str(signing_key_id)}
        self._data["packages"] = packages
        self._save()

    def drop_package(self, name: str) -> bool:
        packages = dict(self._data.get("packages") or {})
        if name not in packages:
            return False
        packages.pop(name)
        self._data["packages"] = packages
        self._save()
        return True

    # ---------- диск ----------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Битый файл не «чиним» частично: потеря состояния означает
            # sequence = 0, то есть готовность принять старый релиз. Пусть
            # это будет видно как «ничего не установлено», а не как случайный
            # набор полей, часть которых уцелела.
            return
        if isinstance(raw, dict):
            self._data = {"app": raw.get("app") or {},
                          "packages": raw.get("packages") or {},
                          "pending": raw.get("pending")}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self._path)
