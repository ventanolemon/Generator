# pycode/exercises/matan/matan_main.py
import json
import sqlite3
from const import db
from PyQt6.QtWidgets import QWidget
from PyQt6.uic import loadUi

# Импорты генераторов — как у вас
from pycode.exercises.matan.diff.just_diff import get_just_diff
from pycode.exercises.matan.diff.ln_diff import get_ln_diff
from pycode.exercises.matan.diff.ln_secret_diff import get_ln_secret_diff
from pycode.exercises.matan.diff.neyawn_diff import get_neyawn_diff
from pycode.exercises.matan.diff.parametric_task import get_parametric_task
from pycode.exercises.matan.diff.kasat import get_tangent_line
from pycode.exercises.matan.diff.lopital_law import get_lopital_law
from pycode.exercises.matan.diff.teylor import get_taylor_limit_task


class MatanMain:
    def __init__(self, main_obj):
        self.main_obj = main_obj
        self.partitions_id = None
        # ID → генератор
        self._generators = {
            40: get_just_diff,
            41: get_ln_diff,
            42: get_ln_secret_diff,
            43: get_neyawn_diff,
            44: get_parametric_task,
            45: get_tangent_line,
            46: get_lopital_law,
            47: get_taylor_limit_task,
        }

    def get_ex(self, partitions_id):
        self.partitions_id = partitions_id
        task_obj = None

        # --- Простые задачи ---
        if partitions_id in self._generators:
            generator = self._generators[partitions_id]
            task_obj = MatanTaskWidget(generator)

        # --- Группы / Тесты ---
        with sqlite3.connect(db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT constracted, generation_parametrs FROM Partitions WHERE id = ?", 
                (partitions_id,)
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Partition ID {partitions_id} not found")
            constracted, params_js = row

            if constracted == 2:  # группа
                tasks_id = [obj.get("task_id") for obj in json.loads(params_js)]
                from pycode.group_adder.group_view import ConstructedGroup
                task_obj = ConstructedGroup(tasks_id, self.main_obj)

            elif constracted == 3:  # тест
                params = json.loads(params_js)
                from pycode.tester.test_view import ConstructedTest
                task_obj = ConstructedTest(params.get("data"), self.main_obj)

        if not task_obj:
            raise ValueError(f"No handler for partition_id={partitions_id}")

        # Очистка layout и добавление нового виджета
        layout = self.main_obj.generator.layout()
        while layout.count():
            child = layout.takeAt(0)
            widget = child.widget()
            if widget:
                widget.setParent(None)
                widget.deleteLater()

        layout.addWidget(task_obj)
        self.main_obj.second_ui = task_obj

    def give_ex(self, partitions_id):
        """
        Возвращает (task_repr: str, answer_repr: str) — как в LinalMain.
        Поддерживает 2- и 3-компонентные возвраты.
        """
        if partitions_id in self._generators:
            gen = self._generators[partitions_id]
            result = gen()  # может быть (desc, cond, ans) или (cond, ans)

            if len(result) == 3:
                desc, cond, ans = result
                # Собираем текст условия из desc + cond
                parts = []
                for typ, content in [desc, cond]:
                    parts.append(content if typ == "text" else f"${content}$")
                task_repr = "\n".join(parts)
                answer_repr = ans[1]  # ans = ("formula"/"text", строка)
            elif len(result) == 2:
                # fallback: предполагаем (cond, ans)
                cond, ans = result
                task_repr = cond[1]
                answer_repr = ans[1]
            else:
                raise ValueError(f"Unexpected result length {len(result)} from {gen.__name__}")

            return task_repr, answer_repr

        # Для групп и тестов — как в LinalMain
        with sqlite3.connect(db) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT constracted, generation_parametrs FROM Partitions WHERE id = ?",
                (partitions_id,)
            )
            constracted, generation_parametrs = cursor.fetchone()

            if constracted == 2:
                tasks_id = [obj.get("task_id") for obj in json.loads(generation_parametrs)]
                from pycode.group_adder.group_view import ConstructedGroup
                task_obj = ConstructedGroup(tasks_id, self.main_obj)
                return task_obj.get_task()

        raise NotImplementedError(f"give_ex for partition_id={partitions_id} not implemented")


# -------------------------------------------------------
# MatanTaskWidget — с поддержкой 3-компонентного формата
# -------------------------------------------------------
class MatanTaskWidget(QWidget):
    def __init__(self, generator):
        super().__init__()
        loadUi('resources/exercises/linal/linal2-d.ui', self)

        self.generator = generator
        self.task_text_full = ""   # для показа условия целиком
        self.answer_text = ""
        self.currently_showing_answer = False

        self.generateButton.clicked.connect(self.generate_task)
        self.answerButton.clicked.connect(self.toggle_answer)

        # Скрыто изначально
        self.taskText.hide()
        self.taskTitle.hide()
        self.answerButton.hide()

    def generate_task(self):
        res = self.generator()
        if len(res) == 3:
            desc, cond, ans = res
        elif len(res) == 2:
            # fallback: допустим (cond, ans), desc = ("text", "")
            desc = ("text", "")
            cond, ans = res
        else:
            raise ValueError(f"Unexpected result length {len(res)}")

        # Собираем условие: desc + cond
        parts = []
        for typ, content in [desc, cond]:
            if typ == "text":
                parts.append(content)
            elif typ == "formula":
                parts.append(content)  # Word принимает как есть
            # можно добавить "inline" и т.п. при необходимости

        self.task_text_full = "\n".join(parts).strip()
        self.answer_text = ans[1]
        self.currently_showing_answer = False

        # Показываем UI
        self.taskText.setText(self.task_text_full)
        self.taskText.show()
        self.taskTitle.show()
        self.answerButton.show()
        self.answerButton.setText("показать ответ")

    def toggle_answer(self):
        if self.currently_showing_answer:
            self.taskText.setText(self.task_text_full)
            self.answerButton.setText("показать ответ")
            self.currently_showing_answer = False
        else:
            self.taskText.setText(self.answer_text)
            self.answerButton.setText("показать задание")
            self.currently_showing_answer = True