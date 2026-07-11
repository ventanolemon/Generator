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
from core.contour import ContourClient
from core.settings import Settings
from core.sync import RepositorySyncListener, SyncClient, SyncStore
from bootstrap import build_registry, sync_database
from ui.app_context import AppContext
from ui.theme import apply_theme
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

    # Технические настройки среды (адрес backend, тема). Пробрасываются в окна
    # через AppContext.
    settings = Settings()

    # Тема оформления — единый QSS на всё приложение из выбранной палитры
    # (по умолчанию тёмная). Применяем до построения окон.
    apply_theme(app, settings.get_theme())

    # Клиент офлайн-синхронизации: outbox в той же БД. Слушателя мутаций
    # подключаем ПОСЛЕ sync_database — иначе стартовые сиды сыпались бы в
    # очередь при каждом запуске. Адрес backend берём из настроек (пусто —
    # только копим outbox, сеть не трогаем, пока адрес не задан в настройках).
    sync_store = SyncStore(DB_PATH)
    sync_client = SyncClient(repo, sync_store,
                             base_url=settings.get_base_url())
    repo.sync_listener = RepositorySyncListener(sync_client)

    # Мутабельный контейнер с текущей сессией. Передаётся в реестр и AppContext
    # замыканиями: один и тот же набор генераторов и одни и те же окна
    # корректно работают с разными пользователями без пересоздания при
    # перелогине. role по умолчанию 'student' (гость) — ролевые действия
    # (например, кнопка контура) скрыты, пока не войдёт teacher/admin.
    current_user: dict[str, str | None] = {"id": None, "role": "student"}

    def user_id_provider() -> str | None:
        return current_user["id"]

    def user_role_provider() -> str:
        return current_user["role"] or "student"

    # Клиент LLM-контура: тот же web_layer, что и синк; идентичность — из
    # сессии. Кнопка контура гейтится ролью teacher/admin.
    contour_client = ContourClient(base_url=settings.get_base_url(),
                                   user_id_provider=user_id_provider,
                                   user_role_provider=user_role_provider)

    def make_registry():
        return build_registry(
            repo, WORDS_DIR,
            stats_store=stats_store,
            user_id_provider=user_id_provider,
        )

    context = AppContext(
        repo=repo,
        settings=settings,
        user_id_provider=user_id_provider,
        user_role_provider=user_role_provider,
        sync_client=sync_client,
        contour_client=contour_client,
    )

    registry = make_registry()
    generator_window = GeneratorWindow(
        context=context,
        registry=registry,
        registry_builder=make_registry,
        stats_store=stats_store,
        words_dir=WORDS_DIR,
    )

    def on_auth(user_info):
        title = "Генератор заданий"
        if user_info is not None:
            current_user["id"] = user_info[0]
            # find_user → (login, FIO, group, role); роль гейтит UI-действия.
            current_user["role"] = (user_info[3] if len(user_info) > 3
                                    else "teacher") or "teacher"
            # Идентичность клиента синка — из сессии (заголовки X-User-*).
            sync_client.user_role = current_user["role"]
            title = f"Генератор заданий — {user_info[0]}"
        else:
            current_user["id"] = None
            current_user["role"] = "student"      # гость
        generator_window.setWindowTitle(title)
        generator_window.show()

    # Держим ссылки на окна входа/регистрации, чтобы Qt их не удалил, пока
    # пользователь навигирует между ними.
    windows: dict[str, object] = {}

    def show_auth() -> None:
        from ui.windows import AuthWindow as _Auth
        auth = _Auth(repository=repo, on_success=on_auth,
                     on_register=show_register)
        apply_theme(app, settings.get_theme())  # на случай смены темы в сессии
        windows["auth"] = auth
        auth.show()

    def show_register() -> None:
        from ui.windows import RegisterWindow as _Reg

        def on_registered(login: str) -> None:
            # Автологин сразу после регистрации: аккаунт только что создан
            # (create_user, роль teacher) — входим по известному логину/роли,
            # повторная проверка пароля не нужна.
            on_auth((login, "", "", "teacher"))

        reg = _Reg(repository=repo, on_success=on_registered,
                   on_back=show_auth)
        windows["register"] = reg
        reg.show()

    show_auth()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
