from PyQt6 import uic
from PyQt6.QtWidgets import (QMessageBox, QPushButton, QHeaderView,
                             QWidget, QVBoxLayout, QHBoxLayout, QRadioButton,
                             QTableWidget, QTableWidgetItem, QAbstractItemView,
                             QSizePolicy)
from PyQt6.QtCore import Qt

from pycode.exercises.fisic.constructor_window import ExerciseWindow
from pycode.exercises.fisic.fisic_generater import generate_fisic_task


class ConstructedTasks(QWidget):
    def __init__(self, partitions_id, generation_settings, main_obj):
        super().__init__()
        uic.loadUi('resources/exercises/fisic/fisic_task_generated_interface.ui', self)

        self.main_obj = main_obj
        self.editer = ExerciseWindow(self.main_obj)
        self.partitions_id = partitions_id
        self.generation_settings = generation_settings

        # Создаем отсутствующие элементы интерфейса
        self.create_missing_widgets()

        # Настройка таблицы
        self.setup_table()

        # Настройка кнопок и соединений
        self.setup_buttons_and_connections()

        self.answer_popup = QMessageBox(self)
        self.answer_popup.setWindowTitle("Правильный ответ")
        self.answer_popup.setStandardButtons(QMessageBox.StandardButton.Ok)

        self.task_popup = QMessageBox(self)
        self.task_popup.setWindowTitle("Текст задания")
        self.task_popup.setStandardButtons(QMessageBox.StandardButton.Ok)

    def create_missing_widgets(self):
        """Создает отсутствующие элементы интерфейса"""
        # Проверяем и создаем основные элементы если они не найдены
        if not hasattr(self, 'tasksView') or not self.findChild(QTableWidget, 'tasksView'):
            self.tasksView = QTableWidget(self)
            self.tasksView.setObjectName('tasksView')

        if not hasattr(self, 'buttonsContainer') or not self.findChild(QWidget, 'buttonsContainer'):
            self.buttonsContainer = QWidget(self)
            self.buttonsContainer.setObjectName('buttonsContainer')

        # Создаем кнопки если они отсутствуют
        if not hasattr(self, 'generateButton'):
            self.generateButton = QPushButton("Сгенерировать", self.buttonsContainer)
        if not hasattr(self, 'exportButton'):
            self.exportButton = QPushButton("Экспорт", self.buttonsContainer)
        if not hasattr(self, 'editButton'):
            self.editButton = QPushButton("Редактировать шаблон", self.buttonsContainer)
        if not hasattr(self, 'showAnswersButton'):
            self.showAnswersButton = QRadioButton("Показать ответы", self.buttonsContainer)

        # Создаем основной макет если его нет
        if not self.layout():
            main_layout = QVBoxLayout(self)
            main_layout.addWidget(self.buttonsContainer)
            main_layout.addWidget(self.tasksView)

        # Создаем layout для кнопок если его нет
        if not self.buttonsContainer.layout():
            buttons_layout = QHBoxLayout(self.buttonsContainer)
            buttons_layout.addWidget(self.generateButton)
            buttons_layout.addWidget(self.exportButton)
            buttons_layout.addWidget(self.editButton)
            buttons_layout.addWidget(self.showAnswersButton)
            buttons_layout.addStretch()

    def setup_table(self):
        """Настройка таблицы с базовой шириной столбцов и автоматической высотой строк"""
        self.tasksView.setColumnCount(3)
        self.tasksView.setHorizontalHeaderLabels(["Задание", "Ответ", "Удалить"])

        # Базовая настройка ширины столбцов
        self.tasksView.setColumnWidth(0, 430)  # Ширина для столбца заданий
        self.tasksView.setColumnWidth(1, 150)  # Уменьшенная ширина для столбца ответов
        self.tasksView.setColumnWidth(2, 80)  # Фиксированная ширина для кнопки удаления

        # Настройка поведения заголовков - разрешаем ручное изменение ширины
        header = self.tasksView.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)

        # Настройка вертикального заголовка для автоматической высоты строк
        vertical_header = self.tasksView.verticalHeader()
        vertical_header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        vertical_header.setDefaultSectionSize(40)  # Минимальная высота по умолчанию

        # Включение переноса текста
        self.tasksView.setWordWrap(True)
        self.tasksView.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.tasksView.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.tasksView.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        # Установка политики размера
        self.tasksView.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def setup_buttons_and_connections(self):
        """Настройка кнопок и их соединений"""
        self.generateButton.clicked.connect(self.generate_task)
        self.exportButton.clicked.connect(self.export_tasks)
        self.editButton.clicked.connect(self.edit)
        self.showAnswersButton.clicked.connect(self.show_all_answers)
        self.tasksView.cellClicked.connect(self.on_cell_clicked)

    def on_cell_clicked(self, row, column):
        """Обрабатывает клики по ячейкам таблицы"""
        if column == 0:  # Клик по ячейке с заданием
            self.show_task_text(row)
        elif column == 1:  # Клик по ячейке с ответом
            self.show_answer(row)

    def show_task_text(self, row):
        """Показывает полный текст задания в диалоговом окне"""
        task_item = self.tasksView.item(row, 0)
        if task_item:
            task_text = task_item.text()
            self.task_popup.setText(f"<b>Текст задания:</b><br>{task_text}")
            self.task_popup.exec()

    def show_answer(self, row):
        """Показывает ответ при клике на ячейку ответа только если ответы скрыты"""
        if not self.showAnswersButton.isChecked():
            answer_item = self.tasksView.item(row, 1)
            if answer_item and answer_item.text() == "Нажмите для просмотра":
                real_answer = answer_item.data(Qt.ItemDataRole.UserRole)
                self.answer_popup.setText(f"<b>Правильный ответ:</b><br>{real_answer}")
                self.answer_popup.exec()

    def edit(self):
        self.editer.edit_exercise(self.partitions_id, self.generation_settings)
        self.editer.show()

    def show_all_answers(self):
        show_answers = self.showAnswersButton.isChecked()

        for row in range(self.tasksView.rowCount()):
            answer_item = self.tasksView.item(row, 1)
            if answer_item:
                real_answer = answer_item.data(Qt.ItemDataRole.UserRole)

                if show_answers:
                    answer_item.setText(real_answer)
                    answer_item.setFlags(answer_item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                else:
                    answer_item.setText("Нажмите для просмотра")
                    answer_item.setFlags(answer_item.flags() | Qt.ItemFlag.ItemIsEnabled)

        # Обновляем высоту строк после изменения содержимого
        self.tasksView.resizeRowsToContents()

    def generate_task(self):
        try:
            text, answer = generate_fisic_task(self.generation_settings)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось сгенерировать задание: {str(e)}")
            return

        row_position = self.tasksView.rowCount()
        self.tasksView.insertRow(row_position)

        # Создание элемента для задания
        task_item = QTableWidgetItem(text)
        task_item.setFlags(task_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        task_item.setToolTip("Нажмите для просмотра полного текста задания")

        # Создание элемента для ответа
        show_answers = self.showAnswersButton.isChecked()
        answer_text = answer if show_answers else "Нажмите для просмотра"
        answer_item = QTableWidgetItem(answer_text)
        answer_item.setData(Qt.ItemDataRole.UserRole, answer)
        answer_item.setToolTip("Нажмите для просмотра ответа")

        if not show_answers:
            answer_item.setFlags(answer_item.flags() | Qt.ItemFlag.ItemIsEnabled)
        else:
            answer_item.setFlags(answer_item.flags() & ~Qt.ItemFlag.ItemIsEnabled)

        # Кнопка удаления
        delete_btn = QPushButton("❌")
        delete_btn.setFixedSize(30, 30)
        delete_btn.setToolTip("Удалить задание")
        delete_btn.clicked.connect(lambda: self.confirm_delete_row(row_position))

        # Размещение элементов в таблице
        self.tasksView.setItem(row_position, 0, task_item)
        self.tasksView.setItem(row_position, 1, answer_item)
        self.tasksView.setCellWidget(row_position, 2, delete_btn)

        # Обновляем высоту строки для нового содержимого
        self.tasksView.resizeRowToContents(row_position)

    def confirm_delete_row(self, row):
        msg = QMessageBox(self)
        msg.setWindowTitle("Подтверждение удаления")
        msg.setText("Вы уверены, что хотите удалить это задание?")
        msg.setIcon(QMessageBox.Icon.Question)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)

        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.tasksView.removeRow(row)

    def export_tasks(self):
        tasks_data = []
        for row in range(self.tasksView.rowCount()):
            task_item = self.tasksView.item(row, 0)
            answer_item = self.tasksView.item(row, 1)
            if task_item and answer_item:
                real_answer = answer_item.data(Qt.ItemDataRole.UserRole)
                tasks_data.append({
                    'task': task_item.text(),
                    'answer': real_answer
                })

        QMessageBox.information(self, "Экспорт",
                                f"Готово к экспорту {len(tasks_data)} заданий")