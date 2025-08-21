# Импорт библиотек
from PyQt6 import uic
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QVBoxLayout
import sqlite3

# from pycode.adder.adder import TaskTypeEditor
from pycode.exercises.fisic.fisic_main import FisicMain
from pycode.exercises.linal.linal_main import LinalMain
from pycode.group_adder.group_adder import GroupAdder

db = r'C:\Users\happy\PycharmProjects\PythonProject4\resources\users_database.db'
class GeneratorWindow(QMainWindow):
    """Класс окна генератора заданий"""
    grouper = None

    def __init__(self):
        super().__init__()
        self.mainObject = None
        self.answer = None
        self.subject_id = 1

        # Настройка окна
        uic.loadUi('resources/templates/gen.ui', self)
        self.setWindowIcon(QIcon("resources/icon.png"))
        self.initialize_ui()

    def initialize_ui(self):
        self.setWindowTitle("Генератор")
        self.cur_sub = LinalMain(self)

        # Скрываем ненужные элементы
        self.generateButton.hide()
        self.taskText.hide()
        self.taskTitle.hide()
        self.answerButton.hide()
        self.generateButton.hide()

        # Инициализация списков из БД
        self.load_subjects_from_db()

        # Подключение сигналов
        self.type.itemClicked.connect(self.generate_exercise)
        self.subject.currentTextChanged.connect(self.handle_subject_change)
        self.profile.clicked.connect(self.go_to_profile)
        self.groupButton.clicked.connect(self.create_group)

        self.generator.setLayout(QVBoxLayout())

    def load_subjects_from_db(self):
        """Загрузка предметов из таблицы Subjects"""
        try:
            with sqlite3.connect(db) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT subject_name FROM Subjects")
                subjects = [row[0] for row in cursor.fetchall()]
                self.subject.clear()
                self.subject.addItems(subjects)
                self.handle_subject_change("Линейная алгебра")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки предметов: {str(e)}")

    def handle_subject_change(self, subject_name):
        """Обработка изменения выбранного предмета"""
        try:
            with sqlite3.connect(db) as conn:
                cursor = conn.cursor()

                # Получаем ID выбранного предмета
                cursor.execute(
                    "SELECT id FROM Subjects WHERE subject_name = ?",
                    (subject_name,)
                )
                subject_id = cursor.fetchone()
                self.subject_id = subject_id[0]

                cursor.execute(
                    "SELECT pra_subject FROM Subjects WHERE subject_name = ?",
                    (subject_name,)
                )
                science = cursor.fetchone()[0]

                if subject_id:
                    # Загружаем типы заданий для выбранного предмета
                    cursor.execute(
                        """SELECT partition_name 
                        FROM Partitions 
                        WHERE subject_id = ?""",
                        (subject_id[0],)
                    )
                    partitions = [row[0] for row in cursor.fetchall()]
                    self.type.clear()
                    self.type.addItems(partitions)
                # print(science)
                if science == "Линейная алгебра":
                    self.cur_sub = LinalMain(self)
                elif science == "Физика":
                    self.cur_sub = FisicMain(self)

                # Обработка специальных случаев
                # self.update_tasks_list(subject_name)

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки типов заданий: {str(e)}")

    def generate_exercise(self, item):
        layout = self.generator.layout()
        while layout.count():
            child = layout.takeAt(0)
            widget = child.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()
        with sqlite3.connect(db) as conn:
            cursor = conn.cursor()

            # Получаем ID выбранного предмета
            cursor.execute(
                f"SELECT id FROM Partitions WHERE subject_id = {self.subject_id} AND partition_name = '{item.text()}'")
            partition_id = cursor.fetchone()[0]
            self.cur_sub.get_ex(partition_id)

    def create_group(self):
        self.grouper = GroupAdder(self.subject_id, self.mainObject)
        self.grouper.show()

    def go_to_profile(self):
        self.mainObject.change_cur_obj(self.mainObject.profile)
