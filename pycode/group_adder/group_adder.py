from PyQt6.QtWidgets import (
    QMainWindow, QMessageBox, QWidget, QVBoxLayout, QListWidget, QListWidgetItem, QPushButton, QLabel
)
from PyQt6.QtCore import pyqtSignal, Qt
import sqlite3
import json
from const import db
from PyQt6.uic import loadUi


class GroupAdder(QMainWindow):
    saved = pyqtSignal()  # Сигнал успешного сохранения
    partitions = []

    def __init__(self, subject_id, main_obj):
        super().__init__()
        self.subject_id = subject_id
        self.main_obj = main_obj
        loadUi('pycode/group_adder/group_adder_interface.ui', self)  # загружаем UI файл
        # loadUi('group_adder_interface.ui', self)  # загружаем UI файл

        self.load_partitions()
        self.load_subjects()
        self.connect_signals()

        self.init_checker()

    def connect_signals(self):
        """Подключение сигналов"""
        self.saveType.clicked.connect(self.save_group)

    def load_partitions(self):
        try:
            with sqlite3.connect(db) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT partition_name FROM Partitions WHERE subject_id = {self.subject_id} AND constracted <> 2"
                )
                subj = cursor.fetchall()
                self.partitions = []
                for partition in subj:
                    self.partitions.append(partition[0])

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки: {str(e)}")

    def load_subjects(self):
        """Загрузка предметов из БД"""
        try:
            with sqlite3.connect(db) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, subject_name FROM Subjects"
                )
                self.subjetChoose.clear()
                for subj_id, name in cursor.fetchall():
                    self.subjetChoose.addItem(name, subj_id)
                self.subjetChoose.setCurrentIndex(self.subject_id - 1)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки: {str(e)}")

    def init_checker(self):
        # Создаем новый CheckboxListWidget
        self.partitionsChoose = CheckboxListWidget()

        parent_layout = self.gridLayout  # Предполагаем, что layout называется gridLayout
        parent_layout.addWidget(self.partitionsChoose, 0, 1)

        # Загружаем данные в новый виджет
        self.load_partitions_to_checkbox()
        self.partitionsChoose.show()

    def load_partitions_to_checkbox(self):
        # Очищаем список
        self.partitionsChoose.list_widget.clear()

        # Добавляем элементы из базы данных
        for partition in self.partitions:
            list_item = QListWidgetItem(partition)
            list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            list_item.setCheckState(Qt.CheckState.Unchecked)
            self.partitionsChoose.list_widget.addItem(list_item)

    def save_group(self):
        """Сохранение данных в таблицу Partitions"""
        # Проверка обязательных полей
        if not self.groupName.text().strip():
            QMessageBox.warning(self, "Ошибка", "Введите название раздела")
            return

        if self.subjetChoose.currentIndex() == -1:
            QMessageBox.warning(self, "Ошибка", "Выберите предмет")
            return

        # Сбор данных из partitionsChoose
        selected_tasks = []
        for i in range(self.partitionsChoose.list_widget.count()):
            item = self.partitionsChoose.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                with sqlite3.connect(db) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        f"SELECT id, constracted FROM Partitions WHERE subject_id = {self.subject_id} "
                        f"AND partition_name = '{item.text()}'"
                    )
                    task_id, constracted = cursor.fetchone()
                    # Предполагаем, что текст элемента содержит нужные данные
                    task_data = {
                        "task_id": task_id,
                        "constracted": constracted,
                        "task_type": item.text(),
                        # "params": params  # Здесь должны быть реальные параметры задания
                    }
                    selected_tasks.append(task_data)

        if not selected_tasks:
            QMessageBox.warning(self, "Ошибка", "Выберите хотя бы один тип задания")
            return

        # Формирование JSON
        try:
            generation_params = json.dumps(selected_tasks, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка формирования JSON: {str(e)}")
            return

        # Подготовка данных для БД
        subject_id = self.subject_id  # Используем переменную класса
        partition_name = self.groupName.text().strip()
        constracted = 2

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
                        (constracted, generation_params, subject_id, partition_name)
                    )
                else:
                    # Создание новой записи
                    cursor.execute(
                        """INSERT INTO Partitions 
                        (subject_id, partition_name, constracted, generation_parametrs)
                        VALUES (?, ?, ?, ?)""",
                        (subject_id, partition_name, constracted, generation_params)
                    )

                conn.commit()
                self.saved.emit()
                QMessageBox.information(self, "Успех", "Данные успешно сохранены")
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

    def edit_group(self):
        try:
            group_id = self.main_obj.partition_id
            # Очищаем текущие данные
            self.groupName.clear()
            self.partitionsChoose.list_widget.clear()

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
                    """, (group_id,)
                )

                group_data = cursor.fetchone()
                if not group_data:
                    QMessageBox.warning(self, "Ошибка", "Группа не найдена")
                    return

                group_name, generation_params = group_data

                # Загружаем название группы
                self.groupName.setText(group_name)

                # Загружаем параметры генерации
                try:
                    params_data = json.loads(generation_params)
                except json.JSONDecodeError:
                    QMessageBox.critical(
                        self,
                        "Ошибка",
                        "Некорректные данные в базе данных"
                    )
                    return

                # Получаем все доступные разделы
                cursor.execute(
                    """
                    SELECT 
                        id, 
                        partition_name 
                    FROM 
                        Partitions 
                    WHERE 
                        subject_id = ?
                    """, (self.subject_id,)
                )

                all_partitions = cursor.fetchall()

                # Создаем словарь для быстрого поиска
                partition_dict = {
                    partition_id: name
                    for partition_id, name in all_partitions
                }

                # Заполняем список разделов
                for partition_id, name in partition_dict.items():
                    list_item = QListWidgetItem(name)
                    list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                    list_item.setCheckState(Qt.CheckState.Unchecked)
                    self.partitionsChoose.list_widget.addItem(list_item)

                # Отмечаем выбранные разделы
                for task in params_data:
                    task_id = task.get("task_id")
                    if task_id in partition_dict:
                        for i in range(self.partitionsChoose.list_widget.count()):
                            item = self.partitionsChoose.list_widget.item(i)
                            if item.text() == partition_dict[task_id]:
                                item.setCheckState(Qt.CheckState.Checked)
                                break
                self.show()

        except sqlite3.Error as e:
            QMessageBox.critical(
                self,
                "Ошибка базы данных",
                f"Произошла ошибка при загрузке данных: {str(e)}"
            )
        # except Exception as e:
        #     QMessageBox.critical(
        #         self,
        #         "Ошибка",
        #         f"Непредвиденная ошибка: {str(e)}"
        #     )


class CheckboxListWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        layout = QVBoxLayout()

        # Создаем список с чекбоксами
        self.list_widget = QListWidget()

        layout.addWidget(self.list_widget)

        self.setLayout(layout)

    def add_items(self, items):
        self.list_widget.clear()
        for item in items:
            list_item = QListWidgetItem(item)
            list_item.setFlags(list_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            list_item.setCheckState(Qt.CheckState.Unchecked)
            self.list_widget.addItem(list_item)

    def get_selected(self):
        selected = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            # print()
            # checkbox = self.list_widget.itemWidget(item)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.text())
                # selected.append(checkbox.text())
        return selected if selected else None


# Пример использования
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    app = QApplication([])

    # Тестовые параметры
    params = [{
        "partition_name": "Кинематика",
        "generation_parameters": {
            "formula": "v = s/t",
            "variables": {
                "s": {"min": 10, "max": 100},
                "t": {"min": 1, "max": 10}
            }
        }
    }]

    window = GroupAdder(4, None)
    window.show()
    app.exec()
