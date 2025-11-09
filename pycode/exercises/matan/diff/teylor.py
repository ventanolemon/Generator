import random
import sympy as sp


def get_taylor_limit_task():
    x = sp.symbols('x')

    # Шаблоны для sympy выражений
    templates_sympy = {
        2: {
            'numerator': [
                ('cos', lambda a, x: 1 - sp.cos(a * x)),
                ('ch', lambda a, x: sp.cosh(a * x) - 1),
                ('exp', lambda a, x: sp.exp(a * x) - 1 - a * x),
                ('ln', lambda a, x: sp.log(1 + a * x) - a * x)
            ],
            'denominator': [
                ('cos', lambda b, x: 1 - sp.cos(b * x)),
                ('ch', lambda b, x: sp.cosh(b * x) - 1),
                ('exp', lambda b, x: sp.exp(b * x) - 1 - b * x),
                ('ln', lambda b, x: sp.log(1 + b * x) - b * x)
            ]
        },
        3: {
            'numerator': [
                ('sin', lambda a, x: sp.sin(a * x) - a * x),
                ('sh', lambda a, x: sp.sinh(a * x) - a * x),
                ('exp', lambda a, x: sp.exp(a * x) - 1 - a * x - (a ** 2 * x ** 2) / 2),
                ('ln', lambda a, x: sp.log(1 + a * x) - a * x + (a ** 2 * x ** 2) / 2)
            ],
            'denominator': [
                ('sin', lambda b, x: sp.sin(b * x) - b * x),
                ('sh', lambda b, x: sp.sinh(b * x) - b * x),
                ('exp', lambda b, x: sp.exp(b * x) - 1 - b * x - (b ** 2 * x ** 2) / 2),
                ('ln', lambda b, x: sp.log(1 + b * x) - b * x + (b ** 2 * x ** 2) / 2)
            ]
        },
        4: {
            'numerator': [
                ('cos', lambda a, x: 1 - sp.cos(a * x) - (a ** 2 * x ** 2) / 2),
                ('ch', lambda a, x: sp.cosh(a * x) - 1 - (a ** 2 * x ** 2) / 2),
                ('exp', lambda a, x: sp.exp(a * x) - 1 - a * x - (a ** 2 * x ** 2) / 2 - (a ** 3 * x ** 3) / 6)
            ],
            'denominator': [
                ('cos', lambda b, x: 1 - sp.cos(b * x) - (b ** 2 * x ** 2) / 2),
                ('ch', lambda b, x: sp.cosh(b * x) - 1 - (b ** 2 * x ** 2) / 2),
                ('exp', lambda b, x: sp.exp(b * x) - 1 - b * x - (b ** 2 * x ** 2) / 2 - (b ** 3 * x ** 3) / 6)
            ]
        }
    }

    # LaTeX шаблоны
    templates_latex = {
        2: {
            'numerator': [
                ("cos", "1 - \\cos({a}x)"),
                ("ch", "ch({a}x) - 1"),
                ("exp", "e^{{{a}x}} - 1 - {a}x"),
                ("ln", "\\ln(1 + {a}x) - {a}x")
            ],
            'denominator': [
                ("cos", "1 - \\cos({b}x)"),
                ("ch", "ch({b}x) - 1"),
                ("exp", "e^{{{b}x}} - 1 - {b}x"),
                ("ln", "\\ln(1 + {b}x) - {b}x")
            ]
        },
        3: {
            'numerator': [
                ("sin", "\\sin({a}x) - {a}x"),
                ("sh", "sh({a}x) - {a}x"),
                ("exp", "e^{{{a}x}} - 1 - {a}x - \\frac{{({a}x)^2}}{{2}}"),
                ("ln", "\\ln(1 + {a}x) - {a}x + \\frac{{({a}x)^2}}{{2}}")
            ],
            'denominator': [
                ("sin", "\\sin({b}x) - {b}x"),
                ("sh", "sh({b}x) - {b}x"),
                ("exp", "e^{{{b}x}} - 1 - {b}x - \\frac{{({b}x)^2}}{{2}}"),
                ("ln", "\\ln(1 + {b}x) - {b}x + \\frac{{({b}x)^2}}{{2}}")
            ]
        },
        4: {
            'numerator': [
                ("cos", "1 - \\cos({a}x) - \\frac{{({a}x)^2}}{{2}}"),
                ("ch", "ch({a}x) - 1 - \\frac{{({a}x)^2}}{{2}}"),
                ("exp", "e^{{{a}x}} - 1 - {a}x - \\frac{{({a}x)^2}}{{2}} - \\frac{{({a}x)^3}}{{6}}")
            ],
            'denominator': [
                ("cos", "1 - \\cos({b}x) - \\frac{{({b}x)^2}}{{2}}"),
                ("ch", "ch({b}x) - 1 - \\frac{{({b}x)^2}}{{2}}"),
                ("exp", "e^{{{b}x}} - 1 - {b}x - \\frac{{({b}x)^2}}{{2}} - \\frac{{({b}x)^3}}{{6}}")
            ]
        }
    }

    order = random.choice([2, 3, 4])
    num_options = templates_sympy[order]['numerator']
    den_options = templates_sympy[order]['denominator']
    num_latex_options = templates_latex[order]['numerator']
    den_latex_options = templates_latex[order]['denominator']

    # Выбираем функции для числителя и знаменателя
    num_idx = random.randint(0, len(num_options) - 1)
    num_func_name, num_func = num_options[num_idx]
    num_latex_template = num_latex_options[num_idx][1]

    # Выбираем разные функции для числителя и знаменателя
    den_candidates = [i for i in range(len(den_options)) if den_options[i][0] != num_func_name]
    den_idx = random.choice(den_candidates) if den_candidates else random.randint(0, len(den_options) - 1)
    den_func_name, den_func = den_options[den_idx]
    den_latex_template = den_latex_options[den_idx][1]

    a, b = random.sample(range(1, 5), k=2)
    # b = random.randint(1, 5)

    # Генерируем LaTeX выражения
    num_latex = num_latex_template.format(a=a)
    den_latex = den_latex_template.format(b=b)

    # Генерируем sympy выражения
    num_expr = num_func(a, x)
    den_expr = den_func(b, x)

    # Вычисляем разложение Тейлора до нужного порядка
    num_series = sp.series(num_expr, x, 0, order + 1).removeO()
    den_series = sp.series(den_expr, x, 0, order + 1).removeO()

    # Находим коэффициенты при x^order
    num_coeff = sp.expand(num_series).coeff(x, order)
    den_coeff = sp.expand(den_series).coeff(x, order)

    # Вычисляем предел
    limit_value = sp.simplify(num_coeff / den_coeff)

    # Формируем LaTeX для задания и ответа
    limit_expr_latex = r"\lim_{x \to 0} {\frac{" + num_latex + r"}{" + den_latex + r"}}"
    task = ("formula", limit_expr_latex)
    answer = ("formula", sp.latex(limit_value))

    return task, answer


# Пример использования
if __name__ == "__main__":
    task, answer = get_taylor_limit_task()
    print(task)
    print(answer)