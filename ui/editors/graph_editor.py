"""
GraphEditor — визуальный редактор раздела-графа (constracted=4).

Фаза 2: расстановка узлов мышью на холсте (QGraphicsScene). Слева — палитра
типов узлов (двойной клик добавляет узел), в центре — холст с узлами и
проводами, справа — инспектор параметров выбранного узла. Вкладка «JSON» даёт
текстовый доступ к тому же графу (запасной путь / отладка).

Канвас ничего не вычисляет: он редактирует core.graph.GraphDocument и
сериализует его в тот же GraphSpec, что исполняет движок. Проверка и
предпросмотр переиспользуют GraphExecutor / GraphConstructorGenerator.

По «Сохранить» пишет (name, 4, graph_dict) в Partitions через общий контракт
PartitionEditor.
"""

from __future__ import annotations
import json

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QPlainTextEdit, QTabWidget, QWidget, QSplitter, QMessageBox,
)

from core.graph import (
    GraphDocument, GraphError, GraphExecutor, GraphSpec, GraphValidationError,
)

from .base import PartitionEditor
from .graph_canvas import GraphScene, GraphCanvasView, NodePalette
from .graph_canvas.history import GraphHistory
from .graph_canvas.inspector import ParamInspector


def _default_graph_dict() -> dict:
    from exercises.graph.generators import EXAMPLE_GRAPH
    return EXAMPLE_GRAPH


class GraphEditor(PartitionEditor):
    """Визуальный редактор графа (constracted=4)."""

    CONSTRACTED = 4

    def __init__(self, repository, subject_id, partition_id=None, parent=None):
        super().__init__(repository, subject_id, partition_id, parent)
        self.doc = GraphDocument()
        # Стек навигации по вложенным телам циклов:
        # каждый уровень — (родительский GraphDocument, node_id узла repeat, ключ параметра).
        self._nav_stack: list[tuple] = []
        # История undo/redo и буфер обмена (на уровне текущего холста).
        self._history = GraphHistory()
        self._clipboard: dict | None = None
        self._restoring = False        # подавляем запись в историю при undo/redo
        self._build_ui()
        if self.is_edit_mode:
            self.load_existing()
        else:
            self._load_doc(GraphDocument.from_spec_dict(_default_graph_dict()))

    # ---- UI ----

    def _build_ui(self) -> None:
        self.setMinimumSize(1100, 760)
        self.setWindowTitle(
            "Редактирование графа" if self.is_edit_mode else "Создание графа"
        )

        root = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Название раздела:"))
        self.name_edit = QLineEdit(self)
        row.addWidget(self.name_edit, stretch=1)
        root.addLayout(row)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_canvas_tab(), "Холст")
        self.tabs.addTab(self._build_json_tab(), "JSON")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, stretch=1)

        # Полоса: проверить / предпросмотр + результат
        tools = QHBoxLayout()
        check_btn = QPushButton("Проверить", self)
        preview_btn = QPushButton("Предпросмотр", self)
        check_btn.clicked.connect(self._on_check)
        preview_btn.clicked.connect(self._on_preview)
        tools.addWidget(check_btn)
        tools.addWidget(preview_btn)
        tools.addStretch()
        root.addLayout(tools)

        self.preview = QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(140)
        root.addWidget(self.preview)

        # Save / Cancel
        btns = QHBoxLayout()
        save_btn = QPushButton("Сохранить", self)
        cancel_btn = QPushButton("Отмена", self)
        save_btn.clicked.connect(self.save)
        cancel_btn.clicked.connect(self._on_cancel)
        btns.addStretch()
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        root.addLayout(btns)

    def _build_canvas_tab(self) -> QWidget:
        wrap = QWidget(self)
        layout = QHBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal, wrap)

        self.palette = NodePalette(self.doc.registry, splitter)
        self.palette.add_requested.connect(self._on_palette_add)

        self.scene = GraphScene(self.doc, splitter)
        self.scene.selection_node.connect(self._on_node_selected)
        self.scene.changed_doc.connect(self._mark_canvas_dirty)
        self.view = GraphCanvasView(self.scene, splitter)
        self.view.copy_requested.connect(self.copy_selection)
        self.view.paste_requested.connect(self.paste_clipboard)
        self.view.undo_requested.connect(self.undo)
        self.view.redo_requested.connect(self.redo)
        self.view.moved_nodes.connect(self.snapshot_after_move)

        self.inspector = ParamInspector(self.doc, splitter)
        self.inspector.ports_changed.connect(self.scene.refresh_node)
        self.inspector.params_changed.connect(self._on_param_changed)
        self.inspector.open_subgraph.connect(self._enter_subgraph)

        splitter.addWidget(self.palette)
        splitter.addWidget(self.view)
        splitter.addWidget(self.inspector)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 640, 240])

        # Хлебные крошки + «назад» для навигации по вложенным телам циклов.
        crumbs = QHBoxLayout()
        self.back_btn = QPushButton("← Назад", wrap)
        self.back_btn.clicked.connect(self._exit_subgraph)
        self.back_btn.setVisible(False)
        self.breadcrumb = QLabel("Главный граф", wrap)
        self.breadcrumb.setStyleSheet("color: #bbb;")
        crumbs.addWidget(self.back_btn)
        crumbs.addWidget(self.breadcrumb)
        crumbs.addStretch()

        hint = QLabel(
            "Двойной клик в палитре — добавить узел. Тяните от порта к порту — "
            "провод (только совместимые типы). Del — удалить. "
            "Ctrl+C/V — копировать/вставить, Ctrl+Z — отменить, "
            "Ctrl+Shift+Z — повторить.",
            wrap,
        )
        hint.setStyleSheet("color: #888;")
        outer = QVBoxLayout()
        outer.addLayout(crumbs)
        outer.addWidget(splitter, stretch=1)
        outer.addWidget(hint)
        container = QWidget(self)
        container.setLayout(outer)
        return container

    def _build_json_tab(self) -> QWidget:
        wrap = QWidget(self)
        layout = QVBoxLayout(wrap)
        layout.addWidget(QLabel("Описание графа (JSON: nodes / edges / meta):"))
        self.json_edit = QPlainTextEdit(wrap)
        self.json_edit.setStyleSheet("font-family: Consolas, monospace;")
        layout.addWidget(self.json_edit, stretch=1)
        apply_btn = QPushButton("Применить JSON к холсту", wrap)
        apply_btn.clicked.connect(self._apply_json_to_canvas)
        layout.addWidget(apply_btn)
        return wrap

    def _on_cancel(self) -> None:
        self.cancelled.emit()
        self.close()

    # ---- Загрузка графа в холст ----

    def _load_doc(self, doc: GraphDocument) -> None:
        self.doc = doc
        self.scene.doc = doc
        self.scene.registry = doc.registry
        self.inspector.doc = doc
        self.scene.rebuild()
        self._sync_json_from_doc()
        # Новый граф (или смена уровня подграфа) — история начинается заново.
        if not self._restoring:
            self._history.reset(self.doc.to_spec_dict())

    # ---- Палитра / выбор / параметры ----

    def _on_palette_add(self, type_id: str) -> None:
        # ставим в видимый центр сцены
        center = self.view.mapToScene(self.view.viewport().rect().center())
        try:
            self.scene.add_node(type_id, QPointF(center.x(), center.y()))
        except GraphError as e:
            QMessageBox.warning(self, "Не удалось добавить узел", str(e))

    def _on_node_selected(self, node_id) -> None:
        self.inspector.show_node(node_id)

    def _on_param_changed(self, node_id: str) -> None:
        item = self.scene.node_items.get(node_id)
        if item is not None:
            item.update()
        self._mark_canvas_dirty()

    def _mark_canvas_dirty(self) -> None:
        self._sync_json_from_doc()
        if not self._restoring:
            self._history.push(self.doc.to_spec_dict())

    # ---- Undo / redo / буфер обмена ----

    def _restore_snapshot(self, snap: dict) -> None:
        """Загрузить снимок в холст, не трогая историю (флаг _restoring)."""
        self._restoring = True
        try:
            doc = GraphDocument.from_spec_dict(snap, registry=self.doc.registry)
            self._load_doc(doc)
            self.inspector.show_node(None)
        finally:
            self._restoring = False

    def undo(self) -> None:
        snap = self._history.undo()
        if snap is not None:
            self._restore_snapshot(snap)

    def redo(self) -> None:
        snap = self._history.redo()
        if snap is not None:
            self._restore_snapshot(snap)

    def copy_selection(self) -> None:
        clip = self.scene.copy_selection()
        if clip is not None:
            self._clipboard = clip

    def paste_clipboard(self) -> None:
        if self._clipboard is not None:
            self.scene.paste(self._clipboard)

    def snapshot_after_move(self) -> None:
        """Зафиксировать перемещение узлов в истории (вызывается по отпусканию ЛКМ)."""
        if not self._restoring:
            self._history.push(self.doc.to_spec_dict())
            self._sync_json_from_doc()

    # ---- Навигация по вложенному телу цикла (repeat.body) ----

    def _enter_subgraph(self, node_id: str, param_key: str) -> None:
        """Открыть тело цикла как отдельный холст. Текущий уровень — в стек."""
        parent_doc = self.doc
        node = parent_doc.nodes.get(node_id)
        if node is None:
            return
        body = node.params.get(param_key) or {"nodes": [], "edges": [], "meta": {}}
        try:
            child = GraphDocument.from_spec_dict(body)
        except GraphValidationError as e:
            QMessageBox.warning(self, "Не удалось открыть тело цикла", str(e))
            return
        self._nav_stack.append((parent_doc, node_id, param_key))
        self._load_doc(child)
        self._update_breadcrumb()

    def _exit_subgraph(self) -> None:
        """Вернуться на уровень выше, сохранив отредактированное тело в параметр."""
        if not self._nav_stack:
            return
        child_doc = self.doc
        parent_doc, node_id, param_key = self._nav_stack.pop()
        node = parent_doc.nodes.get(node_id)
        if node is not None:
            node.params[param_key] = child_doc.to_spec_dict()
        self._load_doc(parent_doc)
        self._update_breadcrumb()

    def _flush_subgraphs(self) -> None:
        """Свернуть весь стек обратно в корневой граф (перед сохранением/проверкой)."""
        while self._nav_stack:
            self._exit_subgraph()

    def _update_breadcrumb(self) -> None:
        depth = len(self._nav_stack)
        self.back_btn.setVisible(depth > 0)
        if depth == 0:
            self.breadcrumb.setText("Главный граф")
        else:
            trail = " › ".join(f"тело «{nid}»" for _d, nid, _k in self._nav_stack)
            self.breadcrumb.setText("Главный граф › " + trail)

    # ---- Синхронизация холст ⇄ JSON ----

    def _sync_json_from_doc(self) -> None:
        self.json_edit.blockSignals(True)
        self.json_edit.setPlainText(
            json.dumps(self.doc.to_spec_dict(), ensure_ascii=False, indent=2)
        )
        self.json_edit.blockSignals(False)

    def _on_tab_changed(self, index: int) -> None:
        # При уходе на JSON — обновить его из холста.
        if self.tabs.tabText(index) == "JSON":
            self._sync_json_from_doc()

    def _apply_json_to_canvas(self) -> None:
        text = self.json_edit.toPlainText().strip()
        try:
            doc = GraphDocument.from_spec_dict(text)
        except GraphValidationError as e:
            QMessageBox.warning(self, "Ошибка JSON", str(e))
            return
        self._load_doc(doc)
        self.tabs.setCurrentIndex(0)

    # ---- Проверка и предпросмотр (через движок) ----

    def _root_spec_dict(self) -> dict:
        """
        Корневой граф как dict, даже если открыто вложенное тело цикла.
        Текущий уровень сворачивается в стек неразрушающе (UI не трогаем).
        """
        if not self._nav_stack:
            return self.doc.to_spec_dict()
        # Свернуть текущее тело в копию родительских узлов снизу вверх.
        current = self.doc.to_spec_dict()
        for parent_doc, node_id, param_key in reversed(self._nav_stack):
            parent_dict = parent_doc.to_spec_dict()
            for n in parent_dict["nodes"]:
                if n["id"] == node_id:
                    n["params"] = {**n.get("params", {}), param_key: current}
                    break
            current = parent_dict
        return current

    def _current_spec(self) -> GraphSpec:
        return GraphSpec.parse(self._root_spec_dict())

    def _on_check(self) -> None:
        try:
            GraphExecutor(self._current_spec())
        except GraphError as e:
            self.preview.setPlainText(f"✗ Ошибка: {e}")
            return
        self.preview.setPlainText("✓ Граф корректен.")

    def _on_preview(self) -> None:
        from exercises.graph.generators import GraphConstructorGenerator
        try:
            gen = GraphConstructorGenerator(
                partition_id=self.partition_id or 0,
                name=self.name_edit.text() or "preview",
                config=self._root_spec_dict(),
            )
            task = gen.generate()
        except GraphError as e:
            self.preview.setPlainText(f"✗ Ошибка генерации: {e}")
            return
        lines = ["УСЛОВИЕ:"]
        lines += [b.render_plain() for b in getattr(task, "statement", [])]
        lines += ["", "ОТВЕТ:"]
        lines += [b.render_plain() for b in getattr(task, "answer", [])]
        self.preview.setPlainText("\n".join(lines))

    # ---- Загрузка существующего раздела ----

    def load_existing(self) -> None:
        part = self.repo.get_partition(self.partition_id)
        if part is None:
            self._show_error(f"Раздел {self.partition_id} не найден.")
            return
        self.name_edit.setText(part.name)

        cfg = part.generation_params
        if "raw" in cfg:
            try:
                cfg = json.loads(cfg["raw"])
            except (json.JSONDecodeError, TypeError):
                cfg = {}
        try:
            self._load_doc(GraphDocument.from_spec_dict(cfg))
        except GraphValidationError as e:
            self._show_error(f"Не удалось загрузить граф: {e}")

    # ---- Сборка payload ----

    def collect_payload(self):
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("Введите название раздела.")

        # Сохраняем корневой граф (с учётом открытых вложенных тел циклов).
        root = self._root_spec_dict()
        # Валидируем структуру до записи в БД — лучше упасть здесь.
        try:
            GraphExecutor(GraphSpec.parse(root))
        except GraphError as e:
            raise ValueError(f"Граф некорректен: {e}")

        return name, self.CONSTRACTED, root
