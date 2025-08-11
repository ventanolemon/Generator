import sqlite3
from PyQt6.QtWidgets import QMainWindow
from pycode.exercises.fisic.constructor_window import ExerciseWindow
from pycode.exercises.fisic.tasks_view_fisic import ConstructedTasks


db = r'C:\Users\happy\PycharmProjects\PythonProject4\resources\users_database.db'
class FisicMain(QMainWindow):
    def __init__(self, main_obj):
        super().__init__()
        self.main_obj = main_obj

    def get_ex(self, partitions_id):
        if partitions_id == 2:
            fis = ExerciseWindow(self.main_obj)
            fis.show()
            self.main_obj.cur_sub = fis
        with sqlite3.connect(db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT generation_parametrs FROM Partitions WHERE id = '{partitions_id}'",
            )
            params = cursor.fetchone()[0]
            if params:
                task_obj = ConstructedTasks(params)

                self.main_obj.second_ui = task_obj
                self.main_obj.generator.layout().addWidget(self.main_obj.second_ui)

