"""
UpdatesWindow — окно «Обновления»: версия приложения и пакеты узлов графа.

Витрина для `core/updates`: библиотека проверяет подписи и раскладывает
файлы, здесь у неё появляются кнопки. Окно немодальное, живёт синглтоном у
главного окна — как SyncWindow.

## Что окно обязано показывать, а не прятать

**Отказ проверки — событие, а не «обновлений нет».** `Updater.check()`
возвращает отказ отдельным полем `rejected`, и показать его надо словами:
«подпись не соответствует доверенному ключу» и «сервер предлагает откат» —
это признаки того, что с каналом что-то не так, а вовсе не тишина. Свести
их к «у вас последняя версия» значило бы выбросить ровно ту информацию,
ради которой писалась вся проверка.

**Сборка без ключа.** Если в сборку не впечатан набор ключей
(`core/updates/bundled.py`), клиент отвергает всё — и обновления, и пакеты.
Это не поломка сети, и выглядеть как поломка сети оно не должно: окно
говорит прямо, что проверять нечем.

**Подготовлено ≠ установлено.** Переключение дерева приложения делает
запускающий (`scripts/update_launcher.py`) до импорта кода — подменять
каталог, из которого уже работает процесс, нельзя. Поэтому кнопка
называется «Скачать и подготовить», а не «Обновить», и рядом написано,
когда это применится. Соврать здесь легко и очень неприятно: пользователь
перезапустится, увидит прежнюю версию и решит, что обновление не работает.

## Потоки

Сеть и распаковка блокируют, поэтому идут в QThread (`_Worker`), а виджеты
трогает только UI-поток — результат приезжает сигналом. Тот же приём, что
у SyncWindow.

## Роли

Не гейтится ничем. Обновление безопасности должно доезжать до всех, а
пакеты узлов нужны, чтобы граф вообще открылся, — запирать их за ролью
значило бы ломать работу тому, кто просто решает задачи.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QTabWidget, QVBoxLayout, QWidget,
)

from ui.app_context import AppContext
from ui.qt_worker import run_detached

# Уровень → значение свойства class для QSS (см. ui/theme.py).
_MUTED = "muted"


class _Worker(QThread):
    """
    Один фоновый вызов. Общий на все действия окна намеренно: каждое из них
    — «сходить в сеть и вернуть словарь», и пять почти одинаковых классов
    отличались бы только именем.

    Исключение НЕ проглатывается и не превращается в пустой результат: для
    этого окна «не смогли проверить» и «проверили, всё хорошо» — разные
    ответы, и путать их нельзя.
    """

    done = pyqtSignal(object, object)          # (результат, текст ошибки)

    def __init__(self, fn: Callable[[], object]):
        # Родителя нет и быть не может: владелец-виджет, умерев раньше
        # потока, снёс бы его на ходу (см. ui/qt_worker.py).
        super().__init__()
        self._fn = fn

    def run(self) -> None:                     # noqa: D102 — контракт QThread
        try:
            self.done.emit(self._fn(), None)
        except Exception as exc:               # noqa: BLE001 — показываем как есть
            self.done.emit(None, str(exc))


class UpdatesWindow(QWidget):
    """Окно «Обновления»: вкладки «Приложение» и «Пакеты узлов»."""

    def __init__(self, context: AppContext, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.ctx = context
        self.setWindowTitle("Обновления")
        self.resize(640, 520)

        self._checked: Optional[dict] = None   # последний ответ check()
        self._worker: Optional[_Worker] = None
        # Итог последнего действия с пакетом. Живёт до показа, потому что
        # после установки каталог перезапрашивается — и без этого «пакет
        # установлен» мигало бы и сменялось на «пакетов в каталоге: 1»,
        # то есть единственное, что человек хотел прочитать, исчезало бы.
        self._pkg_notice: Optional[str] = None

        root = QVBoxLayout(self)
        tabs = QTabWidget(self)
        tabs.addTab(self._app_tab(), "Приложение")
        tabs.addTab(self._packages_tab(), "Пакеты узлов")
        root.addWidget(tabs, stretch=1)
        self.refresh()

    # ---------- доступ к подсистеме ----------

    @property
    def updater(self):
        return self.ctx.updater

    @property
    def installer(self):
        return self.ctx.package_installer

    def _ready(self) -> Optional[str]:
        """Причина, по которой действовать нельзя, либо None."""
        if self.updater is None or self.installer is None:
            return ("Механизм обновлений не собран в этой сборке.")
        if not self.updater.has_server():
            return ("Адрес сервера не задан — укажите его в Настройках.")
        if not self.updater.keyring.configured:
            return ("В сборку не впечатан ключ выпуска: проверить подпись "
                    "нечем, поэтому не будет принято ни обновление, ни "
                    "пакет. Это не сбой связи — так собрано приложение.")
        return None

    # ---------- вкладка «Приложение» ----------

    def _app_tab(self) -> QWidget:
        w = QWidget(self)
        box = QVBoxLayout(w)

        self.version_label = QLabel("", w)
        box.addWidget(self.version_label)

        self.trust_label = QLabel("", w)
        self.trust_label.setWordWrap(True)
        box.addWidget(self.trust_label)

        row = QHBoxLayout()
        self.check_btn = QPushButton("Проверить обновление", w)
        self.check_btn.clicked.connect(self._on_check)
        row.addWidget(self.check_btn)
        self.stage_btn = QPushButton("Скачать и подготовить", w)
        self.stage_btn.setEnabled(False)
        self.stage_btn.clicked.connect(self._on_stage)
        row.addWidget(self.stage_btn)
        row.addStretch(1)
        box.addLayout(row)

        self.app_status = QLabel("", w)
        self.app_status.setWordWrap(True)
        self.app_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(self.app_status)

        self.pending_label = QLabel("", w)
        self.pending_label.setWordWrap(True)
        box.addWidget(self.pending_label)

        box.addStretch(1)
        return w

    # ---------- вкладка «Пакеты узлов» ----------

    def _packages_tab(self) -> QWidget:
        w = QWidget(self)
        box = QVBoxLayout(w)

        hint = QLabel(
            "Дополнительные типы узлов графа. Приезжают только с сервера и "
            "только подписанными; установленное подключается при следующем "
            "запуске приложения.", w)
        hint.setProperty("class", _MUTED)
        hint.setWordWrap(True)
        box.addWidget(hint)

        row = QHBoxLayout()
        self.catalog_btn = QPushButton("Обновить список", w)
        self.catalog_btn.clicked.connect(self._on_catalog)
        row.addWidget(self.catalog_btn)
        row.addStretch(1)
        box.addLayout(row)

        self.pkg_status = QLabel("", w)
        self.pkg_status.setWordWrap(True)
        box.addWidget(self.pkg_status)

        area = QScrollArea(w)
        area.setWidgetResizable(True)
        self.pkg_host = QWidget(area)
        self.pkg_layout = QVBoxLayout(self.pkg_host)
        self.pkg_layout.addStretch(1)
        area.setWidget(self.pkg_host)
        box.addWidget(area, stretch=1)
        return w

    # ---------- обновление витрины ----------

    def refresh(self) -> None:
        """Пересчитать всё, что читается локально (без сети)."""
        if self.updater is None:
            self.version_label.setText("Механизм обновлений не собран.")
            self.trust_label.setText("")
            self._set_enabled(False)
            return

        state = self.updater.state
        version = state.app_version() or "—"
        self.version_label.setText(
            f"Установлено: {version} (выпуск {state.app_sequence()})")

        ring = self.updater.keyring
        if ring.configured:
            self.trust_label.setProperty("class", _MUTED)
            self.trust_label.setText(
                f"Ключи выпуска: набор {ring.sequence()}, "
                f"активные отпечатки — {', '.join(ring.fingerprints())}")
        else:
            self.trust_label.setProperty("class", "")
            self.trust_label.setText(
                "⚠ В сборку не впечатан ключ выпуска. Проверить подпись "
                "нечем, поэтому приложение отвергнет и обновление, и любой "
                "пакет узлов. Это свойство сборки, а не сбой связи.")
        for dropped in ring.dropped:
            self.trust_label.setText(
                self.trust_label.text() + f"\n⚠ {dropped}")

        pending = state.pending()
        if pending:
            self.pending_label.setText(
                f"Подготовлено: {pending['version']} "
                f"(выпуск {pending['sequence']}). Применится при следующем "
                f"запуске — переключение делает запускающий, до загрузки "
                f"кода приложения.")
        else:
            self.pending_label.setText("")

        blocked = self._ready()
        self._set_enabled(blocked is None)
        if blocked is not None:
            self.app_status.setText(blocked)
            self.pkg_status.setText(blocked)

    def _set_enabled(self, enabled: bool) -> None:
        for btn in (self.check_btn, self.catalog_btn):
            btn.setEnabled(enabled)
        if not enabled:
            self.stage_btn.setEnabled(False)

    # ---------- действия: приложение ----------

    def _on_check(self) -> None:
        blocked = self._ready()
        if blocked is not None:
            self.app_status.setText(blocked)
            return
        self._checked = None
        self.stage_btn.setEnabled(False)
        self.app_status.setText("Проверка…")
        updater = self.updater

        def work() -> dict:
            # Ротацию догоняем ПЕРЕД проверкой: релиз может быть подписан уже
            # новым ключом, и без свежего набора он выглядел бы подделкой.
            # Неудача самой ротации не должна прятать причину — она уедет
            # наверх как ошибка целиком.
            updater.refresh_keys()
            return updater.check()

        self._run(work, self._on_checked, self.check_btn)

    def _on_checked(self, result, error) -> None:
        self.refresh()
        if error is not None:
            self.app_status.setText(f"Не удалось проверить: {error}")
            return
        checked = result or {}
        rejected = checked.get("rejected")
        if rejected:
            # Отказ показываем словами: это не «обновлений нет», а признак
            # того, что с каналом что-то не так.
            self.app_status.setText(f"⚠ Обновление отклонено. {rejected}")
            return
        if not checked.get("update_available"):
            self.app_status.setText("Установлена последняя версия.")
            return

        manifest = checked.get("manifest") or {}
        lines = [f"Доступна версия {manifest.get('version')} "
                 f"(выпуск {manifest.get('sequence')})."]
        if checked.get("mandatory"):
            lines.append("Сервер отмечает обновление как обязательное — "
                         "ваша версия ниже минимально поддерживаемой.")
        if checked.get("notes"):
            lines.append(str(checked["notes"]))
        lines.append("Подпись проверена ключом "
                     f"{checked.get('signing_key_id') or '—'}.")
        self.app_status.setText("\n".join(lines))
        self._checked = checked
        self.stage_btn.setEnabled(True)

    def _on_stage(self) -> None:
        if self._checked is None:
            return
        checked = self._checked
        updater = self.updater
        self.app_status.setText("Скачивание и проверка…")
        self._run(lambda: updater.stage(checked), self._on_staged,
                  self.stage_btn)

    def _on_staged(self, result, error) -> None:
        self.refresh()
        if error is not None:
            self.app_status.setText(f"Не удалось подготовить: {error}")
            return
        pending = result or {}
        self.app_status.setText(
            f"Версия {pending.get('version')} скачана, подпись и хеш "
            f"сошлись, распаковано рядом. Установится при следующем запуске.")
        self._checked = None
        self.stage_btn.setEnabled(False)

    # ---------- действия: пакеты ----------

    def _on_catalog(self) -> None:
        blocked = self._ready()
        if blocked is not None:
            self.pkg_status.setText(blocked)
            return
        if not self._pkg_notice:
            self.pkg_status.setText("Загрузка каталога…")
        installer = self.installer
        self._run(installer.catalog, self._on_catalog_ready, self.catalog_btn)

    def _on_catalog_ready(self, result, error) -> None:
        if error is not None:
            self.pkg_status.setText(f"Каталог недоступен: {error}")
            return
        packages = (result or {}).get("packages") or []
        if self._pkg_notice:
            self.pkg_status.setText(self._pkg_notice)
            self._pkg_notice = None
        else:
            self.pkg_status.setText(
                f"Пакетов в каталоге: {len(packages)}." if packages
                else "На сервере пока нет ни одного пакета узлов.")
        self._fill_packages(packages)

    def _fill_packages(self, packages: list) -> None:
        while self.pkg_layout.count() > 1:
            item = self.pkg_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for entry in packages:
            self.pkg_layout.insertWidget(
                self.pkg_layout.count() - 1, self._package_card(entry))

    def _package_card(self, entry: dict) -> QWidget:
        card = QFrame(self.pkg_host)
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Maximum)
        box = QVBoxLayout(card)

        name = str(entry.get("name") or "")
        title = QLabel(f"<b>{name}</b> {entry.get('version') or ''}", card)
        box.addWidget(title)

        if entry.get("summary"):
            summary = QLabel(str(entry["summary"]), card)
            summary.setWordWrap(True)
            summary.setProperty("class", _MUTED)
            box.addWidget(summary)

        types = ", ".join(str(t) for t in (entry.get("node_types") or []))
        if types:
            types_label = QLabel(f"Узлы: {types}", card)
            types_label.setWordWrap(True)
            types_label.setProperty("class", _MUTED)
            box.addWidget(types_label)

        row = QHBoxLayout()
        if not entry.get("supported", True):
            # Пакет под другой контракт узлов. Не «немного не подойдёт» — он
            # упал бы посреди генерации, поэтому кнопку не показываем вовсе.
            warn = QLabel(
                f"Собран под api_version {entry.get('api_version')} — эта "
                f"версия приложения его не подключит.", card)
            warn.setWordWrap(True)
            row.addWidget(warn, stretch=1)
        else:
            local = entry.get("local_version")
            if entry.get("local_installed"):
                state = QLabel(f"Установлен: {local}", card)
                state.setProperty("class", _MUTED)
                row.addWidget(state, stretch=1)
                if str(local) != str(entry.get("version")):
                    upgrade = QPushButton("Обновить", card)
                    upgrade.clicked.connect(
                        lambda _=False, n=name: self._on_install(n))
                    row.addWidget(upgrade)
                remove = QPushButton("Удалить", card)
                remove.clicked.connect(
                    lambda _=False, n=name: self._on_uninstall(n))
                row.addWidget(remove)
            else:
                row.addStretch(1)
                install = QPushButton("Установить", card)
                install.clicked.connect(
                    lambda _=False, n=name: self._on_install(n))
                row.addWidget(install)
        box.addLayout(row)
        return card

    def _on_install(self, name: str) -> None:
        installer = self.installer
        self.pkg_status.setText(f"Установка «{name}»…")
        self._run(lambda: installer.install(name), self._on_installed,
                  self.catalog_btn)

    def _on_installed(self, result, error) -> None:
        if error is not None:
            self.pkg_status.setText(f"Не установлен: {error}")
            return
        info = result or {}
        self._pkg_notice = (
            f"Пакет «{info.get('name')}» {info.get('version')} установлен: "
            f"подпись проверена, узлы подключатся при следующем запуске.")
        self.pkg_status.setText(self._pkg_notice)
        self._on_catalog()

    def _on_uninstall(self, name: str) -> None:
        installer = self.installer
        self._run(lambda: installer.uninstall(name), self._on_uninstalled,
                  self.catalog_btn)

    def _on_uninstalled(self, result, error) -> None:
        if error is not None:
            self.pkg_status.setText(f"Не удалось удалить: {error}")
            return
        self._pkg_notice = (
            "Пакет удалён. Графы, использующие его узлы, перестанут "
            "открываться после перезапуска.")
        self.pkg_status.setText(self._pkg_notice)
        self._on_catalog()

    # ---------- фон ----------

    def _run(self, fn: Callable[[], object],
             slot: Callable[[object, object], None],
             button: QPushButton) -> None:
        """
        Запустить в фоне, погасив кнопку на время. Ссылку на воркер держим
        в атрибуте: без неё Qt соберёт QThread сборщиком мусора посреди
        работы, и падение будет выглядеть случайным.
        """
        button.setEnabled(False)
        # Без родителя и через run_detached: поток, принадлежащий окну,
        # умирает вместе с ним прямо на ходу (см. ui/qt_worker.py).
        worker = _Worker(fn)
        self._worker = worker

        def finish(result, error) -> None:
            self._worker = None
            button.setEnabled(self._ready() is None)
            slot(result, error)

        run_detached(self, worker, finish)
