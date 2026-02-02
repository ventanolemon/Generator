import win32com.client as win32

from pycode.exercises.matan.diff.just_diff import get_just_diff
from pycode.exercises.matan.diff.kasat import get_tangent_line
from pycode.exercises.matan.diff.ln_diff import get_ln_diff
from pycode.exercises.matan.diff.ln_secret_diff import get_ln_secret_diff
from pycode.exercises.matan.diff.lopital_law import get_lopital_law
from pycode.exercises.matan.diff.neyawn_diff import get_neyawn_diff
from pycode.exercises.matan.diff.parametric_task import get_parametric_task



from pycode.exercises.matan.diff.teylor import get_taylor_limit_task

# import shutil
# import win32com
#
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

def insert_editable_latex(answers="show", variants_cnt=1):
    word = win32.gencache.EnsureDispatch('Word.Application')
    word.Visible = True
    doc = word.Documents.Add()
    selection = word.Selection

    # Список генераторов задач (они возвращают: (text_desc, latex_condition, latex_answer))
    task_generators = [
        get_just_diff,
        get_ln_diff,
        get_ln_secret_diff,
        get_neyawn_diff,
        get_parametric_task,
        get_tangent_line,
        get_lopital_law,
        get_taylor_limit_task
    ]

    for variant_ind in range(variants_cnt):
        selection.TypeText(f"Вариант: {variant_ind + 1}\n")

        tasks_data = []
        for gen in task_generators:
            # Получаем: (desc_tuple, cond_tuple, ans_tuple)
            desc, cond, ans = gen()  # теперь gen() возвращает 3 элемента
            tasks_data.append((desc, cond, ans))

        if answers == "show":
            # (desc, cond, ans) — выводим всё
            res_tasks = [(desc, cond, ans) for desc, cond, ans in tasks_data]
        elif answers == "show_after":
            # Сначала все задания (desc + cond), потом блок ответов
            tasks_only = [(desc, cond) for desc, cond, _ in tasks_data]
            answers_only = [ans for _, _, ans in tasks_data]
            res_tasks = tasks_only + answers_only
        elif answers == "hide":
            # Только описание и условие
            res_tasks = [(desc, cond) for desc, cond, _ in tasks_data]
        else:
            res_tasks = [("text", "Ошибка: неверный режим ответов")]

        # Вывод задач
        for i, task in enumerate(res_tasks, start=1):
            # selection.TypeText(f"{i}.\t")

            # Определяем тип элемента: кортеж или просто ответ (если show_after)
            if isinstance(task, tuple):
                parts = task if isinstance(task[0], tuple) else [task]
                # Но по логике — task — это либо (desc, cond), либо (desc, cond, ans), либо только ans (в show_after)
                # Поэтому делаем универсальную обработку:
                if len(task) == 3:
                    desc, cond, ans = task
                    _insert_part(selection, desc)
                    _insert_part(selection, cond)
                    selection.TypeText("Ответ: ")
                    _insert_part(selection, ans)
                elif len(task) == 2:
                    desc, cond = task
                    _insert_part(selection, desc)
                    _insert_part(selection, cond)
                else:
                    # один элемент — например, только ответ в show_after
                    _insert_part(selection, task)
            else:
                # fallback: непонятный элемент — выводим как текст
                selection.TypeText(str(task))

            selection.TypeText("\n")

    return word, doc


def _insert_part(selection, part):
    """Вспомогательная функция для вставки части: текст или формула."""
    typ, content = part
    if typ == "text":
        selection.TypeText(content)
    elif typ == "formula":
        insert_formula(selection, content)
        selection.TypeText("\n")
    # можно добавить поддержку "inline_latex" и т.п., если нужно
# system_latex = r"\cases{3 \sin(2 t) - 1 - 3 e^{-2 t} & @ -3 t^{2} - 3 \sin(2 t) - 1 & }"
# insert_formula(selection, system_latex)

insert_editable_latex(variants_cnt=15)
