import json
import random
from math import sin, cos, tan, log


def generate_fisic_task(task_config: json):
    # Извлекаем данные из конфигурации
    task_config = json.loads(task_config)
    # print(task_config)
    condition_template = task_config['condition']
    result_letter = task_config['result_letter']
    formula = task_config['formula']
    dimension = task_config['dimension']
    variables = task_config['variables']

    # Генерируем случайные значения для переменных
    generated_values = {}
    for var_name, var_config in variables.items():
        # Генерируем случайное число в заданном диапазоне
        value = random.randint(int(var_config['min']), int(var_config['max']))

        # Проверяем на запрещённые значения
        while value in var_config['forbidden']:
            value = random.uniform(var_config['min'], var_config['max'])

        # Округляем до 2 знаков после запятой
        generated_values[var_name] = round(value, 2)

    # Вычисляем результат по формуле
    try:
        # Создаём локальный scope для вычислений
        local_scope = {**generated_values, **{
            'sin': lambda x: sin(x),
            'cos': lambda x: cos(x),
            'tan': lambda x: tan(x),
            'sqrt': lambda x: x ** 0.5,

            "g": 9.81,
            "G": 6.67 * 10 ** (-11),

            "R": 8.31,
            "k": 1.38 * 10 ** (-23)
        }}

        # Вычисляем результат
        result = eval(formula, {}, local_scope)
        result = round(result, 2)  # округляем до 2 знаков

    except Exception as e:
        raise ValueError(f"Ошибка при вычислении формулы: {str(e)}")

    # Формируем условие задачи
    condition = condition_template
    for var_name, value in generated_values.items():
        dim = variables[var_name]["dimension"]
        condition = condition.replace(f'#{var_name}#', str(value) + " " + dim)

    # Формируем итоговое задание
    task = {
        'условие': condition,
        'решение': f"{result_letter} = {result} {dimension}",
        'исходные_данные': generated_values,
        'формула': formula
    }

    return task["условие"], task["решение"]


# Пример использования
if __name__ == "__main__":
    # Пример JSON конфигурации
    task_config = {
        "condition": "#a# #m#",
        "result_letter": "F",
        "formula": "a * m",
        "dimension": "Н",
        "variables": {
            "a": {
                "min": 0.0,
                "max": 100.0,
                "forbidden": [],
                "dimension": ""
            },
            "m": {
                "min": 0.0,
                "max": 100.0,
                "forbidden": [],
                "dimension": ""
            }
        }
    }

    # Генерируем задание
    generated_task = generate_fisic_task(task_config)
    print("Сгенерированное задание:")
    print(f"Условие: {generated_task['условие']}")
    print(f"Ответ: {generated_task['решение']}")
    print(f"Исходные данные: {generated_task['исходные_данные']}")
    print(f"Используемая формула: {generated_task['формула']}")
