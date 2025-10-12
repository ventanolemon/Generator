import random
import math
import json


def generate_fisic_task(task_config: str):
    # Извлекаем данные из конфигурации
    task_config = json.loads(task_config)
    condition_template = task_config['condition']
    result_letter = task_config['result_letter']
    formula = task_config['formula']
    dimension = task_config['dimension']
    variables = task_config['variables']

    # Максимальное количество попыток генерации
    max_attempts = 100
    attempt = 0

    while attempt < max_attempts:
        attempt += 1

        # Генерируем случайные значения для переменных
        generated_values = {}
        valid_generation = True

        for var_name, var_config in variables.items():
            min_val = var_config['min']
            max_val = var_config['max']
            forbidden = var_config.get('forbidden', [])

            # Определяем тип генерации на основе диапазона
            value = generate_smart_value(min_val, max_val, forbidden)

            if value is None:
                valid_generation = False
                break

            generated_values[var_name] = value

        if not valid_generation:
            continue

        # Вычисляем результат по формуле
        try:
            # Создаём локальный scope для вычислений
            local_scope = {
                **generated_values,
                'sin': math.sin,
                'cos': math.cos,
                'tan': math.tan,
                'sqrt': math.sqrt,
                'log': math.log,
                'log10': math.log10,
                'log2': math.log2,
                'exp': math.exp,
                'pi': math.pi,
                'e': math.e,
                'g': 9.81,
                'G': 6.67e-11,
                'R': 8.31,
                'k': 1.38e-23
            }

            # Безопасное вычисление формулы
            result = safe_eval_formula(formula, local_scope)

            # Проверяем на особые случаи
            if math.isinf(result) or math.isnan(result):
                continue  # Пробуем снова с другими значениями

            # Если результат слишком большой/малый, но не бесконечность - принимаем
            break

        except (OverflowError, ValueError, ZeroDivisionError):
            continue  # Пробуем снова с другими значениями

    if attempt >= max_attempts:
        raise ValueError("Не удалось сгенерировать задание с допустимыми значениями переменных")

    # Форматируем результат
    def format_result(value):
        if math.isinf(value):
            return "∞" if value > 0 else "-∞"
        elif math.isnan(value):
            return "неопределено"
        elif value == 0:
            return "0"
        else:
            abs_value = abs(value)
            try:
                if abs_value >= 1e6 or (abs_value < 1e-6 and abs_value > 1e-100):
                    # Научная нотация для очень больших/малых чисел
                    exponent = math.floor(math.log10(abs_value))
                    coefficient = value / (10 ** exponent)
                    # Стараемся показать коэффициент как целое число, если возможно
                    if abs(coefficient - round(coefficient)) < 1e-10:
                        return f"{int(round(coefficient))}×10^{exponent}"
                    else:
                        return f"{coefficient:.2f}×10^{exponent}"
                elif abs_value >= 1000 or (abs_value < 0.001 and abs_value > 1e-15):
                    # Научная нотация с меньшей точностью
                    exponent = math.floor(math.log10(abs_value))
                    coefficient = value / (10 ** exponent)
                    if abs(coefficient - round(coefficient)) < 1e-10:
                        return f"{int(round(coefficient))}×10^{exponent}"
                    else:
                        return f"{coefficient:.2f}×10^{exponent}"
                else:
                    # Обычная запись, стараемся показывать целые числа
                    if abs(value - round(value)) < 1e-10:
                        return str(int(round(value)))
                    else:
                        return f"{value:.4f}".rstrip('0').rstrip('.')
            except (OverflowError, ValueError):
                # Резервное форматирование
                return f"{value:.2e}"

    formatted_result = format_result(result)

    # Форматируем значения переменных для вывода
    def format_variable_value(value):
        abs_val = abs(value)
        if abs_val >= 1e3 or (abs_val < 1e-3 and abs_val > 0):
            try:
                exponent = math.floor(math.log10(abs_val))
                coefficient = value / (10 ** exponent)
                # Стараемся показать коэффициент как целое число
                if abs(coefficient - round(coefficient)) < 1e-10:
                    return f"{int(round(coefficient))}×10^{{{exponent}}}"
                else:
                    return f"{coefficient:.2f}×10^{{{exponent}}}"
            except (OverflowError, ValueError):
                return f"{value:.2e}"
        else:
            # Для обычных чисел стараемся показывать как целые, если возможно
            if abs(value - round(value)) < 1e-10:
                return str(int(round(value)))
            else:
                return f"{value:.4f}".rstrip('0').rstrip('.')

    # Формируем условие задачи
    condition = condition_template
    for var_name, value in generated_values.items():
        dim = variables[var_name]["dimension"]
        formatted_value = format_variable_value(value)
        condition = condition.replace(f'#{var_name}#', f"{formatted_value} {dim}")

    # Формируем итоговое задание
    task = {
        'условие': condition,
        'решение': f"{result_letter} = {formatted_result} {dimension}",
        'исходные_данные': generated_values,
        'формула': formula
    }

    return task["условие"], task["решение"]


def generate_smart_value(min_val, max_val, forbidden, max_attempts=50):
    """
    Умная генерация значений с приоритетом на целые числа и степенной формат
    """
    for attempt in range(max_attempts):
        # Определяем порядок величин
        try:
            min_exp = math.floor(math.log10(min_val)) if min_val > 0 else -100
            max_exp = math.floor(math.log10(max_val)) if max_val > 0 else -100
        except (ValueError, OverflowError):
            min_exp, max_exp = -100, 100

        # Если диапазон охватывает несколько порядков, используем степенной формат
        if max_exp - min_exp >= 2 and min_val > 0:
            # Генерируем в формате coefficient × 10^exponent
            # Выбираем случайную экспоненту из доступного диапазона
            exponent = random.randint(min_exp, max_exp)

            # Вычисляем границы для коэффициента
            min_coef = max(1, min_val / (10 ** exponent))
            max_coef = min(100, max_val / (10 ** exponent))

            # Если диапазон коэффициентов допустим
            if min_coef <= max_coef:
                # С высокой вероятностью генерируем целый коэффициент
                if max_coef - min_coef >= 1:
                    # Генерируем целый коэффициент в диапазоне от 1 до 100
                    int_min_coef = max(1, math.ceil(min_coef))
                    int_max_coef = min(100, math.floor(max_coef))
                    if int_min_coef <= int_max_coef:
                        coefficient = random.randint(int_min_coef, int_max_coef)
                    else:
                        coefficient = random.uniform(min_coef, max_coef)
                else:
                    # print("rrr")

                    # Генерируем дробный коэффициент
                    coefficient = random.uniform(min_coef, max_coef)

                value = coefficient * (10 ** exponent)
            else:
                # Если не получается с выбранной экспонентой, пробуем другую
                continue
        else:
            # Для узких диапазонов стараемся генерировать целые числа
            if max_val - min_val >= 1:
                # Генерируем целое число
                int_min = math.ceil(min_val)
                int_max = math.floor(max_val)
                if int_min <= int_max:
                    value = random.randint(int_min, int_max)
                else:
                    value = random.uniform(min_val, max_val)
            else:
                # Генерируем дробное число
                value = random.uniform(min_val, max_val)

        # Проверяем на запрещенные значения
        if value not in forbidden:
            return value

    # Если не удалось сгенерировать допустимое значение, используем обычную генерацию
    if max_val - min_val >= 1:
        int_min = math.ceil(min_val)
        int_max = math.floor(max_val)
        if int_min <= int_max:
            return random.randint(int_min, int_max)

    return random.uniform(min_val, max_val)


def safe_eval_formula(formula, local_scope):
    """
    Безопасное вычисление математических формул с обработкой больших значений
    """
    try:
        result = eval(formula, {}, local_scope)

        # Проверяем на переполнение
        if abs(result) > 1e100 and ('**' in formula or 'exp(' in formula):
            # Для формул с экспонентами пытаемся вычислить логарифм
            try:
                log_formula = f"math.log(abs({formula}))" if formula else "0"
                log_result = eval(log_formula, {}, {**local_scope, 'math': math})
                if log_result > 700:  # e^700 ~ 10^304
                    return float('inf')
                # Восстанавливаем знак
                sign = eval(f"1 if ({formula}) >= 0 else -1", {}, local_scope)
                return sign * math.exp(log_result)
            except:
                return float('inf')

        return result
    except OverflowError:
        # Для формул с экспонентами пытаемся вычислить логарифм
        try:
            log_formula = f"math.log(abs({formula}))" if formula else "0"
            log_result = eval(log_formula, {}, {**local_scope, 'math': math})
            if log_result > 700:
                return float('inf')
            # Восстанавливаем знак
            sign = eval(f"1 if ({formula}) >= 0 else -1", {}, local_scope)
            return sign * math.exp(log_result)
        except:
            raise OverflowError("Результат слишком большой для вычисления")


# Пример конфигурации для формулы мощности сигнала
config_example = '''
{
    "condition": "Дана спектральная плотность мощности шума N0 = #N0# Вт/Гц, объём канала связи V = #V# бит, полоса пропускания сигнала Δf = #Δf# Гц, время передачи T = #T# с. Найдите мощность сигнала Pc.",
    "result_letter": "Pc",
    "formula": "N0 * Δf * (2 ** (V / (Δf * T)) - 1)",
    "dimension": "Вт",
    "variables": {
        "N0": {"min": 1e-20, "max": 1e-15, "dimension": "Вт/Гц", "forbidden": []},
        "V": {"min": 1000, "max": 10000, "dimension": "бит", "forbidden": []},
        "Δf": {"min": 1000, "max": 10000, "dimension": "Гц", "forbidden": []},
        "T": {"min": 0.1, "max": 10.0, "dimension": "с", "forbidden": []}
    }
}
'''

# Пример использования
if __name__ == "__main__":
    try:
        condition, solution = generate_fisic_task(config_example)
        print("Условие:", condition)
        print("Решение:", solution)
    except Exception as e:
        print(f"Ошибка: {e}")