import json
import sqlite3
from PyQt6.QtWidgets import QMainWindow
# from pyqtgraph.examples.parallelize import tasks
from const import db
from pycode.exercises.fisic.constructor_window import ExerciseWindow
from pycode.group_adder.group_view import ConstructedGroup
from pycode.exercises.fisic.tasks_view_fisic import ConstructedTasks
from pycode.tester.test_view import ConstructedTest


class FisicMain(QMainWindow):
    def __init__(self, main_obj):
        super().__init__()
        self.main_obj = main_obj
        self.partitions_id = None

    def get_ex(self, partitions_id):
        # print(partitions_id)
        self.partitions_id = partitions_id
        # print(self.partitions_id)
        if partitions_id == 2:  # конструктор
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
                # print(params)
                for task in params:
                    if task["constracted"] == 1:
                        gen.append(task["task_id"])
                task_obj = ConstructedGroup(gen, self.main_obj)

                self.main_obj.second_ui = task_obj
                self.main_obj.generator.layout().addWidget(self.main_obj.second_ui)
            elif constracted == 3:
                params = json.loads(params_js)
                print(params, type(params.get("data")))
                task_obj = ConstructedTest(params.get("data"), self)

                self.main_obj.second_ui = task_obj
                self.main_obj.generator.layout().addWidget(self.main_obj.second_ui)
