from PyQt6.QtWidgets import (
    QMainWindow, QMessageBox
)
from PyQt6.QtCore import pyqtSignal
import sqlite3
import json

from PyQt6.uic import loadUi


db = r'C:\Users\happy\PycharmProjects\PythonProject4\resources\users_database.db'
class TaskTypeEditor(QMainWindow):
    saved = pyqtSignal()  # Сигнал успешного сохранения

    def __init__(self, generation_params: dict, main_obj=None):
        super().__init__()
        self.generation_params = generation_params
        print(generation_params)
        loadUi('pycode/exercises/fisic/adder_interface.ui', self)  # загружаем UI файл

        self.load_subjects()
        self.connect_signals()

    def connect_signals(self):
        """Подключение сигналов"""
        self.addNewSubject.clicked.connect(self.add_subject)
        self.saveType.clicked.connect(self.save_partition)

    def load_subjects(self):
        """Загрузка предметов из БД"""
        try:
            with sqlite3.connect(db) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, subject_name FROM Subjects WHERE pra_subject = 'Физика'"
                )
                self.subjetChoose.clear()
                for subj_id, name in cursor.fetchall():
                    print()
                    self.subjetChoose.addItem(name, subj_id)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки: {str(e)}")

    def add_subject(self):
        """Добавление нового предмета"""
        new_name = self.newSubject.text().strip()
        if not new_name:
            QMessageBox.warning(self, "Ошибка", "Введите название предмета")
            return

        try:
            with sqlite3.connect(db) as conn:
                cursor = conn.cursor()
                # Проверка существования
                cursor.execute(
                    "SELECT 1 FROM Subjects WHERE subject_name = ? AND pra_subject = 'физика'",
                    (new_name,)
                )
                if cursor.fetchone():
                    QMessageBox.warning(self, "Ошибка", "Предмет уже существует")
                    return

                # Добавление
                cursor.execute(
                    "INSERT INTO Subjects (subject_name, pra_subject) VALUES (?, 'Физика')",
                    (new_name,)
                )
                conn.commit()
                self.load_subjects()
                self.newSubject.clear()
                QMessageBox.information(self, "Успех", "Предмет добавлен")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка БД: {str(e)}")

    def save_partition(self):
        """Сохранение типа задания"""
        if self.subjetChoose.currentIndex() == -1:
            QMessageBox.warning(self, "Ошибка", "Выберите предмет")
            return

        # Подготовка данных
        subject_id = self.subjetChoose.currentData()
        partition_name = self.typeName.text()
        if not partition_name:
            partition_name = "Без названия"
        # is_constructed = 'generation_parameters' in self.generation_params
        params = json.dumps(self.generation_params)
        try:
            with sqlite3.connect(db) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """INSERT INTO Partitions 
                    (subject_id, partition_name, constracted, generation_parametrs)
                    VALUES (?, ?, ?, ?)""",
                    (subject_id, partition_name, 1, params)
                )
                conn.commit()
                self.saved.emit()
                QMessageBox.information(self, "Успех", "Тип задания сохранён")
                self.close()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка сохранения: {str(e)}")


# Пример использования
if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication

    app = QApplication([])

    # Тестовые параметры
    params = {
        "partition_name": "Кинематика",
        "generation_parameters": {
            "formula": "v = s/t",
            "variables": {
                "s": {"min": 10, "max": 100},
                "t": {"min": 1, "max": 10}
            }
        }
    }

    window = TaskTypeEditor(params)
    window.show()
    app.exec()
