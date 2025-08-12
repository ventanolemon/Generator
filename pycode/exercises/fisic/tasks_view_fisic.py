from PyQt6 import uic
from PyQt6.QtWidgets import QMessageBox, QPushButton, QHeaderView, QWidget, QVBoxLayout, QHBoxLayout

from pycode.exercises.fisic.constructor_window import ExerciseWindow
from pycode.exercises.fisic.fisic_generater import generate_fisic_task
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem


class ConstructedTasks(QWidget):
    def __init__(self, partitions_id, generation_settings, main_obj):
        super().__init__()
        uic.loadUi('pycode/exercises/fisic/fisic_task_generated_interface.ui', self)

        self.main_obj = main_obj
        self.editer = ExerciseWindow(self.main_obj)

        # Поиск основных элементов с созданием при необходимости
        original_table = self.findChild(QTableWidget, 'tasksView')
        buttons_container = self.findChild(QWidget, 'buttonsContainer')

        # Создаем отсутствующие элементы
        if not original_table:
            original_table = QTableWidget(self)
            original_table.setObjectName('tasksView')

        if not buttons_container:
            buttons_container = QWidget(self)
            buttons_container.setObjectName('buttonsContainer')
            self.generateButton = QPushButton("Сгенерировать", buttons_container)
            self.exportButton = QPushButton("Экспорт", buttons_container)
            self.editButton = QPushButton("Редактировать шаблон", buttons_container)

        # Создаем главный макет, если его нет
        main_layout = self.layout() or QVBoxLayout(self)

        # Добавляем элементы в макет
        main_layout.addWidget(buttons_container)
        main_layout.addWidget(self.tasksView)

        # Настройка кнопок
        buttons_layout = QHBoxLayout(buttons_container)
        buttons_layout.addWidget(self.generateButton)
        buttons_layout.addWidget(self.exportButton)
        buttons_layout.addWidget(self.editButton)
        buttons_layout.addStretch()

        # Настройка таблицы
        self.tasksView.setColumnCount(3)
        self.tasksView.setHorizontalHeaderLabels(["Задание", "Ответ", "Удалить"])
        header = self.tasksView.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)  # Разрешаем ручное изменение размеров
        header.setSectionsMovable(True)  # Разрешаем перемещение столбцов
        header.sectionResized.connect(self.handle_header_resize)  # Обработчик изменения размера

        # Установите начальные размеры столбцов (опционально)
        self.tasksView.setColumnWidth(0, 300)  # Ширина для столбца "Задание"
        self.tasksView.setColumnWidth(1, 200)  # Ширина для столбца "Ответ"
        self.tasksView.setColumnWidth(2, 100)  # Ширина для столбца "Удалить"

        # Подключение сигналов
        self.generateButton.clicked.connect(self.generate_task)
        self.exportButton.clicked.connect(self.export_tasks)
        self.editButton.clicked.connect(self.edit)
        self.tasksView.cellClicked.connect(self.show_answer)

        self.answer_popup = QMessageBox(self)
        self.answer_popup.setWindowTitle("Правильный ответ")
        self.answer_popup.setStandardButtons(QMessageBox.StandardButton.Ok)

        self.partitions_id = partitions_id
        self.generation_settings = generation_settings

    def edit(self):
        self.editer.edit_exercise(self.partitions_id, self.generation_settings, )
        self.editer.show()

    def show_answer(self, row, column):
        """Показывает ответ при клике на ячейку ответа"""
        if column == 1:  # Только для столбца с ответами
            answer_item = self.tasksView.item(row, column)
            if answer_item:
                real_answer = answer_item.data(Qt.ItemDataRole.UserRole)
                self.answer_popup.setText(f"<b>Правильный ответ:</b><br>{real_answer}")
                self.answer_popup.exec()

    def generate_task(self):
        text, answer = generate_fisic_task(self.generation_settings)

        # Определение позиции для вставки
        row_position = self.tasksView.rowCount()

        # Вставка новой строки
        self.tasksView.insertRow(row_position)

        # Создание элементов таблицы
        task_item = QTableWidgetItem(text)
        task_item.setFlags(task_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Запрет редактирования

        answer_item = QTableWidgetItem("Нажмите для просмотра")
        answer_item.setData(Qt.ItemDataRole.UserRole, answer)  # Сохранение ответа
        answer_item.setFlags(answer_item.flags() | Qt.ItemFlag.ItemIsEnabled)  # Разрешаем взаимодействие

        # Добавление кнопки удаления
        delete_btn = QPushButton("❌", self)
        delete_btn.clicked.connect(lambda _, r=row_position: self.confirm_delete_row(r))

        # Размещение элементов в таблице
        self.tasksView.setItem(row_position, 0, task_item)
        self.tasksView.setItem(row_position, 1, answer_item)
        self.tasksView.setCellWidget(row_position, 2, delete_btn)

        # Автоматическое растягивание столбца
        self.tasksView.resizeColumnToContents(0)

    def handle_cell_click(self, row, column):
        if column == 1:
            answer_item = self.tasksView.item(row, 1)
            if answer_item.text() == "Нажмите для просмотра":
                real_answer = answer_item.data(Qt.ItemDataRole.UserRole)
                answer_item.setText(real_answer)

    def handle_header_resize(self, logicalIndex, oldSize, newSize):
        """Обновление размеров столбцов при изменении"""
        self.tasksView.resizeRowsToContents()
        self.tasksView.updateGeometry()

    def confirm_delete_row(self, row):
        msg = QMessageBox(self)
        msg.setWindowTitle("Подтверждение удаления")
        msg.setText("Вы уверены, что хотите удалить это задание?")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.tasksView.removeRow(row)
            self.update_row_numbers()

    def update_row_numbers(self):
        for row in range(self.tasksView.rowCount()):
            btn = self.tasksView.cellWidget(row, 2)
            if btn:
                btn.clicked.disconnect()
                btn.clicked.connect(lambda _, r=row: self.confirm_delete_row(r))

    def export_tasks(self):
        pass  # Реализуйте по необходимости
