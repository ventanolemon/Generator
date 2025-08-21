import json
import sqlite3
from PyQt6.QtWidgets import QMainWindow
from pycode.exercises.fisic.constructor_window import ExerciseWindow
from pycode.exercises.fisic.group_view_fisic import ConstructedGroup
from pycode.exercises.fisic.tasks_view_fisic import ConstructedTasks


db = r'C:\Users\happy\PycharmProjects\PythonProject4\resources\users_database.db'
class FisicMain(QMainWindow):
    def __init__(self, main_obj):
        super().__init__()
        self.main_obj = main_obj
        self.partitions_id = None

    def get_ex(self, partitions_id):
        # print(partitions_id)
        self.partitions_id = partitions_id
        # print(self.partitions_id)
        if partitions_id == 2:
            fis = ExerciseWindow(self.main_obj)
            fis.show()
            self.main_obj.cur_sub = fis
        with sqlite3.connect(db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT constracted, generation_parametrs FROM Partitions WHERE id = '{partitions_id}'",
            )
            constracted, params_js = cursor.fetchone()
            if constracted == 1:
                task_obj = ConstructedTasks(partitions_id, params_js, self)

                self.main_obj.second_ui = task_obj
                self.main_obj.generator.layout().addWidget(self.main_obj.second_ui)
            elif constracted == 2:
                params = json.loads(params_js)
                gen = []
                for task in params:
                    if task["constracted"] == 1:
                        gen.append((task["task_id"], task["params"]))
                task_obj = ConstructedGroup([i[0] for i in gen], [i[1] for i in gen], self)

                self.main_obj.second_ui = task_obj
                self.main_obj.generator.layout().addWidget(self.main_obj.second_ui)

