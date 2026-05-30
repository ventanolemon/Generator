"""
GraphEditor — минимальный редактор раздела-графа (constracted=4).

Фаза 1: граф вводится как JSON-текст (полноценный визуальный канвас —
Фаза 2). Вся валидация и предпросмотр переиспользуют движок core.graph,
никакой собственной логики проверки здесь нет:

  * «Проверить»     — GraphExecutor(GraphSpec.parse(text)) собирает и валидирует
                      граф (типы портов, висячие провода, циклы, обязательные
                      входы). Ошибка показывается пользователю.
  * «Предпросмотр»  — GraphConstructorGenerator.generate() исполняет граф и
                      показывает условие/ответ как текст.

По «Сохранить» пишет (name, 4, graph_dict) в Partitions через общий контракт
PartitionEditor.
"""

from __future__ import annotations
import json

from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QLabel,
    QPlainTextEdit,
)

from core.graph import GraphError, GraphExecutor, GraphSpec, GraphValidationError

from .base import PartitionEditor


# Шаблон по умолчанию для нового графа (физика «путь = v · t»).
def _default_graph_text() -> str:
    from exercises.graph.generators import EXAMPLE_GRAPH
    return json.dumps(EXAMPLE_GRAPH, ensure_ascii=False, indent=2)


class GraphEditor(PartitionEditor):
    """Текстовый редактор графа (constracted=4)."""

    CONSTRACTED = 4

    def __init__(self, repository, subject_id, partition_id=None, parent=None):
        super().__init__(repository, subject_id, partition_id, parent)
        self._build_ui()
        if self.is_edit_mode:
            self.load_existing()
        else:
            self.graph_edit.setPlainText(_default_graph_text())

    # ---- UI ----

    def _build_ui(self) -> None:
        self.setMinimumSize(820, 680)
        self.setWindowTitle(
            "Редактирование графа" if self.is_edit_mode else "Создание графа"
        )

        root = QVBoxLayout(self)

        root.addWidget(QLabel("Название раздела:"))
        self.name_edit = QLineEdit(self)
        root.addWidget(self.name_edit)

        root.addWidget(QLabel("Описание графа (JSON: nodes / edges / meta):"))
        self.graph_edit = QPlainTextEdit(self)
        self.graph_edit.setStyleSheet("font-family: Consolas, monospace;")
        root.addWidget(self.graph_edit, stretch=1)

        # Полоса инструментов: проверить / предпросмотр
        tools = QHBoxLayout()
        check_btn = QPushButton("Проверить", self)
        preview_btn = QPushButton("Предпросмотр", self)
        tools.addWidget(check_btn)
        tools.addWidget(preview_btn)
        tools.addStretch()
        root.addLayout(tools)

        root.addWidget(QLabel("Результат проверки / предпросмотр:"))
        self.preview = QPlainTextEdit(self)
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(160)
        root.addWidget(self.preview)

        # Save / Cancel
        btns = QHBoxLayout()
        save_btn = QPushButton("Сохранить", self)
        cancel_btn = QPushButton("Отмена", self)
        btns.addStretch()
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        root.addLayout(btns)

        check_btn.clicked.connect(self._on_check)
        preview_btn.clicked.connect(self._on_preview)
        save_btn.clicked.connect(self.save)
        cancel_btn.clicked.connect(self._on_cancel)

    def _on_cancel(self) -> None:
        self.cancelled.emit()
        self.close()

    # ---- Проверка и предпросмотр (через движок) ----

    def _parse_spec(self) -> GraphSpec:
        """Распарсить текст в GraphSpec. Бросает ValueError для UI."""
        text = self.graph_edit.toPlainText().strip()
        if not text:
            raise ValueError("Опишите граф в формате JSON.")
        try:
            return GraphSpec.parse(text)
        except GraphValidationError as e:
            raise ValueError(str(e))

    def _on_check(self) -> None:
        try:
            spec = self._parse_spec()
            GraphExecutor(spec)            # сборка = полная структурная валидация
        except (ValueError, GraphError) as e:
            self.preview.setPlainText(f"✗ Ошибка: {e}")
            return
        self.preview.setPlainText("✓ Граф корректен.")

    def _on_preview(self) -> None:
        try:
            spec = self._parse_spec()
        except ValueError as e:
            self.preview.setPlainText(f"✗ Ошибка: {e}")
            return
        from exercises.graph.generators import GraphConstructorGenerator
        try:
            gen = GraphConstructorGenerator(
                partition_id=self.partition_id or 0,
                name=self.name_edit.text() or "preview",
                config=spec.to_dict(),
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
        self.graph_edit.setPlainText(json.dumps(cfg, ensure_ascii=False, indent=2))

    # ---- Сборка payload ----

    def collect_payload(self):
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("Введите название раздела.")

        spec = self._parse_spec()
        # Валидируем структуру до записи в БД — лучше упасть здесь.
        try:
            GraphExecutor(spec)
        except GraphError as e:
            raise ValueError(f"Граф некорректен: {e}")

        return name, self.CONSTRACTED, spec.to_dict()
