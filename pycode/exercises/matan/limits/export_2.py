import win32com.client as win32

from pycode.exercises.matan.limits.breaking_points import get_breaking_points
from pycode.exercises.matan.limits.c_k_equals import get_c_k_equals
from pycode.exercises.matan.limits.drob_radicals import get_drob_radicals
from pycode.exercises.matan.limits.equals import get_equals
from pycode.exercises.matan.limits.lim_opr import get_lim_opr
from pycode.exercises.matan.limits.long_radicals import get_long_radicals
from pycode.exercises.matan.limits.simple_osn import get_simple_osn
from pycode.exercises.matan.limits.simple_stepens_radicals import get_simple_stepens
from pycode.exercises.matan.limits.second_perfect import get_2_perfect

import time
from functools import wraps


def timer(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        execution_time = end_time - start_time
        print(f"Функция {func.__name__} выполнилась за {execution_time:.4f} секунд")
        return result
    return wrapper


def insert_formula(selection, formula):
    # print(formula)
    selection.OMaths.Add(selection.Range)
    selection.TypeText(formula)
    selection.OMaths.BuildUp()


@timer
def generate_variants(variants_cnt):
    """Генерирует все варианты заданий и ответов"""
    all_variants = []

    tasks_conditions = [
        ("text", " 1.\tε-δ определение предела функции, геометрическая интерпретация.\n"),
        ("text", " 2.\tВычислить предел последовательности.\n"),
        ("text", " 3.\tВычислить предел функции.\n"),
        ("text", " 4.\tВычислить предел функции.\n"),
        ("text", " 5.\tВычислить предел функции.\n"),
        ("text", " 6.\tВычислить предел функции.\n"),
        ("text", " 7.\tВычислить предел функции.\n"),
        ("text", " 8.\tОпределить C и  k, при которых функции эквивалентны при x → 0. \n"),
        ("text", " 9.\tНайти точки разрыва функции y=f(x) и определить их тип. \n")
    ]

    for variant_ind in range(variants_cnt):
        tasks_text, tasks_answers = [], []

        # Генерируем задания для текущего варианта
        for task in [get_lim_opr(), get_simple_osn(), get_simple_stepens(),
                     get_drob_radicals(), get_long_radicals(), get_2_perfect(),
                     get_equals(), get_c_k_equals(), get_breaking_points()]:
            tasks_text.append(task[0])
            tasks_answers.append(task[1])
        # print(tasks_text)

        # Сохраняем вариант с условиями, заданиями и ответами
        variant_data = {
            'conditions': tasks_conditions,
            'texts': tasks_text,
            'answers': tasks_answers,
            'variant_number': variant_ind + 1
        }
        all_variants.append(variant_data)
    print()
    return all_variants


@timer
def create_document(variants_data, show_answers=True):
    """Создает документ Word с вариантами заданий"""
    word = win32.gencache.EnsureDispatch('Word.Application')
    word.Visible = True
    doc = word.Documents.Add()
    selection = word.Selection

    for variant in variants_data:
        selection.TypeText(f"Вариант: {variant['variant_number']}\n")

        for i in range(len(variant['conditions'])):
            # Вставляем условие задачи
            condition = variant['conditions'][i]
            if condition[0] == "text":
                selection.TypeText(condition[1])
            else:
                insert_formula(selection, condition[1].replace(r"\\", '\\'))

            # Вставляем текст задания
            task_text = variant['texts'][i]
            if task_text[0] == "text":
                selection.TypeText(task_text[1])
            else:
                insert_formula(selection, task_text[1].replace(r"\\", '\\'))

            # Вставляем ответ, если нужно
            if show_answers:
                selection.TypeText("\nОтвет: ")
                answer = variant['answers'][i]
                if answer[0] == "text":
                    selection.TypeText(answer[1])
                else:
                    insert_formula(selection, answer[1].replace(r"\\", '\\'))
                selection.TypeText("\n")

            selection.TypeText("\n")

        selection.TypeText("\n")

    return word, doc


def main():
    # Генерируем все варианты
    variants_cnt = 15
    all_variants = generate_variants(variants_cnt)
    # print(all_variants)

    # Создаем документ с ответами
    word_with_answers, doc_with_answers = create_document(all_variants, show_answers=True)

    # Создаем документ без ответов
    word_without_answers, doc_without_answers = create_document(all_variants, show_answers=False)

    # Можно сохранить документы, если нужно:
    # doc_with_answers.SaveAs("Задания_с_ответами.docx")
    # doc_without_answers.SaveAs("Задания_без_ответов.docx")


if __name__ == "__main__":
    main()