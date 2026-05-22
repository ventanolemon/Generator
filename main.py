"""
Точка входа.

Сборка приложения:
  1. Repository (БД)
  2. GeneratorRegistry со всеми зарегистрированными модулями
  3. AuthWindow → GeneratorWindow

GeneratorWindow получает фабрику build_registry — чтобы пересобирать
реестр после изменений в БД (создание/правка/удаление разделов).
"""

from __future__ import annotations
import sys

from PyQt6.QtWidgets import QApplication

from const import DB_PATH, WORDS_DIR
from core import Repository, WordStatsStore
from bootstrap import build_registry, sync_database
from ui.windows import AuthWindow, GeneratorWindow


def main() -> int:
    app = QApplication(sys.argv)
    repo = Repository(DB_PATH)

    # При старте гарантируем структуру БД: subjects, code-only разделы,
    # таблица WordStats. После этого build_registry соберёт всё корректно.
    sync_database(repo, WORDS_DIR)

    # Единое хранилище межсессионной статистики словарного тренажёра.
    # Для авторизованных — SQLite, для гостей — in-memory (общая на запуск).
    stats_store = WordStatsStore(repo)

    # Мутабельный контейнер с текущим user_id. Передаётся в реестр замыканием:
    # один и тот же набор генераторов корректно работает с разными пользователями
    # без пересоздания реестра при перелогине.
    current_user: dict[str, str | None] = {"id": None}

    def user_id_provider() -> str | None:
        return current_user["id"]

    def make_registry():
        return build_registry(
            repo, WORDS_DIR,
            stats_store=stats_store,
            user_id_provider=user_id_provider,
        )

    registry = make_registry()
    generator_window = GeneratorWindow(
        repository=repo,
        registry=registry,
        registry_builder=make_registry,
    )

    def on_auth(user_info):
        title = "Генератор заданий"
        if user_info is not None:
            current_user["id"] = user_info[0]
            title = f"Генератор заданий — {user_info[0]}"
        else:
            current_user["id"] = None
        generator_window.setWindowTitle(title)
        generator_window.show()

    auth = AuthWindow(repository=repo, on_success=on_auth)
    auth.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
