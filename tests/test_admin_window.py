"""
AdminWindow (offscreen Qt): доступность (заглушка без сервера/не-admin),
загрузка пользователей и смена роли с подтверждением + откат по guardrail,
CRUD групп (создание, состав, преподаватели) через фоновый _CallWorker.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_admin_window
"""

from __future__ import annotations
import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.admin import AdminClient
from tests.test_admin_client import FakeAdminServer

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class AdminWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self, *, role="admin", login="root", base_url="http://x",
                server=None):
        from types import SimpleNamespace
        from ui.windows.admin_window import AdminWindow

        srv = server or FakeAdminServer()
        client = AdminClient(base_url=base_url, transport=srv.transport,
                             user_id_provider=lambda: login,
                             user_role_provider=lambda: role)
        ctx = SimpleNamespace(admin_client=client,
                              user_id_provider=lambda: login,
                              user_role_provider=lambda: role)
        w = AdminWindow(ctx)
        w._confirm = lambda _q: True   # без модального диалога
        self.addCleanup(w.deleteLater)
        self._srv = srv
        return w

    def _spin(self, predicate, timeout=6.0):
        deadline = time.monotonic() + timeout
        while not predicate():
            self.assertLess(time.monotonic(), deadline, "условие не наступило")
            self.app.processEvents()
            time.sleep(0.01)

    def _settle(self, w):
        self._spin(lambda: w._worker is None)

    # ---------- доступность ----------

    def test_disabled_without_server(self):
        # Окно не показано (offscreen-тест) → isVisible() ложна у всех; логику
        # доступности проверяем через явный isHidden() (setVisible-состояние).
        w = self._window(base_url="")
        self.assertTrue(w.tabs.isHidden())
        self.assertFalse(w.disabled_label.isHidden())
        self.assertIn("адрес сервера", w.disabled_label.text())

    def test_disabled_for_non_admin(self):
        w = self._window(role="teacher")
        self.assertTrue(w.tabs.isHidden())
        self.assertFalse(w.disabled_label.isHidden())
        self.assertIn("администратор", w.disabled_label.text())

    # ---------- пользователи ----------

    def test_users_table_populates(self):
        w = self._window()
        self._settle(w)
        self._spin(lambda: w.users_table.rowCount() == 2)
        logins = {w.users_table.item(r, 0).data(Qt.ItemDataRole.UserRole)
                  for r in range(w.users_table.rowCount())}
        self.assertEqual(logins, {"root", "alla"})

    def _combo_for(self, w, login):
        for r in range(w.users_table.rowCount()):
            if w.users_table.item(r, 0).data(Qt.ItemDataRole.UserRole) == login:
                return w.users_table.cellWidget(r, 2)
        return None

    def test_viewer_own_role_locked(self):
        w = self._window(login="root")
        self._settle(w)
        self._spin(lambda: w.users_table.rowCount() == 2)
        self.assertFalse(self._combo_for(w, "root").isEnabled())
        self.assertTrue(self._combo_for(w, "alla").isEnabled())

    def test_change_role_confirmed_persists(self):
        w = self._window()
        self._settle(w)
        self._spin(lambda: w.users_table.rowCount() == 2)
        combo = self._combo_for(w, "alla")
        combo.setCurrentIndex(combo.findData("admin"))   # → confirm → server
        self._spin(lambda: self._srv.users["alla"]["role"] == "admin")
        self._settle(w)

    def test_change_role_declined_reverts(self):
        w = self._window()
        w._confirm = lambda _q: False
        self._settle(w)
        self._spin(lambda: w.users_table.rowCount() == 2)
        combo = self._combo_for(w, "alla")
        combo.setCurrentIndex(combo.findData("admin"))
        self._settle(w)
        # Сервер не тронут; таблица перечитана — combo снова «teacher».
        self.assertEqual(self._srv.users["alla"]["role"], "teacher")
        self._spin(lambda: self._combo_for(w, "alla").currentData() == "teacher")

    def test_change_role_guardrail_shows_error(self):
        # Понижение root (в фейке — как «нельзя изменить свою роль») → 400.
        # Здесь смотрим на alla→root недоступно; используем прямой путь:
        srv = FakeAdminServer()
        w = self._window(login="someone_else", server=srv)
        self._settle(w)
        self._spin(lambda: w.users_table.rowCount() == 2)
        combo = self._combo_for(w, "root")   # root редактируем (не мы)
        self.assertIsNotNone(combo)
        combo.setCurrentIndex(combo.findData("teacher"))
        self._spin(lambda: not w.users_error.isHidden())
        self.assertIn("400", w.users_error.text())

    # ---------- группы ----------

    def test_create_group_and_manage_members(self):
        w = self._window()
        self._settle(w)
        w.group_name_edit.setText("Поток А")
        w.group_create_btn.click()
        self._spin(lambda: w.groups_list.count() == 1)
        self._settle(w)
        # Выбрана созданная группа; добавляем участника и преподавателя.
        w.member_login_edit.setText("alla")
        w.member_add_btn.click()
        self._spin(lambda: w.members_list.count() == 1)
        self._settle(w)
        w.teacher_login_edit.setText("alla")
        w.teacher_add_btn.click()
        self._spin(lambda: w.teachers_list.count() == 1)
        self._settle(w)
        gid = w._current_group_id()
        self.assertEqual(self._srv.groups[gid]["members"], ["alla"])
        self.assertEqual(self._srv.groups[gid]["teachers"], ["alla"])

    def test_matrix_tab_built(self):
        w = self._window()
        # Вкладка матрицы — третья; таблица заполнена статикой без вызовов.
        matrix = w.tabs.widget(2)
        self.assertIsNotNone(matrix)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class WorkerOutlivesTheWindowTests(unittest.TestCase):
    """
    Окно закрыли, а запрос ещё в полёте.

    Так падало по-настоящему, и не только в тестах: воркер создавался с
    окном в родителях, удаление окна удаляло его ВМЕСТЕ С РАБОТАЮЩИМ
    ПОТОКОМ, а это неопределённое поведение — на практике segfault без
    единого сообщения. В программе это выход из неё (или закрытие окна)
    с незавершённым запросом к серверу; в наборе — восьмой тест подряд,
    когда `processEvents` добирался до отложенного удаления предыдущего
    окна.

    Тест намеренно не проверяет «результат пришёл»: проверяется, что
    ПРОЦЕСС ЖИВ. Падение здесь выглядит не как провал теста, а как
    прерванный прогон — потому и заметили его так поздно.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _window(self):
        from types import SimpleNamespace
        from ui.windows.admin_window import AdminWindow
        srv = FakeAdminServer()
        client = AdminClient(base_url="http://x", transport=srv.transport,
                             user_id_provider=lambda: "root",
                             user_role_provider=lambda: "admin")
        ctx = SimpleNamespace(admin_client=client,
                              user_id_provider=lambda: "root",
                              user_role_provider=lambda: "admin")
        return AdminWindow(ctx)

    def test_destroying_a_window_mid_call_does_not_crash(self):
        # Нарочно без обращения к внутренностям починки: тест обязан
        # уметь упасть и на СТАРОМ коде, иначе он проверяет не падение, а
        # реализацию. Проверено — на старом коде он его и роняет.
        for _ in range(6):
            w = self._window()
            w.refresh()               # запрос в полёте
            w.deleteLater()           # и тут же закрыли
            self.app.processEvents()  # ← здесь и сносило живой поток

        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

        # Дошли сюда — значит процесс жив. Другого утверждения тут и не
        # нужно: падение выглядит не как провал теста, а как прерванный
        # прогон.
        self.assertTrue(True)

    def test_a_dead_window_gets_no_callback(self):
        """
        Ответ пришёл, а окна уже нет — колбэк обязан промолчать. Не
        ошибка: пользователь вправе закрыть окно, не дожидаясь сервера.

        Этот и следующий тесты обращаются к внутренностям починки, и
        потому на старом коде не запускаются вовсе. Падение ловит
        предыдущий.
        """
        w = self._window()
        w.refresh()
        w._alive.mark_dead()          # как если бы окно уничтожили
        deadline = time.monotonic() + 6.0
        while w._worker is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        # Колбэк не выполнился, поэтому и флаг занятости не снят — это
        # ожидаемо: окна нет, снимать его некому и незачем.
        self.assertIsNotNone(w._worker)
        w.deleteLater()

    def test_the_worker_has_no_widget_parent(self):
        """
        Корень падения: у работающего потока не должно быть владельца,
        который умрёт раньше него.
        """
        w = self._window()
        w.refresh()
        self.assertIsNotNone(w._worker)
        self.assertIsNone(w._worker.parent())
        w.deleteLater()
