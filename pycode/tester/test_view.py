import json
import random
import sqlite3

from PyQt6 import uic
from PyQt6.QtWidgets import QWidget
from PyQt6.QtWidgets import QMessageBox

from pycode.exercises.fisic.fisic_generater import generate_fisic_task
from const import db
from pycode.exporter.export_current.export_current import ExportDialog
from pycode.exporter.export_new.export_new import ExportNewDialog
from pycode.tester.test_adder import TestAdder


class ConstructedTest(QWidget):
    def __init__(self, generation_data: list, pra_obj=None):
        super().__init__()
        uic.loadUi('pycode/tester/test_generated_interface.ui', self)

        self.pra_obj = pra_obj
        self.editer = TestAdder(subject_id=self.pra_obj.main_obj.subject_id, main_obj=self.pra_obj.main_obj)

        self.cur_test_text = None
        self.cur_answer = None

        # Сохраняем список настроек генерации
        self.partitions_ids = [i.get("task_id") for i in generation_data]  # список ID разделов
        generation_settings_list = []
        with sqlite3.connect(db) as conn:
            cursor = conn.cursor()
            for partitions_id in self.partitions_ids:
                cursor.execute(
                    f"SELECT generation_parametrs FROM Partitions WHERE id = '{partitions_id}'",
                )
                generation_settings_list.append(cursor.fetchone()[0])
        self.generation_settings_list = list(zip(generation_data, generation_settings_list))  # список настроек

        # Проверка корректности входных данных
        if not self.partitions_ids or not self.generation_settings_list:
            raise ValueError("Список разделов и настроек не может быть пустым")

        # Подключение сигналов
        self.generateButton.clicked.connect(self.generate_test)
        # self.exportButton.clicked.connect(self.export_tasks)
        self.editButton.clicked.connect(self.edit)

        self.answer_popup = QMessageBox(self)
        self.answer_popup.setWindowTitle("Правильный ответ")
        self.answer_popup.setStandardButtons(QMessageBox.StandardButton.Ok)

        self.exportButton.clicked.connect(self.show_export_dialog)
        self.exportNewButton.clicked.connect(self.show_export_new_dialog)

    def show_export_dialog(self):
        # Получаем текущие данные
        test_text = self.cur_test_text
        answers = self.cur_answer  # Нужно реализовать метод получения ответов
        test_name = self.pra_obj.main_obj.partition_name  # Замените на реальное название теста
        current_answer_setting = self.selectAnswers.currentText()

        # Создаем и показываем диалог
        dialog = ExportDialog(
            test_text=test_text,
            answers=answers,
            test_name=test_name,
            answer_visibility=current_answer_setting,
            parent=self
        )
        dialog.show()

    def show_export_new_dialog(self):
        # Получаем текущие данные
        test_name = self.pra_obj.main_obj.partition_name
        current_answer_setting = self.selectAnswers.currentText()

        # Создаем и показываем диалог
        dialog = ExportNewDialog(
            test_name=test_name,
            answer_visibility=current_answer_setting,
            parent=self
        )
        dialog.show()

    def edit(self):
        self.editer.edit_test()

    def get_test(self):
        """Генерация заданий для всех настроек в списке"""
        if not self.generation_settings_list:
            QMessageBox.warning(self, "Ошибка", "Нет доступных настроек генерации")
            return None

        all_texts = []
        all_answers = []

        try:
            # Проходим по всем настройкам генерации
            cnt = 0
            for setting in self.generation_settings_list:

                task_id = setting[0]["task_id"]
                task_name = setting[0]["task_name"]
                tasks_count = int(setting[0]["task_cnt"])

                # Генерируем указанное количество заданий
                for _ in range(tasks_count):
                    if self.pra_obj.main_obj.pra_subject_id == 1:
                        # Логика для предмета с ID 1
                        # if task_id >= len(self.partitions_ids):
                        #     raise IndexError("Некорректный индекс задания")

                        task_text, task_answer = self.pra_obj.give_ex(
                            task_id
                        )

                    elif self.pra_obj.main_obj.pra_subject_id == 3:
                        # Логика для физики
                        if setting[1][0] == "{":
                            task_text, task_answer = generate_fisic_task(setting[1])
                        else:
                            task = random.choice(json.loads(setting[1]))
                            with sqlite3.connect(db) as con:
                                curs = con.cursor()
                                curs.execute(f"SELECT generation_parametrs FROM Partitions WHERE id = {task.get("task_id")}")
                                usl = curs.fetchone()[0]
                                task_text, task_answer = generate_fisic_task(usl)
                    else:
                        raise ValueError(f"Неизвестный ID предмета: {self.pra_obj.main_obj.pra_subject_id}")

                    # Добавляем результаты в списки
                    cnt += 1
                    all_texts.append(f"{cnt}) {task_text}")
                    all_answers.append(f"{cnt}) {task_answer}")

            return all_texts, all_answers

        except (IndexError, ValueError) as e:
            QMessageBox.critical(
                self,
                "Ошибка данных",
                f"Ошибка в настройках генерации: {str(e)}"
            )
            raise e
            return None
        # except Exception as e:
        #     QMessageBox.critical(
        #         self,
        #         "Ошибка генерации",
        #         f"Произошла непредвиденная ошибка: {str(e)}"
        #     )
        #     return None

    def generate_test(self):
        text, answer = self.get_test()

        self.cur_test_text = text
        self.cur_answer = answer

        answers_view = self.selectAnswers.currentText()
        if answers_view == "показывать рядом с заданием":
            result = [i[0] + "\n" + "Ответ: " + " ".join(i[1].split()[1:]) for i in zip(text, answer)]
            result = "\n".join(result)
        elif answers_view == "показывать в конце":
            result = "\n".join(text) + "\n" + "Ответы:" + "\n" + "\n".join(answer)
        elif answers_view == "скрыть":
            result = "\n".join(text)
        self.testBrowser.setText(result)

