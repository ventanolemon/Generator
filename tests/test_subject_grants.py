"""
Выдача предметов преподавателям (docs/subject_grants.md):

  * снимок выдач в Repository и фильтр витрины: нет снимка — не ограничиваем,
    режим умолчания, отзыв через полную замену, независимость от личного
    скрытия, ключевание логином;
  * GrantsClient: разбор ответов, разрешающий фолбэк на кривом/старом ответе,
    запись снимка, отказ сети не глотается;
  * scope-эпоха в синке: resync со sweep убирает отозванное, НЕ трогает
    встроенные предметы и неподтверждённую сервером локальную работу, НЕ
    шлёт tombstone'ы, эпоха сохраняется только после успешного sweep и
    ключуется логином;
  * вкладка матрицы в AdminWindow: отрисовка, черновик, последовательное
    сохранение строк, сброс, фильтр.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_subject_grants
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.grants import GrantsClient, GrantsError  # noqa: E402
from core.repository import GrantsSnapshot, Repository  # noqa: E402
from core.sync import SyncClient, SyncStore  # noqa: E402
from tests.test_sync_client import FakeServer, _make_local_db  # noqa: E402
from core.tmpdb import temp_path  # noqa: E402

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False


# ---------- Фейк-сервер выдач ----------

class FakeGrantsServer:
    """Сервер API выдач в памяти: /subjects/grants/mine + админская матрица."""

    def __init__(self):
        self.default_access = "all"
        self.scope_version = 3
        self.grants: dict[str, set[int]] = {"ivanov": {1, 3}, "petrova": set()}
        self.teachers = [{"login": "ivanov", "fio": "Иванов И.И."},
                         {"login": "petrova", "fio": "Петрова А.С."}]
        self.subjects = [
            {"id": 1, "subject_name": "Линейная алгебра", "is_builtin": True},
            {"id": 2, "subject_name": "Английский", "is_builtin": True},
            {"id": 3, "subject_name": "Физика", "is_builtin": True},
        ]
        self.puts: list[tuple[str, list[int]]] = []
        self.fail_next = False
        self.viewer = "ivanov"

    def transport(self, path: str, payload, method: str) -> dict:
        if self.fail_next:
            self.fail_next = False
            raise GrantsError("HTTP 503: сервер недоступен", status=503)
        if path == "/subjects/grants/mine" and method == "GET":
            return {"scope_version": self.scope_version,
                    "default_access": self.default_access,
                    "subject_ids": sorted(self.grants.get(self.viewer, set()))}
        if path == "/admin/subject-grants" and method == "GET":
            return {"default_access": self.default_access,
                    "teachers": list(self.teachers),
                    "subjects": list(self.subjects),
                    "grants": {k: sorted(v) for k, v in self.grants.items()}}
        if path.startswith("/admin/subject-grants/") and method == "PUT":
            tail = path.rsplit("/", 1)[1]
            if tail == "default-access":
                self.default_access = payload["default_access"]
                self.scope_version += 1
                return {"ok": True}
            ids = [int(s) for s in payload["subject_ids"]]
            self.puts.append((tail, ids))
            self.grants[tail] = set(ids)
            self.scope_version += 1
            return {"ok": True, "scope_version": self.scope_version}
        raise AssertionError(f"неизвестный вызов {method} {path}")


def _client(server: FakeGrantsServer, *, role="teacher", login="ivanov",
            base_url="http://x") -> GrantsClient:
    return GrantsClient(base_url=base_url, transport=server.transport,
                        user_id_provider=lambda: login,
                        user_role_provider=lambda: role)


# ---------- Снимок выдач и фильтр витрины ----------

class GrantsRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.db_path = temp_path(suffix=".db")
        _make_local_db(self.db_path)
        self.repo = Repository(self.db_path)
        self.repo.ensure_hidden_columns()
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO Subjects (id, subject_name, pra_subject) "
                "VALUES (?, ?, ?)",
                [(1, "Линал", "Линал"), (2, "Английский", "Английский"),
                 (3, "Физика", "Физика")])
        self.addCleanup(lambda: os.path.exists(self.db_path)
                        and os.unlink(self.db_path))

    def _names(self, **kw) -> set[str]:
        return {s.name for s in self.repo.list_subjects(**kw)}

    def test_no_snapshot_does_not_restrict(self):
        # Сервер ещё не отвечал: витрина полная. Отказ сети не должен
        # выглядеть как отзыв прав.
        self.assertIsNone(self.repo.get_grants("ivanov"))
        self.assertEqual(
            self._names(user_login="ivanov", apply_grants=True),
            {"Линал", "Английский", "Физика"})

    def test_default_all_with_no_grants_does_not_restrict(self):
        self.repo.save_grants("ivanov", [], default_access="all")
        self.assertEqual(
            self._names(user_login="ivanov", apply_grants=True),
            {"Линал", "Английский", "Физика"})

    def test_grants_restrict_even_in_default_all(self):
        # Как только выдали хоть один предмет, набор становится исчерпывающим:
        # разграничение включается по мере раздачи.
        self.repo.save_grants("ivanov", [1, 3], default_access="all")
        self.assertEqual(self._names(user_login="ivanov", apply_grants=True),
                         {"Линал", "Физика"})

    def test_strict_mode_with_no_grants_shows_nothing(self):
        self.repo.save_grants("ivanov", [], default_access="none")
        self.assertEqual(self._names(user_login="ivanov", apply_grants=True),
                         set())

    def test_save_replaces_snapshot_so_revocation_works(self):
        self.repo.save_grants("ivanov", [1, 2, 3])
        self.repo.save_grants("ivanov", [2])
        self.assertEqual(self._names(user_login="ivanov", apply_grants=True),
                         {"Английский"})

    def test_snapshot_is_per_login(self):
        self.repo.save_grants("ivanov", [1])
        self.repo.save_grants("petrova", [2])
        self.assertEqual(self._names(user_login="ivanov", apply_grants=True),
                         {"Линал"})
        self.assertEqual(self._names(user_login="petrova", apply_grants=True),
                         {"Английский"})

    def test_apply_grants_off_ignores_snapshot(self):
        # Админ и гость зовут без apply_grants — снимок не влияет.
        self.repo.save_grants("ivanov", [1], default_access="none")
        self.assertEqual(self._names(user_login="ivanov"),
                         {"Линал", "Английский", "Физика"})

    def test_grants_and_personal_hiding_are_independent(self):
        self.repo.save_grants("ivanov", [1, 2])
        self.repo.set_subject_hidden(1, True, user_login="ivanov")
        # Выдан, но лично скрыт — не показывается.
        self.assertEqual(self._names(user_login="ivanov", apply_grants=True),
                         {"Английский"})
        # Отзыв и возврат доступа не стирают личный выбор.
        self.repo.save_grants("ivanov", [2])
        self.repo.save_grants("ivanov", [1, 2])
        self.assertEqual(self._names(user_login="ivanov", apply_grants=True),
                         {"Английский"})
        self.assertEqual(
            self._names(user_login="ivanov", apply_grants=True,
                        include_hidden=True),
            {"Линал", "Английский"})

    def test_clear_grants_removes_restriction(self):
        self.repo.save_grants("ivanov", [1], default_access="none")
        self.repo.clear_grants("ivanov")
        self.assertIsNone(self.repo.get_grants("ivanov"))
        self.assertEqual(self._names(user_login="ivanov", apply_grants=True),
                         {"Линал", "Английский", "Физика"})

    def test_guest_has_no_snapshot(self):
        self.assertIsNone(self.repo.get_grants(None))
        with self.assertRaises(ValueError):
            self.repo.save_grants("", [1])

    def test_rejects_unknown_default_access(self):
        with self.assertRaises(ValueError):
            self.repo.save_grants("ivanov", [1], default_access="maybe")

    def test_snapshot_roundtrip_keeps_scope_version(self):
        self.repo.save_grants("ivanov", [3, 1, 1], scope_version=42,
                              default_access="none")
        snap = self.repo.get_grants("ivanov")
        self.assertEqual(snap.subject_ids, frozenset({1, 3}))
        self.assertEqual(snap.scope_version, 42)
        self.assertEqual(snap.default_access, "none")


class GrantsSnapshotSemanticsTests(unittest.TestCase):
    def test_restricts_matrix(self):
        self.assertFalse(GrantsSnapshot().restricts)
        self.assertFalse(GrantsSnapshot(frozenset(), "all").restricts)
        self.assertTrue(GrantsSnapshot(frozenset({1}), "all").restricts)
        self.assertTrue(GrantsSnapshot(frozenset(), "none").restricts)

    def test_allows(self):
        snap = GrantsSnapshot(frozenset({1, 2}), "all")
        self.assertTrue(snap.allows(1))
        self.assertFalse(snap.allows(9))
        self.assertTrue(GrantsSnapshot().allows(9))   # без ограничения — всё


# ---------- Клиент ----------

class GrantsClientTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeGrantsServer()
        self.client = _client(self.server)
        self.db_path = temp_path(suffix=".db")
        _make_local_db(self.db_path)
        self.repo = Repository(self.db_path)
        self.addCleanup(lambda: os.path.exists(self.db_path)
                        and os.unlink(self.db_path))

    def test_my_grants_parses_snapshot(self):
        snap = self.client.my_grants()
        self.assertEqual(snap.subject_ids, frozenset({1, 3}))
        self.assertEqual(snap.default_access, "all")
        self.assertEqual(snap.scope_version, 3)

    def test_unknown_default_access_falls_back_to_permissive(self):
        # Старый/кривой сервер не должен запирать преподавателя.
        self.server.default_access = "strict-ish"
        self.assertEqual(self.client.my_grants().default_access, "all")

    def test_matrix_normalizes_grants_to_int_sets(self):
        matrix = self.client.matrix()
        self.assertEqual(matrix["grants"]["ivanov"], {1, 3})
        self.assertEqual(matrix["grants"]["petrova"], set())
        self.assertEqual(len(matrix["subjects"]), 3)
        self.assertEqual(matrix["default_access"], "all")

    def test_set_teacher_grants_sends_sorted_unique(self):
        self.client.set_teacher_grants("petrova", [3, 1, 3])
        self.assertEqual(self.server.puts, [("petrova", [1, 3])])

    def test_set_default_access_validates(self):
        with self.assertRaises(ValueError):
            self.client.set_default_access("maybe")
        self.client.set_default_access("none")
        self.assertEqual(self.server.default_access, "none")

    def test_refresh_into_writes_snapshot(self):
        snap = self.client.refresh_into(self.repo, "ivanov")
        self.assertEqual(snap.subject_ids, frozenset({1, 3}))
        stored = self.repo.get_grants("ivanov")
        self.assertEqual(stored.subject_ids, frozenset({1, 3}))
        self.assertEqual(stored.scope_version, 3)

    def test_refresh_into_noop_for_guest_and_offline(self):
        self.assertIsNone(self.client.refresh_into(self.repo, None))
        offline = _client(self.server, base_url="")
        self.assertIsNone(offline.refresh_into(self.repo, "ivanov"))

    def test_refresh_into_propagates_network_error(self):
        # Проглотить нельзя: решение «работать по старому снимку» принимает
        # вызывающий, иначе отзыв прав спрятался бы за неудачным опросом.
        self.repo.save_grants("ivanov", [1])
        self.server.fail_next = True
        with self.assertRaises(GrantsError):
            self.client.refresh_into(self.repo, "ivanov")
        self.assertEqual(self.repo.get_grants("ivanov").subject_ids,
                         frozenset({1}))

    def test_can_manage_gating(self):
        self.assertFalse(_client(self.server, role="teacher").can_manage())
        self.assertFalse(_client(self.server, role="admin",
                                 base_url="").can_manage())
        self.assertTrue(_client(self.server, role="admin").can_manage())


# ---------- Scope-эпоха в синке ----------

class ScopedFakeServer(FakeServer):
    """FakeServer + скоуп: эпоха, resync и фильтрация выдачей."""

    def __init__(self):
        super().__init__()
        # Ненулевая с самого начала: свежий клиент не знает эпохи (шлёт 0) и
        # обязан получить пересборку на первом же pull. Ноль по обе стороны
        # маскировал бы это совпадением.
        self.scope_version = 1
        self.allowed: set[int] | None = None   # None — всё доступно
        self.resyncs = 0

    def revoke_to(self, allowed: set[int]) -> None:
        self.allowed = set(allowed)
        self.scope_version += 1

    def _pull(self, payload: dict) -> dict:
        resync = int(payload.get("scope_version") or 0) != self.scope_version
        if resync:
            self.resyncs += 1
            payload = dict(payload, cursors={})
        out = super()._pull(payload)
        out["scope_version"] = self.scope_version
        if resync:
            out["resync"] = True
        if self.allowed is not None:
            out["subjects"] = [s for s in out["subjects"]
                               if s["id"] in self.allowed]
            out["partitions"] = [p for p in out["partitions"]
                                 if p.get("subject_id") in self.allowed]
        return out


class SyncScopeTests(unittest.TestCase):
    def setUp(self):
        self.db_path = temp_path(suffix=".db")
        _make_local_db(self.db_path)
        self.repo = Repository(self.db_path)
        self.repo.ensure_owner_column()
        self.store = SyncStore(self.db_path)
        self.server = ScopedFakeServer()
        self.client = SyncClient(self.repo, self.store,
                                 transport=self.server.transport,
                                 user_id=None)
        self.addCleanup(lambda: os.path.exists(self.db_path)
                        and os.unlink(self.db_path))

    def _seed_server_subject(self, sid: int, name: str) -> None:
        self.server.seed("subject", sid, {"subject_name": name,
                                          "pra_subject": name,
                                          "owner_user_id": "author"})

    def _local_subject_ids(self) -> set[int]:
        with sqlite3.connect(self.db_path) as conn:
            return {r[0] for r in conn.execute("SELECT id FROM Subjects")}

    def test_revocation_removes_subject_locally(self):
        self._seed_server_subject(1, "Курс А")
        self._seed_server_subject(2, "Курс Б")
        self.client.sync()
        self.assertEqual(self._local_subject_ids(), {1, 2})

        # Отозвали доступ ко второму: диф-событий об этом нет — версия строки
        # не менялась. Убрать его может только пересборка скоупа.
        self.server.revoke_to({1})
        report = self.client.sync()
        self.assertEqual(self._local_subject_ids(), {1})
        self.assertEqual(report.scope_swept, 1)

    def test_grant_delivers_subject_below_cursor(self):
        self._seed_server_subject(1, "Курс А")
        self._seed_server_subject(2, "Курс Б")
        self.server.revoke_to({1})
        self.client.sync()
        self.assertEqual(self._local_subject_ids(), {1})

        # Выдали второй: его row_version старая, обычный курсор её прошёл.
        self.server.revoke_to({1, 2})
        self.client.sync()
        self.assertEqual(self._local_subject_ids(), {1, 2})

    def test_sweep_spares_builtin_subjects(self):
        # Встроенный (owner NULL) пересоздаётся сидами на каждом старте;
        # удалять его бессмысленно и опасно — уведёт разделы с правками.
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO Subjects (id, subject_name, pra_subject, "
                " owner_user_id) VALUES (7, 'Физика', 'Физика', NULL)")
        self.store.set_version("subject", 7, 5)
        self._seed_server_subject(1, "Курс А")
        self.server.revoke_to({1})
        self.client.sync()
        self.assertIn(7, self._local_subject_ids())

    def test_sweep_spares_unconfirmed_local_work(self):
        # Сущность без версии сервер никогда не принимал — это может быть
        # локальная работа, и права её стирать не должны.
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO Subjects (id, subject_name, pra_subject, "
                " owner_user_id) VALUES (55, 'Черновик', 'Черновик', 'me')")
        self._seed_server_subject(1, "Курс А")
        self.server.revoke_to({1})
        self.client.sync()
        self.assertIn(55, self._local_subject_ids())

    def test_sweep_does_not_enqueue_tombstones(self):
        # Ключевое: потеря доступа НЕ должна превращаться в удаление предмета
        # у всех. Sweep пишет напрямую, мимо sync_listener.
        self._seed_server_subject(1, "Курс А")
        self._seed_server_subject(2, "Курс Б")
        self.client.sync()
        self.server.revoke_to({1})
        self.client.sync()
        self.assertEqual(self.store.pending(), [])
        self.assertFalse(self.server.entities["subject"][2]["deleted"])

    def test_scope_version_saved_only_after_successful_sweep(self):
        self._seed_server_subject(1, "Курс А")
        self.client.sync()
        settled = self.store.get_scope_version(None)
        self.assertEqual(settled, self.server.scope_version)

        self.server.revoke_to(set())
        self.server.fail_next_pull = True
        self.client.sync()                      # обрыв посреди pull
        # Эпоха осталась прежней, sweep не выполнен — данные на месте.
        self.assertEqual(self.store.get_scope_version(None), settled)
        self.assertEqual(self._local_subject_ids(), {1})

        self.client.sync()                      # пересборка повторяется
        self.assertEqual(self.store.get_scope_version(None),
                         self.server.scope_version)
        self.assertEqual(self._local_subject_ids(), set())

    def test_scope_version_is_keyed_by_login(self):
        # На общей машине эпоха предыдущего пользователя не должна сойти за
        # свою — иначе следующий унаследовал бы чужую витрину.
        self._seed_server_subject(1, "Курс А")
        self.client.user_id = "ivanov"
        self.client.sync()
        self.assertEqual(self.store.get_scope_version("ivanov"),
                         self.server.scope_version)

        self.client.user_id = "petrova"
        self.assertEqual(self.store.get_scope_version("petrova"), 0)
        before = self.server.resyncs
        self.client.sync()
        self.assertGreater(self.server.resyncs, before)

    def test_no_resync_when_scope_unchanged(self):
        self._seed_server_subject(1, "Курс А")
        self.client.sync()
        before = self.server.resyncs
        self.client.sync()
        self.client.sync()
        self.assertEqual(self.server.resyncs, before)


# ---------- Вкладка матрицы в AdminWindow ----------

@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class GrantsTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, *, role="admin", login="root"):
        from types import SimpleNamespace
        from tests.test_admin_client import FakeAdminServer
        from core.admin import AdminClient
        from ui.windows.admin_window import AdminWindow

        self.gsrv = FakeGrantsServer()
        admin = AdminClient(base_url="http://x",
                            transport=FakeAdminServer().transport,
                            user_id_provider=lambda: login,
                            user_role_provider=lambda: role)
        grants = _client(self.gsrv, role=role, login=login)
        ctx = SimpleNamespace(admin_client=admin, grants_client=grants,
                              user_id_provider=lambda: login,
                              user_role_provider=lambda: role)
        w = AdminWindow(ctx)
        w._confirm = lambda _q: True
        # Порядок важен: cleanup'ы идут LIFO, поэтому дожидаемся тишины
        # ПЕРЕД удалением виджета. Сохранение матрицы чейнит воркеры (строка
        # → строка → перечитывание), и удаление родителя под живым QThread
        # роняет процесс — в одиночном прогоне просто везло со временем.
        self.addCleanup(w.deleteLater)
        self.addCleanup(self._settle, w)
        return w

    def _settle(self, w) -> None:
        """Дождаться, пока окно перестанет запускать фоновые вызовы."""
        def quiet() -> bool:
            return (w._worker is None and not w._grants_save_queue
                    and not w._refresh_queue)

        # Устойчивая тишина, а не мгновенный снимок: между двумя звеньями
        # цепочки _worker на миг пуст.
        stable = 0
        deadline = time.monotonic() + 10.0
        while stable < 5:
            self.app.processEvents()
            stable = stable + 1 if quiet() else 0
            if time.monotonic() > deadline:
                raise AssertionError("окно не успокоилось")
            time.sleep(0.005)

    def _spin(self, predicate, timeout=6.0):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "условие не наступило")
            self.app.processEvents()
            time.sleep(0.01)

    def _row_for(self, w, login):
        for r in range(w.grants_table.rowCount()):
            item = w.grants_table.item(r, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == login:
                return r
        return None

    def test_tab_present(self):
        w = self._window()
        titles = [w.tabs.tabText(i) for i in range(w.tabs.count())]
        self.assertIn("Предметы преподавателям", titles)

    def test_matrix_renders_current_grants(self):
        w = self._window()
        self._spin(lambda: w.grants_table.rowCount() == 2)
        row = self._row_for(w, "ivanov")
        states = [w.grants_table.item(row, c).checkState()
                  for c in range(1, 4)]
        self.assertEqual(states, [Qt.CheckState.Checked,
                                  Qt.CheckState.Unchecked,
                                  Qt.CheckState.Checked])

    def test_toggle_marks_dirty_and_apply_saves_row(self):
        w = self._window()
        self._spin(lambda: w.grants_table.rowCount() == 2)
        self.assertFalse(w.grants_apply_btn.isEnabled())

        row = self._row_for(w, "petrova")
        w.grants_table.item(row, 2).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(w.grants_apply_btn.isEnabled())
        self.assertIn("1", w.grants_dirty_label.text())

        w._on_apply_grants()
        self._spin(lambda: self.gsrv.puts and w._worker is None)
        self.assertEqual(self.gsrv.puts[0], ("petrova", [2]))
        self._spin(lambda: not w.grants_apply_btn.isEnabled())

    def test_apply_saves_every_changed_row(self):
        # Строки уходят последовательно: _start_call держит один вызов в
        # полёте, параллельные молча пропали бы.
        w = self._window()
        self._spin(lambda: w.grants_table.rowCount() == 2)
        w.grants_table.item(self._row_for(w, "ivanov"), 2).setCheckState(
            Qt.CheckState.Checked)
        w.grants_table.item(self._row_for(w, "petrova"), 1).setCheckState(
            Qt.CheckState.Checked)
        w._on_apply_grants()
        self._spin(lambda: len(self.gsrv.puts) == 2 and w._worker is None)
        self.assertEqual(dict(self.gsrv.puts),
                         {"ivanov": [1, 2, 3], "petrova": [1]})

    def test_revert_restores_loaded_state(self):
        w = self._window()
        self._spin(lambda: w.grants_table.rowCount() == 2)
        row = self._row_for(w, "petrova")
        w.grants_table.item(row, 1).setCheckState(Qt.CheckState.Checked)
        self.assertTrue(w.grants_apply_btn.isEnabled())

        w._on_revert_grants()
        self.assertFalse(w.grants_apply_btn.isEnabled())
        row = self._row_for(w, "petrova")
        self.assertEqual(w.grants_table.item(row, 1).checkState(),
                         Qt.CheckState.Unchecked)
        self.assertEqual(self.gsrv.puts, [])

    def test_filter_narrows_rows(self):
        w = self._window()
        self._spin(lambda: w.grants_table.rowCount() == 2)
        w.grants_filter_edit.setText("петр")
        self.assertEqual(w.grants_table.rowCount(), 1)
        self.assertIsNotNone(self._row_for(w, "petrova"))
        w.grants_filter_edit.setText("")
        self.assertEqual(w.grants_table.rowCount(), 2)

    def test_filter_keeps_unsaved_draft(self):
        w = self._window()
        self._spin(lambda: w.grants_table.rowCount() == 2)
        w.grants_table.item(self._row_for(w, "petrova"), 1).setCheckState(
            Qt.CheckState.Checked)
        w.grants_filter_edit.setText("петр")
        row = self._row_for(w, "petrova")
        self.assertEqual(w.grants_table.item(row, 1).checkState(),
                         Qt.CheckState.Checked)
        self.assertTrue(w.grants_apply_btn.isEnabled())

    def test_error_stops_save_queue(self):
        w = self._window()
        self._spin(lambda: w.grants_table.rowCount() == 2)
        w.grants_table.item(self._row_for(w, "ivanov"), 2).setCheckState(
            Qt.CheckState.Checked)
        w.grants_table.item(self._row_for(w, "petrova"), 1).setCheckState(
            Qt.CheckState.Checked)
        self.gsrv.fail_next = True
        w._on_apply_grants()
        self._spin(lambda: not w.grants_error.isHidden())
        self.assertEqual(w._grants_save_queue, [])
        self.assertIn("503", w.grants_error.text())


if __name__ == "__main__":
    unittest.main()
