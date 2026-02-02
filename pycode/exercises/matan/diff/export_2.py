import win32com.client as win32
from pycode.exercises.matan.diff.just_diff import get_just_diff
from pycode.exercises.matan.diff.kasat import get_tangent_line
from pycode.exercises.matan.diff.ln_diff import get_ln_diff
from pycode.exercises.matan.diff.ln_secret_diff import get_ln_secret_diff
from pycode.exercises.matan.diff.lopital_law import get_lopital_law
from pycode.exercises.matan.diff.neyawn_diff import get_neyawn_diff
from pycode.exercises.matan.diff.parametric_task import get_parametric_task
from pycode.exercises.matan.diff.teylor import get_taylor_limit_task


def insert_formula(selection, formula):
    """Вставляет LaTeX-формулу в текущее положение курсора в Word"""
    selection.OMaths.Add(selection.Range)
    selection.TypeText(formula)
    selection.OMaths.BuildUp()


def _insert_part(selection, part):
    """Вспомогательная функция для вставки текста или формулы"""
    typ, content = part
    if typ == "text":
        selection.TypeText(content)
    elif typ == "formula":
        insert_formula(selection, content)
        selection.TypeText("\n")


def generate_all_variants(variants_cnt=50):
    """Генерирует все варианты заданий и сохраняет их в памяти"""
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

    all_variants = []
    for variant_ind in range(variants_cnt):
        variant_tasks = []
        for gen in task_generators:
            desc, cond, ans = gen()
            variant_tasks.append((desc, cond, ans))
        all_variants.append(variant_tasks)
    return all_variants


def create_document(variants_data, include_answers, filename):
    """Создаёт Word-документ с вариантами заданий"""
    word = win32.gencache.EnsureDispatch('Word.Application')
    word.Visible = True
    doc = word.Documents.Add()
    selection = word.Selection

    for variant_index, variant_tasks in enumerate(variants_data, start=1):
        selection.TypeText(f"Вариант: {variant_index}\n")

        for task_index, (desc, cond, ans) in enumerate(variant_tasks, start=1):
            # Вставляем описание задания
            _insert_part(selection, desc)
            # Вставляем условие задания
            _insert_part(selection, cond)

            # Если нужны ответы - вставляем их
            if include_answers:
                selection.TypeText("Ответ: ")
                _insert_part(selection, ans)

            selection.TypeText("\n")  # Отступ после каждого задания

        selection.TypeText("\n")  # Дополнительный отступ между вариантами

    doc.SaveAs(filename)
    return word, doc


def main():
    # Шаг 1: Генерируем все 50 вариантов
    all_variants = generate_all_variants(50)

    # Шаг 2: Создаём документ с ответами (для преподавателя)
    teacher_word, teacher_doc = create_document(
        variants_data=all_variants,
        include_answers=True,
        filename="variants_with_answers.docx"
    )

    # Шаг 3: Создаём документ без ответов (для студентов)
    student_word, student_doc = create_document(
        variants_data=all_variants,
        include_answers=False,
        filename="variants_without_answers.docx"
    )

    print("Документы успешно созданы!")
    print("- Для преподавателя: variants_with_answers.docx")
    print("- Для студентов: variants_without_answers.docx")


if __name__ == "__main__":
    main()
