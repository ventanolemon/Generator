import win32com.client as win32

from pycode.exercises.matan.diff.just_diff import get_just_diff
from pycode.exercises.matan.diff.kasat import get_tangent_line
from pycode.exercises.matan.diff.ln_diff import get_ln_diff
from pycode.exercises.matan.diff.ln_secret_diff import get_ln_secret_diff
from pycode.exercises.matan.diff.lopital_law import get_lopital_law
from pycode.exercises.matan.diff.neyawn_diff import get_neyawn_diff

import shutil
import win32com


# try:
#     # Получить путь к gen_py
#     gen_path = win32com.__gen_path__
#     shutil.rmtree(gen_path)
#     print(f"Кэш очищен: {gen_path}")
# except Exception as e:
#     print(f"Ошибка: {e}")

def insert_formula(selection, formula):
    selection.OMaths.Add(selection.Range)
    selection.TypeText(formula)
    selection.OMaths.BuildUp()
    # selection.TypeText("\r\n")


def insert_editable_latex(answers="show", variants_cnt=1):
    word = win32.gencache.EnsureDispatch('Word.Application')
    word.Visible = True
    doc = word.Documents.Add()
    selection = word.Selection

    for variant_ind in range(variants_cnt):
        selection.TypeText(f"Вариант: {variant_ind + 1}\n")
        tasks_conditions = [("text", " 1.\tВычислить производную функции\n"),
                            ("text", " 2.\tВычислить производную функции, используя логарифмическую производную\n"),
                            ("text", " 3.\tВычислить производную функции\n"),
                            ("text", " 4.\tВычислить производную неявно заданной функции\n"),
                            ("text", " 6.\tНаписать уравнение касательной к графику функции\n"),
                            ("text", " 7.\tВычислить предел с помощью правила Лопиталя\n")
                            ]

        tasks_text, tasks_answers = [], []
        for task in [get_just_diff(), get_ln_diff(), get_ln_secret_diff(), get_neyawn_diff(), get_tangent_line(), get_lopital_law()]:
            tasks_text.append(task[0])
            tasks_answers.append(task[1])

        if answers == "show":
            res_text = list(zip(tasks_conditions, tasks_text, tasks_answers))
        elif answers == "show_after":
            res_text = list(zip(tasks_conditions, tasks_text)) + tasks_answers
        elif answers == "hide":
            res_text = list(zip(tasks_conditions, tasks_text))
        else:
            res_text = ["PROBLEM"]

        for task_id in range(len(res_text)):
            task = res_text[task_id]
            # selection.TypeText(f"Задание номер: {task_id + 1}\n")
            for string_id in range(parts_cnt := len(task)):
                string = task[string_id]
                if answers == "show" and string_id == parts_cnt - 1:
                    selection.TypeText(f"Ответ: ")

                if string[0] == "text":
                    selection.TypeText(string[1])
                else:
                    insert_formula(selection, string[1].replace(r"\\", '\\'))

                selection.TypeText("\n")

    return word, doc


insert_editable_latex(variants_cnt=15)

# if answers == "show":
#     pass
# elif answers == "show_after":
#     tasks, answers = [], []
#     for item in tasks_text_answers:
#         tasks.append(item[0])
#         answers.append(item[1])
#     tasks_text_answers.extend(tasks)
#     tasks_text_answers.extend(answers)
# elif answers == "show_after":
#     tasks_text_answers = [item[0] for item in tasks_text_answers]

# formulas = [
#     r"\sqrt[3]{x_0^{\infty}} \cdot \frac{1}{2}x^2",
#     r"\lim_{x \to 0} {\frac{\sin x}{x}} = 1",
#     r"C(1 - \cos{\left(\tan{\left(x^{2} \right)} \right)})"]
#

