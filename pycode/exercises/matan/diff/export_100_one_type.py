import shutil

import win32com
import win32com.client as win32
import os
import random

# Импорты генераторов
# from pycode.exercises.matan.diff.just_diff import get_just_diff
from pycode.exercises.matan.diff.parametric_task import get_parametric_task


# try:
#     # Получить путь к gen_py
#     gen_path = win32com.__gen_path__
#     shutil.rmtree(gen_path)
#     print(f"Кэш очищен: {gen_path}")
# except Exception as e:
#     print(f"Ошибка: {e}")
#

def insert_latex_formula(selection, latex: str):
    """Вставляет LaTeX-формулу в Word и преобразует в OMML."""
    # Word требует, чтобы формула была встроенная — создаём контейнер
    selection.OMaths.Add(selection.Range)
    selection.TypeText(latex)
    selection.OMaths.BuildUp()
    selection.TypeText("\n")


def generate_tasks(task_count=100):
    """Генерирует список из task_count заданий: [(formula_latex, answer_latex), ...]"""

    tasks = []
    for i in range(task_count):
        gen = get_parametric_task()  # случайный выбор (можно заменить на циклический)
        formula, answer = gen[0], gen[1]
        tasks.append((formula, answer))
    return tasks


def create_document(tasks, with_answers=False, filename="output.docx"):
    """Создаёт Word-документ с заданиями (и, опционально, ответами)."""
    word = win32.gencache.EnsureDispatch('Word.Application')
    doc = word.Documents.Add()
    selection = word.Selection
    # print(tasks)
    for i, (formula_latex, answer_latex) in enumerate(tasks, start=1):
        # Заголовок
        selection.TypeText(f"Задание {i}.\n")
        # Формула условия
        # print(formula_latex)
        print(formula_latex[1])
        insert_latex_formula(selection, formula_latex[1])

        # Ответ (если нужно)
        if with_answers:
            selection.TypeText("Ответ: \n")
            insert_latex_formula(selection, answer_latex[1])

        # Доп. отступ между заданиями (кроме последнего)
        if i < len(tasks):
            selection.TypeText("\n")

    # Сохраняем и закрываем
    full_path = os.path.abspath(filename)
    doc.SaveAs2(full_path)
    doc.Close()
    word.Quit()
    print(f"✅ Сохранено: {filename}")


# === ЗАПУСК ===
if __name__ == "__main__":
    TASK_COUNT = 10

    # 1️⃣ Генерируем ОДИН список заданий (чтобы в обоих файлах были одинаковые!)
    print("Генерация 100 заданий...")
    tasks = generate_tasks(TASK_COUNT)
    # print(tasks[0])
    # 2️⃣ Создаём файл без ответов
    create_document(tasks, with_answers=False, filename="Задания.docx")

    # 3️⃣ Создаём файл с ответами
    create_document(tasks, with_answers=True, filename="Задания_с_ответами.docx")

    print("Готово!")
