import json
import sys
from PyQt6.QtWidgets import *
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIntValidator
import sqlite3
from const import db
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.uic import loadUi


class TestAdder(QMainWindow):
    def __init__(self, subject_id, main_obj):
        super().__init__()

        self.subject_id = subject_id
        self.main_obj = main_obj

        self.initUI()
        self.load_initial_data()

        # Настройка автоподбора
        self.typesTable.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)
        self.typesTable.horizontalHeader().setStretchLastSection(True)

        self.typesTable.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents)

        # Для мгновенного обновления при изменении данных
        self.typesTable.model().dataChanged.connect(self.update_table_sizes)

    def initUI(self):
        loadUi("resources/tester/test_adder_interface.ui", self)

        self.parentSubjectLabel.setText(self.main_obj.subject_name)

        # Настройка таблицы
        self.typesTable.setColumnCount(3)
        self.typesTable.setHorizontalHeaderLabels(["Тип задания", "Значение", "Действия"])
        self.typesTable.horizontalHeader().setStretchLastSection(True)

        # Сигналы
        self.addTypeBtn.clicked.connect(self.add_type_row)
        self.saveBtn.clicked.connect(self.save_data)

        # # Layout
        # layout = QVBoxLayout()
        # layout.addWidget(self.typesTable)
        # layout.addWidget(self.addTypeBtn)
        # layout.addWidget(self.selectType)
        # layout.addWidget(self.selectScience)
        # layout.addWidget(self.saveBtn)

        # container = QWidget()
        # container.setLayout(layout)
        # self.setCentralWidget(container)

    def load_initial_data(self):
        # Загрузка данных в комбо-боксы
        # self.selectType.addItems(["ddd", "ss", "fff"])
        with sqlite3.connect(db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT id, partition_name FROM Partitions WHERE subject_id = {self.subject_id}"
            )
            subj = cursor.fetchall()
            self.partitions = []
            for partition in subj:
                self.partitions.append(partition)
                self.selectType.addItem(partition[1], userData=partition[0])
            # self.selectType.addItems(self.partitions)

            cursor.execute(
                f"SELECT subject_name FROM Subjects WHERE pra_subject = "
                f"(SELECT subject_name FROM Subjects WHERE id = {self.main_obj.pra_subject_id})"
            )
            subjects = cursor.fetchall()
            self.subjects = []
            for partition in subjects:
                self.subjects.append(partition[0])
            self.selectScience.addItems(self.subjects)

    def add_type_row(self):
        row_position = self.typesTable.rowCount()
        self.typesTable.insertRow(row_position)

        # Название задания
        type_name = self.selectType.currentText()
        item = QTableWidgetItem(type_name)
        item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
        self.typesTable.setItem(row_position, 0, item)

        # Поле ввода значения
        value_edit = QLineEdit("1")
        value_edit.setValidator(QIntValidator(1, 100))
        self.typesTable.setCellWidget(row_position, 1, value_edit)

        # Кнопки управления с увеличенным размером
        btn_widget = QWidget()
        btn_layout = QHBoxLayout()

        # Настройка стилей для кнопок
        button_style = """
            QPushButton {
                font-size: 16px;
                min-width: 40px;
                max-width: 40px;
                min-height: 30px;
                max-height: 30px;
                border-radius: 5px;
                background-color: #000000;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
        """

        btn_up = QPushButton("↑")
        btn_down = QPushButton("↓")
        btn_delete = QPushButton("×")

        # Применяем стили ко всем кнопкам
        for btn in [btn_up, btn_down, btn_delete]:
            btn.setStyleSheet(button_style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        # Увеличиваем размер кнопки удаления
        btn_delete.setStyleSheet(button_style + "color: #ff0000;")

        btn_up.clicked.connect(lambda: self.move_row_up(row_position))
        btn_down.clicked.connect(lambda: self.move_row_down(row_position))
        btn_delete.clicked.connect(lambda: self.remove_row(row_position))

        btn_layout.addWidget(btn_up)
        btn_layout.addWidget(btn_down)
        btn_layout.addWidget(btn_delete)
        btn_widget.setLayout(btn_layout)

        # Устанавливаем отступы для виджета с кнопками
        btn_layout.setContentsMargins(5, 2, 5, 2)
        self.typesTable.setCellWidget(row_position, 2, btn_widget)

        self.update_buttons_state()

    def move_row_up(self, current_row):
        if current_row > 0:
            # Создаем копии данных без привязки к виджетам
            current_type = self.typesTable.item(current_row, 0).text()
            current_value = self.typesTable.cellWidget(current_row, 1).text()

            prev_type = self.typesTable.item(current_row - 1, 0).text()
            prev_value = self.typesTable.cellWidget(current_row - 1, 1).text()

            # Полностью перезаписываем строки
            self.typesTable.setItem(current_row - 1, 0, QTableWidgetItem(current_type))
            self.typesTable.setItem(current_row, 0, QTableWidgetItem(prev_type))

            # Создаем новые виджеты для значений
            self.typesTable.setCellWidget(current_row - 1, 1, self.create_value_edit(current_value))
            self.typesTable.setCellWidget(current_row, 1, self.create_value_edit(prev_value))

            # Пересоздаем кнопки с новыми привязками
            self.typesTable.setCellWidget(current_row - 1, 2, self.create_buttons(current_row - 1))
            self.typesTable.setCellWidget(current_row, 2, self.create_buttons(current_row))

            self.update_buttons_state()

    def move_row_down(self, current_row):
        if current_row < self.typesTable.rowCount() - 1:
            # Создаем копии данных без привязки к виджетам
            current_type = self.typesTable.item(current_row, 0).text()
            current_value = self.typesTable.cellWidget(current_row, 1).text()

            next_type = self.typesTable.item(current_row + 1, 0).text()
            next_value = self.typesTable.cellWidget(current_row + 1, 1).text()

            # Полностью перезаписываем строки
            self.typesTable.setItem(current_row + 1, 0, QTableWidgetItem(current_type))
            self.typesTable.setItem(current_row, 0, QTableWidgetItem(next_type))

            # Создаем новые виджеты для значений
            self.typesTable.setCellWidget(current_row + 1, 1, self.create_value_edit(current_value))
            self.typesTable.setCellWidget(current_row, 1, self.create_value_edit(next_value))

            # Пересоздаем кнопки с новыми привязками
            self.typesTable.setCellWidget(current_row + 1, 2, self.create_buttons(current_row + 1))
            self.typesTable.setCellWidget(current_row, 2, self.create_buttons(current_row))

            self.update_buttons_state()

    def create_value_edit(self, value):
        """Создает новый QLineEdit для значения"""
        edit = QLineEdit(value)
        edit.setValidator(QIntValidator(1, 100))
        return edit

    def create_buttons(self, row):
        """Создает новый набор кнопок для строки"""
        btn_widget = QWidget()
        btn_layout = QHBoxLayout()

        button_style = """
        QPushButton {
            font-size: 16px;
            min-width: 40px;
            max-width: 40px;
            min-height: 30px;
            max-height: 30px;
            border-radius: 5px;
            background-color: #000000;
        }
        QPushButton:hover {
            background-color: #e0e0e0;
        }
        """

        btn_up = QPushButton("↑")
        btn_down = QPushButton("↓")
        btn_delete = QPushButton("×")

        # Исправленная строка (выберите подходящий вариант):
        # cursor_shape = Qt.PointingHandCursor  # Для PyQt5
        cursor_shape = Qt.CursorShape.PointingHandCursor  # Для PyQt6/PySide6

        for btn in (btn_up, btn_down, btn_delete):
            btn.setStyleSheet(button_style)
            btn.setCursor(cursor_shape)

        # Подключение сигналов с фиксацией номера строки
        btn_up.clicked.connect(lambda _, r=row: self.move_row_up(r))
        btn_down.clicked.connect(lambda _, r=row: self.move_row_down(r))
        btn_delete.clicked.connect(lambda _, r=row: self.remove_row(r))

        btn_layout.addWidget(btn_up)
        btn_layout.addWidget(btn_down)
        btn_layout.addWidget(btn_delete)
        btn_widget.setLayout(btn_layout)

        return btn_widget

    def update_buttons_state(self):
        for row in range(self.typesTable.rowCount()):
            if widget := self.typesTable.cellWidget(row, 2):
                btn_up = widget.layout().itemAt(0).widget()
                btn_down = widget.layout().itemAt(1).widget()

                if btn_up:
                    btn_up.setEnabled(row > 0)
                if btn_down:
                    btn_down.setEnabled(row < self.typesTable.rowCount() - 1)

    def save_data(self):
        # Пример сохранения данных
        data = []
        for row in range(self.typesTable.rowCount()):
            type_name = self.typesTable.item(row, 0).text()
            value = self.typesTable.cellWidget(row, 1).text()

            index = self.selectType.findText(type_name)
            task_id = self.selectType.itemData(index)
            data.append((task_id, type_name, value))

        # Здесь логика сохранения в БД
        print("Сохраненные данные:", data)
        generation_parametrs = json.dumps({"parent_subject": self.main_obj.subject_id,
                                           "data": [dict(zip(("task_id", "task_name", "task_cnt"), task)) for task in data]})

        # Подготовка данных для БД
        subject_id = self.subject_id  # Используем переменную класса
        partition_name = self.testName.text().strip()
        constracted = 3

        if not partition_name:
            QMessageBox.warning(self, "Не удалось сохранить", "Введите название для группы")
            return -1

        try:
            with sqlite3.connect(db) as conn:
                cursor = conn.cursor()

                # Проверка существующей записи
                cursor.execute(
                    """SELECT * FROM Partitions 
                    WHERE subject_id = ? AND partition_name = ?""",
                    (subject_id, partition_name)
                )
                if cursor.fetchone():
                    # Обновление существующей записи
                    cursor.execute(
                        """UPDATE Partitions 
                        SET constracted = ?, 
                            generation_parametrs = ? 
                        WHERE subject_id = ? 
                        AND partition_name = ?""",
                        (constracted, generation_parametrs, subject_id, partition_name)
                            )
                else:
                    # Создание новой записи
                    cursor.execute(
                        """INSERT INTO Partitions 
                        (subject_id, partition_name, constracted, generation_parametrs)
                        VALUES (?, ?, ?, ?)""",
                        (subject_id, partition_name, constracted, generation_parametrs)
                    )

            conn.commit()
            # self.saved.emit()
            QMessageBox.information(self, "Сохранение", "Данные успешно сохранены!")
            self.close()

        except sqlite3.Error as e:
            QMessageBox.critical(
                self,
                "Ошибка базы данных",
                f"Не удалось сохранить данные: {str(e)}"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Непредвиденная ошибка: {str(e)}"
            )

    def remove_row(self, row):
        self.typesTable.removeRow(row)
        # self.update_row_numbers()
        self.update_buttons_state()

    def update_table_sizes(self):
        # self.typesTable.resizeColumnsToContents()
        # self.typesTable.resizeRowsToContents()
        # self.typesTable.horizontalHeader().setStretchLastSection(True)
        pass

    def edit_test(self):
        try:
            test_id = self.main_obj.partition_id

            # Подключение к БД
            with sqlite3.connect(db) as conn:
                cursor = conn.cursor()

                # Получаем информацию о группе
                cursor.execute(
                    """
                    SELECT 
                        partition_name, 
                        generation_parametrs 
                    FROM 
                        Partitions 
                    WHERE 
                        id = ?
                    """, (test_id,)
                )

                data = cursor.fetchone()
                current_settings = json.loads(data[1]).get("data")
                test_name = data[0]

                # Очищаем таблицу перед заполнением
                self.typesTable.setRowCount(0)
                print(2, current_settings)

                # Заполняем таблицу текущими настройками
                for setting in current_settings:
                    data = setting  # Берем словарь с настройками
                    print(1, data)
                    row_position = self.typesTable.rowCount()
                    self.typesTable.insertRow(row_position)

                    # Находим индекс в комбобоксе по task_id
                    task_id = data["task_id"]
                    index = next((i for i, partition in enumerate(self.partitions) if partition[0] == task_id), -1)

                    if index != -1:
                        # Устанавливаем название типа задания
                        item = QTableWidgetItem(self.selectType.itemText(index))
                        item.setFlags(item.flags() ^ Qt.ItemFlag.ItemIsEditable)
                        self.typesTable.setItem(row_position, 0, item)

                        # Устанавливаем значение количества
                        value_edit = QLineEdit(str(data["task_cnt"]))
                        value_edit.setValidator(QIntValidator(1, 100))
                        self.typesTable.setCellWidget(row_position, 1, value_edit)

                        # Добавляем кнопки управления
                        self.typesTable.setCellWidget(row_position, 2, self.create_buttons(row_position))

                self.testName.setText(test_name)

                self.update_buttons_state()
                self.show()

        except Exception as e:
            QMessageBox.critical(
                self,
                "Ошибка редактирования",
                f"Не удалось загрузить настройки теста: {str(e)}"
            )
            raise e


def except_hook(cls, exception, traceback):
    """Функция для обработки ошибок PyQT"""
    sys.__excepthook__(cls, exception, traceback)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = TestAdder(1, None)
    window.show()
    sys.excepthook = except_hook
    sys.exit(app.exec())
