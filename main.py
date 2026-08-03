"""
Точка входа.

Сборка приложения:
  1. Repository (БД)
  2. установленные пакеты узлов → общий реестр узлов
  3. GeneratorRegistry со всеми зарегистрированными модулями
  4. AuthWindow → GeneratorWindow

GeneratorWindow получает фабрику build_registry — чтобы пересобирать
реестр после изменений в БД (создание/правка/удаление разделов).
"""

from __future__ import annotations
import sys

from PyQt6.QtWidgets import QApplication

from const import DB_PATH, WORDS_DIR
from core import Repository, WordStatsStore
from core.admin import AdminClient
from core.analytics import AnalyticsClient
from core.assignments import AssignmentsClient
from core.contour import ContourClient
from core.grants import GrantsClient
from core.session import Session
from core.settings import Settings
from core.sync import RepositorySyncListener, SyncClient, SyncStore
from core.updates import load_installed
from bootstrap import build_registry, sync_database
from ui.app_context import AppContext
from ui.theme import apply_theme
from ui.windows import AuthWindow, GeneratorWindow


def main() -> int:
    app = QApplication(sys.argv)
    repo = Repository(DB_PATH)

    # Установленные пакеты узлов — ДО всего остального: они дополняют общий
    # реестр узлов, а тот стоит умолчанием у исполнителя, документа и
    # палитры, причём часть кода берёт его ленивым импортом. Подключишь
    # позже — половина приложения увидит пакеты, половина нет.
    #
    # Ничего не бросает: пакеты — дополнение, и приложение обязано
    # подниматься без них (и с одним битым пакетом тоже).
    packages_report = load_installed()
    for name, reason in sorted(packages_report["failed"].items()):
        print(f"[пакеты] {name}: не подключён — {reason}", file=sys.stderr)

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

    # Единая идентичность сессии (core.session.Session): один явный источник
    # правды для провайдеров AppContext, клиентов синка/контура, атрибуции
    # попыток и WordStats. Канонический id = login (см. core/session.py).
    # Переживает перелогин без пересоздания реестра/окон. По умолчанию —
    # гость (роль 'student'): ролевые действия (кнопка контура) скрыты, пока
    # не войдёт teacher/admin.
    session = Session()

    def user_id_provider() -> str | None:
        return session.user_id

    def user_role_provider() -> str:
        return session.role

    # Клиент LLM-контура: тот же web_layer, что и синк; идентичность — из
    # сессии. Кнопка контура гейтится ролью teacher/admin.
    contour_client = ContourClient(base_url=settings.get_base_url(),
                                   user_id_provider=user_id_provider,
                                   user_role_provider=user_role_provider)

    # Клиент администрирования (пользователи/роли, группы): тот же web_layer.
    # Кнопка окна гейтится admin + заданным адресом сервера (can_use).
    admin_client = AdminClient(base_url=settings.get_base_url(),
                               user_id_provider=user_id_provider,
                               user_role_provider=user_role_provider)

    # Клиент аналитики (дашборд успеваемости): тот же web_layer. Кнопка
    # гейтится teacher/admin + заданным адресом сервера (can_use).
    analytics_client = AnalyticsClient(base_url=settings.get_base_url(),
                                       user_id_provider=user_id_provider,
                                       user_role_provider=user_role_provider)

    # Клиент домашек (выдача заданий группам / просмотр студентом): тот же
    # web_layer. Кнопка видна вошедшему пользователю (гейтинг ролью в окне).
    assignments_client = AssignmentsClient(base_url=settings.get_base_url(),
                                           user_id_provider=user_id_provider,
                                           user_role_provider=user_role_provider)

    # Клиент выдач предметов: тот же web_layer. Читают его двое — витрина
    # преподавателя (снимок обновляется вместе с синком) и вкладка матрицы в
    # окне администрирования (она гейтится admin, can_manage).
    grants_client = GrantsClient(base_url=settings.get_base_url(),
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
        admin_client=admin_client,
        analytics_client=analytics_client,
        assignments_client=assignments_client,
        grants_client=grants_client,
    )

    def do_logout() -> None:
        # Сброс идентичности к гостю и возврат к экрану входа. hide() (не
        # close()) — иначе QApplication.quitOnLastWindowClosed завершил бы
        # приложение, ведь на момент выхода это единственное окно.
        # show_auth определена ниже — доступна по замыканию к моменту вызова.
        session.set_guest()
        sync_client.user_id = None
        sync_client.user_role = session.role
        generator_window.hide()
        show_auth()

    registry = make_registry()
    generator_window = GeneratorWindow(
        context=context,
        registry=registry,
        registry_builder=make_registry,
        stats_store=stats_store,
        words_dir=WORDS_DIR,
        on_logout=do_logout,
    )

    def on_auth(user_info):
        title = "Генератор заданий"
        if user_info is not None:
            # find_user → (login, FIO, group, role); роль гейтит UI-действия.
            role = user_info[3] if len(user_info) > 3 else None
            session.set_user(user_info[0], role)
            title = f"Генератор заданий — {session.login}"
        else:
            session.set_guest()
        # Идентичность клиента синка — из сессии (заголовки X-User-*). Без
        # user_id push уходил бы без X-User-Id (SyncClient._http_transport
        # шлёт заголовок, только если user_id не None) — правки/попытки были
        # бы неатрибутируемы.
        sync_client.user_id = session.user_id
        sync_client.user_role = session.role
        generator_window.setWindowTitle(title)
        generator_window.show()

    # Держим ссылки на окна входа/регистрации, чтобы Qt их не удалил, пока
    # пользователь навигирует между ними.
    windows: dict[str, object] = {}

    def show_auth() -> None:
        from ui.windows import AuthWindow as _Auth
        auth = _Auth(repository=repo, on_success=on_auth,
                     on_register=show_register, settings=settings)
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
