import win32com.client as win32

from pycode.exercises.matan.limits.breaking_points import get_breaking_points
from pycode.exercises.matan.limits.c_k_equals import get_c_k_equals
from pycode.exercises.matan.limits.drob_radicals import get_drob_radicals
from pycode.exercises.matan.limits.equals import get_equals
from pycode.exercises.matan.limits.lim_opr import get_lim_opr
from pycode.exercises.matan.limits.long_radicals import get_long_radicals
from pycode.exercises.matan.limits.simple_osn import get_simple_osn
from pycode.exercises.matan.limits.simple_stepens import get_simple_stepens
from pycode.exercises.matan.limits.second_perfect import get_2_perfect
from pycode.exercises.matan.limits.perfect_1_2 import get_1_2_perfect
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
        tasks_conditions = [("text", " 1.\tε-δ  определение предела функции, геометрическая интерпретация.\n"),
                            ("text", " 2.\tВычислить предел последовательности.\n"),
                            ("text", " 3.\tВычислить предел функции.\n"),
                            ("text", " 4.\tВычислить предел функции.\n"),
                            ("text", " 5.\tВычислить предел функции.\n"),
                            ("text", " 6.\tВычислить предел функции.\n"),
                            ("text", " 7.\tВычислить предел функции.\n"),
                            ("text", " 8.\tОпределить C и  k, при которых функции эквивалентны при x → 0. \n"),
                            ("text", " 9.\tНайти точки разрыва функции y=f(x) и определить их тип. \n"),
                            # ("text", " 10.\tВычислить предел функции.\n")
                            ]
        tasks_text, tasks_answers = [], []
        for task in [get_lim_opr(), get_simple_osn(), get_simple_stepens(), get_drob_radicals(), get_long_radicals(),
                     get_2_perfect(), get_equals(), get_c_k_equals(), get_breaking_points(), get_1_2_perfect()]:
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

