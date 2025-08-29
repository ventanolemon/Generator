import json
import random
import sqlite3

from PyQt6 import uic
from PyQt6.QtWidgets import QMessageBox, QPushButton, QHeaderView, QWidget, QVBoxLayout, QHBoxLayout, QRadioButton

from pycode.exercises.fisic.constructor_window import ExerciseWindow
from pycode.exercises.fisic.fisic_generater import generate_fisic_task
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem
from const import db
from pycode.group_adder.group_adder import GroupAdder


class ConstructedGroup(QWidget):
    def __init__(self, partitions_ids, pra_obj=None):
        super().__init__()
        uic.loadUi('pycode/exercises/fisic/fisic_task_generated_interface.ui', self)

        self.pra_obj = pra_obj
        self.editer = GroupAdder(subject_id=self.pra_obj.main_obj.subject_id, main_obj=self.pra_obj.main_obj)

        # Сохраняем список настроек генерации
        self.partitions_ids = partitions_ids  # список ID разделов
        generation_settings_list = []
        with sqlite3.connect(db) as conn:
            cursor = conn.cursor()
            for partitions_id in self.partitions_ids:
                cursor.execute(
                    f"SELECT generation_parametrs FROM Partitions WHERE id = {partitions_id}",
                )
                generation_settings_list.append(cursor.fetchone()[0])
        self.generation_settings_list = generation_settings_list  # список настроек
        # print(self.generation_settings_list)

        # Проверка корректности входных данных
        if not self.partitions_ids or not self.generation_settings_list:
            raise ValueError("Список разделов и настроек не может быть пустым")

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
            self.showAnswersButton = QRadioButton("Показать ответы", buttons_container)

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
        buttons_layout.addWidget(self.showAnswersButton)
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
        self.showAnswersButton.clicked.connect(self.show_all_answers)
        self.tasksView.cellClicked.connect(self.show_answer)

        self.answer_popup = QMessageBox(self)
        self.answer_popup.setWindowTitle("Правильный ответ")
        self.answer_popup.setStandardButtons(QMessageBox.StandardButton.Ok)

    def edit(self):
        self.editer.edit_group()

    def show_all_answers(self):
        pos = self.showAnswersButton.isChecked()
        if pos:
            cnt = self.tasksView.rowCount()
            # print(help(self.tasksView))
            for i in range(cnt):
                answer_item = self.tasksView.item(i, 1)
                real_answer = answer_item.data(Qt.ItemDataRole.UserRole)
                res_item = QTableWidgetItem(real_answer)
                self.tasksView.setItem(i, 1, res_item)
        else:
            cnt = self.tasksView.rowCount()
            # print(help(self.tasksView))
            for i in range(cnt):
                answer_item = self.tasksView.item(i, 1)
                answer = answer_item.text()
                answer_item = QTableWidgetItem("Нажмите для просмотра")
                answer_item.setData(Qt.ItemDataRole.UserRole, answer)  # Сохранение ответа
                answer_item.setFlags(answer_item.flags() | Qt.ItemFlag.ItemIsEnabled)  # Разрешаем взаимодействие
                self.tasksView.setItem(i, 1, answer_item)
        self.tasksView.resizeColumnToContents(0)
        self.tasksView.resizeColumnToContents(1)

    def show_answer(self, row, column):
        """Показывает ответ при клике на ячейку ответа"""
        if column == 1:  # Только для столбца с ответами
            answer_item = self.tasksView.item(row, column)
            if answer_item:
                real_answer = answer_item.data(Qt.ItemDataRole.UserRole)
                self.answer_popup.setText(f"<b>Правильный ответ:</b><br>{real_answer}")
                self.answer_popup.exec()

    def get_task(self):
        # Выбираем случайные настройки генерации
        if not self.generation_settings_list:
            QMessageBox.warning(self, "Ошибка", "Нет доступных настроек генерации")
            return
        numb = random.randint(0, len(self.partitions_ids) - 1)
        # selected_settings = random.choice(self.generation_settings_list)
        selected_settings = self.generation_settings_list[numb]

        # Генерируем задание
        try:
            if self.pra_obj.main_obj.pra_subject_id == 1:
                if selected_settings:
                    # print(self.partitions_ids[numb])
                    pass  # сюдааа доработать когда добавлю конструктор по линалу
                else:
                    # print(self.partitions_ids[numb])
                    text, answer = self.pra_obj.give_ex(self.partitions_ids[numb])

            elif self.pra_obj.main_obj.pra_subject_id == 3:
                text, answer = generate_fisic_task(selected_settings)
            return text, answer
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка генерации задания: {str(e)}")
            return -1

    def generate_task(self):
        text, answer = self.get_task()

        # Определение позиции для вставки
        row_position = self.tasksView.rowCount()

        # Вставка новой строки
        self.tasksView.insertRow(row_position)

        # Создание элементов таблицы
        task_item = QTableWidgetItem(text)
        task_item.setFlags(task_item.flags() & ~Qt.ItemFlag.ItemIsEditable)  # Запрет редактирования

        pos = self.showAnswersButton.isChecked()
        if pos:
            answer_item = QTableWidgetItem(answer)
        else:
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
        self.tasksView.resizeColumnToContents(1)

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
