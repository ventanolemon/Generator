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
from core import Repository
from bootstrap import build_registry, sync_database
from ui.windows import AuthWindow, GeneratorWindow


def main() -> int:
    app = QApplication(sys.argv)
    repo = Repository(DB_PATH)

    # При старте гарантируем структуру БД: subjects и code-only разделы.
    # После этого build_registry соберёт всё корректно.
    sync_database(repo, WORDS_DIR)

    def make_registry():
        return build_registry(repo, WORDS_DIR)

    registry = make_registry()
    generator_window = GeneratorWindow(
        repository=repo,
        registry=registry,
        registry_builder=make_registry,
    )

    def on_auth(user_info):
        title = "Генератор заданий"
        if user_info is not None:
            title = f"Генератор заданий — {user_info[0]}"
        generator_window.setWindowTitle(title)
        generator_window.show()

    auth = AuthWindow(repository=repo, on_success=on_auth)
    auth.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
