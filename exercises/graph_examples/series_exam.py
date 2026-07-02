"""
Контрольная работа по рядам — 8 генераторов на граф-языке.

Прототип — «Вариант №0» (сходимость числовых рядов → знакочередующиеся →
степенные → равномерная сходимость → Тейлор). Алгоритмы генерации описаны в
docs/series_exam_algorithms.md; общий приём — ответ вычисляется из СТРУКТУРЫ
случайных параметров (показатели p-рядов, предел Даламбера, радиус как
расстояние до полюса), а sympy используется для точной печати (дроби, знак
суммы, apart).

SERIES_EXAM: имя → {title, note, graph}; generate_variant(seed) исполняет все
восемь графов с согласованными сидами и возвращает готовый вариант.
"""

from __future__ import annotations


# ---------- №1. Сравнение с p-рядом (случайная ветка: сходится/расходится) ----
_S1_COMPARISON = {
    "nodes": [
        {"id": "d", "type": "random_natural", "params": {"min": 0, "max": 1}},
        {"id": "a", "type": "random_natural", "params": {"min": 2, "max": 7}},
        {"id": "b", "type": "random_natural", "params": {"min": 2, "max": 7}},
        {"id": "e", "type": "random_natural", "params": {"min": 1, "max": 3}},
        {"id": "f", "type": "random_natural", "params": {"min": 1, "max": 3}},
        {"id": "p", "type": "random_natural", "params": {"min": 2, "max": 5}},
        {"id": "vd", "type": "var_dict",
         "params": {"names": ["a", "b", "e", "f", "p"]}},
        # Две структуры условия — разные паттерны решения.
        {"id": "conv", "type": "expr_const",
         "params": {"expr": "((a*n**2 + e)/(b*n**3 + f))**p * atan(1/sqrt(n))",
                    "vars": ["a", "b", "e", "f", "p", "n"]}},
        {"id": "div", "type": "expr_const",
         "params": {"expr": "((a*n + e)/(b*n + f))**p * atan(1/sqrt(n))",
                    "vars": ["a", "b", "e", "f", "p", "n"]}},
        {"id": "isconv", "type": "compare", "params": {"op": "==", "b": 1}},
        {"id": "term", "type": "select", "params": {"value_type": "expr"}},
        {"id": "nsym", "type": "symbol", "params": {"name": "n"}},
        {"id": "disp", "type": "sum_display",
         "params": {"lower": "1", "upper": "oo"}},
        {"id": "intro", "type": "text",
         "params": {"text": "Исследовать на сходимость:"}},
        {"id": "fb", "type": "expr_block"},
        {"id": "stmt", "type": "block_list", "params": {"count": 2}},
        {"id": "s", "type": "formula", "params": {"expr": "p + 0.5"}},
        {"id": "ansC", "type": "text", "params": {"text":
            "Сходится: aₙ ~ C·n^(−#s#) (дробь ~ C·n^(−p), arctg(1/√n) ~ "
            "n^(−1/2)); сравнение с p-рядом, s = #s# > 1."}},
        {"id": "ansD", "type": "text", "params": {"text":
            "Расходится: дробь стремится к C ≠ 0, поэтому aₙ ~ C·arctg(1/√n) "
            "~ C·n^(−1/2); p-ряд с s = 1/2 ≤ 1."}},
        {"id": "ans", "type": "select", "params": {"value_type": "block"}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "a:out", "to": "vd:a"}, {"from": "b:out", "to": "vd:b"},
        {"from": "e:out", "to": "vd:e"}, {"from": "f:out", "to": "vd:f"},
        {"from": "p:out", "to": "vd:p"},
        {"from": "vd:out", "to": "conv:values"},
        {"from": "vd:out", "to": "div:values"},
        {"from": "d:out", "to": "isconv:a"},
        {"from": "isconv:out", "to": "term:cond"},
        {"from": "conv:out", "to": "term:on_true"},
        {"from": "div:out", "to": "term:on_false"},
        {"from": "term:out", "to": "disp:term"},
        {"from": "nsym:out", "to": "disp:index"},
        {"from": "disp:out", "to": "fb:in"},
        {"from": "intro:out", "to": "stmt:in0"}, {"from": "fb:out", "to": "stmt:in1"},
        {"from": "p:out", "to": "s:p"},
        {"from": "s:out", "to": "ansC:s"},
        {"from": "isconv:out", "to": "ans:cond"},
        {"from": "ansC:out", "to": "ans:on_true"},
        {"from": "ansD:out", "to": "ans:on_false"},
        {"from": "stmt:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 11, "max_attempts": 100},
}


# ---------- №2. Признак Даламбера (факториалы) ----------
_S2_DALAMBERT = {
    "nodes": [
        {"id": "c", "type": "random_natural", "params": {"min": 2, "max": 3}},
        {"id": "a", "type": "random_natural", "params": {"min": 2, "max": 9}},
        {"id": "b", "type": "random_natural", "params": {"min": 1, "max": 2}},
        {"id": "vd", "type": "var_dict", "params": {"names": ["a", "b", "c"]}},
        {"id": "term", "type": "expr_const",
         "params": {"expr": "a**(b*n) * factorial(n)**c / factorial(c*n)",
                    "vars": ["a", "b", "c", "n"]}},
        # Предел Даламбера в замкнутой форме: L = a^b / c^c. Имена u/v/w,
        # потому что 'c' в узле formula — физическая константа (скорость света).
        {"id": "L", "type": "formula", "params": {"expr": "u^v / w^w"}},
        {"id": "Lx", "type": "expr_const",
         "params": {"expr": "a**b / c**c", "vars": ["a", "b", "c"]}},
        {"id": "eq1", "type": "compare", "params": {"op": "==", "b": 1}},
        {"id": "g", "type": "guard", "params": {"mode": "require_false"}},
        {"id": "verd", "type": "compare", "params": {"op": "<", "b": 1}},
        {"id": "nsym", "type": "symbol", "params": {"name": "n"}},
        {"id": "disp", "type": "sum_display",
         "params": {"lower": "1", "upper": "oo"}},
        {"id": "intro", "type": "text",
         "params": {"text": "Исследовать на сходимость:"}},
        {"id": "fb", "type": "expr_block"},
        {"id": "stmt", "type": "block_list", "params": {"count": 2}},
        {"id": "ansC", "type": "text", "params": {"text":
            "Сходится (признак Даламбера): lim aₙ₊₁/aₙ = #L# < 1."}},
        {"id": "ansD", "type": "text", "params": {"text":
            "Расходится (признак Даламбера): lim aₙ₊₁/aₙ = #L# > 1."}},
        {"id": "ans", "type": "select", "params": {"value_type": "block"}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "a:out", "to": "vd:a"}, {"from": "b:out", "to": "vd:b"},
        {"from": "c:out", "to": "vd:c"},
        {"from": "vd:out", "to": "term:values"},
        {"from": "vd:out", "to": "Lx:values"},
        {"from": "a:out", "to": "L:u"}, {"from": "b:out", "to": "L:v"},
        {"from": "c:out", "to": "L:w"},
        {"from": "L:out", "to": "eq1:a"},
        {"from": "eq1:out", "to": "g:cond"},
        {"from": "L:out", "to": "g:value"},
        {"from": "g:out", "to": "verd:a"},
        {"from": "term:out", "to": "disp:term"},
        {"from": "nsym:out", "to": "disp:index"},
        {"from": "disp:out", "to": "fb:in"},
        {"from": "intro:out", "to": "stmt:in0"}, {"from": "fb:out", "to": "stmt:in1"},
        {"from": "Lx:out", "to": "ansC:L"}, {"from": "Lx:out", "to": "ansD:L"},
        {"from": "verd:out", "to": "ans:cond"},
        {"from": "ansC:out", "to": "ans:on_true"},
        {"from": "ansD:out", "to": "ans:on_false"},
        {"from": "stmt:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 12, "max_attempts": 200},
}


# ---------- №3. Абсолютная/условная сходимость (категория разыгрывается) -----
_S3_LEIBNIZ = {
    "nodes": [
        {"id": "k", "type": "random_natural", "params": {"min": 0, "max": 2}},
        {"id": "p", "type": "random_natural", "params": {"min": 1, "max": 3}},
        {"id": "cc", "type": "random_natural", "params": {"min": 1, "max": 6}},
        # Категория ответа выбрана первой; q подбирается под неё: s = q−p = 2−k.
        {"id": "q", "type": "formula", "params": {"expr": "p + 2 - k"}},
        {"id": "vd", "type": "var_dict", "params": {"names": ["p", "q", "c"]}},
        {"id": "term", "type": "expr_const",
         "params": {"expr": "(-1)**(n+1) * n**p / (n**q + c)",
                    "vars": ["p", "q", "c", "n"]}},
        {"id": "k0", "type": "compare", "params": {"op": "==", "b": 0}},
        {"id": "k1", "type": "compare", "params": {"op": "==", "b": 1}},
        {"id": "nsym", "type": "symbol", "params": {"name": "n"}},
        {"id": "disp", "type": "sum_display",
         "params": {"lower": "1", "upper": "oo"}},
        {"id": "intro", "type": "text", "params":
            {"text": "Исследовать на абсолютную и условную сходимость:"}},
        {"id": "fb", "type": "expr_block"},
        {"id": "stmt", "type": "block_list", "params": {"count": 2}},
        {"id": "ansAbs", "type": "text", "params": {"text":
            "Сходится абсолютно: |aₙ| ~ n^(−2) — p-ряд с s = 2 > 1."}},
        {"id": "ansCond", "type": "text", "params": {"text":
            "Сходится условно: по Лейбницу (|aₙ| ↓ 0), но |aₙ| ~ 1/n — ряд "
            "из модулей расходится."}},
        {"id": "ansDiv", "type": "text", "params": {"text":
            "Расходится: aₙ ↛ 0 — нарушено необходимое условие сходимости."}},
        {"id": "sel1", "type": "select", "params": {"value_type": "block"}},
        {"id": "ans", "type": "select", "params": {"value_type": "block"}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "p:out", "to": "q:p"}, {"from": "k:out", "to": "q:k"},
        {"from": "p:out", "to": "vd:p"}, {"from": "q:out", "to": "vd:q"},
        {"from": "cc:out", "to": "vd:c"},
        {"from": "vd:out", "to": "term:values"},
        {"from": "k:out", "to": "k0:a"}, {"from": "k:out", "to": "k1:a"},
        {"from": "term:out", "to": "disp:term"},
        {"from": "nsym:out", "to": "disp:index"},
        {"from": "disp:out", "to": "fb:in"},
        {"from": "intro:out", "to": "stmt:in0"}, {"from": "fb:out", "to": "stmt:in1"},
        {"from": "k1:out", "to": "sel1:cond"},
        {"from": "ansCond:out", "to": "sel1:on_true"},
        {"from": "ansDiv:out", "to": "sel1:on_false"},
        {"from": "k0:out", "to": "ans:cond"},
        {"from": "ansAbs:out", "to": "ans:on_true"},
        {"from": "sel1:out", "to": "ans:on_false"},
        {"from": "stmt:out", "to": "task:statement"},
        {"from": "ans:out", "to": "task:answer"},
    ],
    "meta": {"seed": 13, "max_attempts": 100},
}


# ---------- №4. Степенной ряд: радиус, интервал, концы, равномерная ----------
_S4_POWER = {
    "nodes": [
        {"id": "R", "type": "random_natural", "params": {"min": 1, "max": 3}},
        {"id": "x0", "type": "random_natural", "params": {"min": 0, "max": 3}},
        {"id": "a", "type": "random_natural", "params": {"min": 1, "max": 4}},
        {"id": "b", "type": "random_natural", "params": {"min": 1, "max": 3}},
        {"id": "vd", "type": "var_dict",
         "params": {"names": ["a", "b", "R", "x0"]}},
        {"id": "term", "type": "expr_const",
         "params": {"expr": "(-1)**n * (x - x0)**n / ((a*n + b) * R**n)",
                    "vars": ["a", "b", "R", "x0", "x", "n"]}},
        {"id": "lo", "type": "formula", "params": {"expr": "x0 - R"}},
        {"id": "hi", "type": "formula", "params": {"expr": "x0 + R"}},
        {"id": "nsym", "type": "symbol", "params": {"name": "n"}},
        {"id": "disp", "type": "sum_display",
         "params": {"lower": "1", "upper": "oo"}},
        {"id": "intro", "type": "text", "params": {"text":
            "Найти радиус и интервал сходимости степенного ряда. Исследовать "
            "сходимость на концах интервала. Указать область равномерной "
            "сходимости."}},
        {"id": "fb", "type": "expr_block"},
        {"id": "stmt", "type": "block_list", "params": {"count": 2}},
        {"id": "ans", "type": "text", "params": {"text":
            "R = #R# (Даламбер: |cₙ/cₙ₊₁| → #R#). Интервал сходимости: "
            "(#lo#; #hi#]. При x = #hi#: Σ(−1)ⁿ/(#a#n+#b#) — сходится условно "
            "(Лейбниц). При x = #lo#: Σ1/(#a#n+#b#) — расходится (сравнение с "
            "гармоническим). Равномерная сходимость: на любом отрезке "
            "[c; #hi#], c > #lo# (теорема Абеля); на всём интервале — нет."}},
        {"id": "ansb", "type": "to_block", "params": {"relation": ""}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "a:out", "to": "vd:a"}, {"from": "b:out", "to": "vd:b"},
        {"from": "R:out", "to": "vd:R"}, {"from": "x0:out", "to": "vd:x0"},
        {"from": "vd:out", "to": "term:values"},
        {"from": "x0:out", "to": "lo:x0"}, {"from": "R:out", "to": "lo:R"},
        {"from": "x0:out", "to": "hi:x0"}, {"from": "R:out", "to": "hi:R"},
        {"from": "term:out", "to": "disp:term"},
        {"from": "nsym:out", "to": "disp:index"},
        {"from": "disp:out", "to": "fb:in"},
        {"from": "intro:out", "to": "stmt:in0"}, {"from": "fb:out", "to": "stmt:in1"},
        {"from": "R:out", "to": "ans:R"},
        {"from": "lo:out", "to": "ans:lo"}, {"from": "hi:out", "to": "ans:hi"},
        {"from": "a:out", "to": "ans:a"}, {"from": "b:out", "to": "ans:b"},
        {"from": "ans:out", "to": "ansb:in"},
        {"from": "stmt:out", "to": "task:statement"},
        {"from": "ansb:out", "to": "task:answer"},
    ],
    "meta": {"seed": 14, "max_attempts": 100},
}


# ---------- №5. Признак Вейерштрасса (равномерная сходимость на ℝ) ----------
_S5_WEIERSTRASS = {
    "nodes": [
        {"id": "p", "type": "random_natural", "params": {"min": 1, "max": 2}},
        {"id": "m", "type": "random_natural", "params": {"min": 1, "max": 3}},
        {"id": "k", "type": "random_natural", "params": {"min": 2, "max": 5}},
        # Конструкция гарантирует применимость: q = 2p+2+m ⇒ s = q/2−p = 1+m/2 > 1.
        {"id": "q", "type": "formula", "params": {"expr": "2*p + 2 + m"}},
        {"id": "cc", "type": "formula", "params": {"expr": "k^2"}},
        {"id": "kk", "type": "formula", "params": {"expr": "2*k"}},
        {"id": "qh", "type": "formula", "params": {"expr": "(2*p + 2 + m)/2"}},
        {"id": "s", "type": "formula", "params": {"expr": "1 + m/2"}},
        {"id": "vd", "type": "var_dict", "params": {"names": ["p", "q", "c"]}},
        {"id": "term", "type": "expr_const",
         "params": {"expr": "n**p * x / (1 + c * n**q * x**2)",
                    "vars": ["p", "q", "c", "x", "n"]}},
        {"id": "nsym", "type": "symbol", "params": {"name": "n"}},
        {"id": "disp", "type": "sum_display",
         "params": {"lower": "1", "upper": "oo"}},
        {"id": "intro", "type": "text", "params": {"text":
            "Пользуясь признаком Вейерштрасса, доказать равномерную сходимость "
            "функционального ряда на указанном промежутке:"}},
        {"id": "fb", "type": "expr_block"},
        {"id": "rng", "type": "text", "params": {"text": "−∞ < x < +∞"}},
        {"id": "stmt", "type": "block_list", "params": {"count": 3}},
        {"id": "ans", "type": "text", "params": {"text":
            "По AM–GM: 1 + #c#·n^#q#·x² ≥ #kk#·n^#qh#·|x|, поэтому |uₙ(x)| ≤ "
            "n^#p#/(#kk#·n^#qh#) = (1/#kk#)·n^(−#s#) = Mₙ для всех x. Ряд "
            "Σ Mₙ сходится (p-ряд, s = #s# > 1) ⇒ по Вейерштрассу ряд "
            "сходится равномерно на всей оси."}},
        {"id": "ansb", "type": "to_block", "params": {"relation": ""}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "p:out", "to": "q:p"}, {"from": "m:out", "to": "q:m"},
        {"from": "k:out", "to": "cc:k"}, {"from": "k:out", "to": "kk:k"},
        {"from": "p:out", "to": "qh:p"}, {"from": "m:out", "to": "qh:m"},
        {"from": "m:out", "to": "s:m"},
        {"from": "p:out", "to": "vd:p"}, {"from": "q:out", "to": "vd:q"},
        {"from": "cc:out", "to": "vd:c"},
        {"from": "vd:out", "to": "term:values"},
        {"from": "term:out", "to": "disp:term"},
        {"from": "nsym:out", "to": "disp:index"},
        {"from": "disp:out", "to": "fb:in"},
        {"from": "intro:out", "to": "stmt:in0"},
        {"from": "fb:out", "to": "stmt:in1"},
        {"from": "rng:out", "to": "stmt:in2"},
        {"from": "cc:out", "to": "ans:c"}, {"from": "q:out", "to": "ans:q"},
        {"from": "kk:out", "to": "ans:kk"}, {"from": "qh:out", "to": "ans:qh"},
        {"from": "p:out", "to": "ans:p"}, {"from": "s:out", "to": "ans:s"},
        {"from": "ans:out", "to": "ansb:in"},
        {"from": "stmt:out", "to": "task:statement"},
        {"from": "ansb:out", "to": "task:answer"},
    ],
    "meta": {"seed": 15, "max_attempts": 100},
}


# ---------- №6. Неравномерная сходимость на интервале ----------
_S6_NONUNIFORM = {
    "nodes": [
        {"id": "x0", "type": "random_natural", "params": {"min": 0, "max": 2}},
        {"id": "k", "type": "random_choice",
         "params": {"elem_type": "number", "items": ["2", "4"]}},
        {"id": "vd", "type": "var_dict", "params": {"names": ["x0", "k"]}},
        {"id": "term", "type": "expr_const",
         "params": {"expr": "(x - x0)**(k*n)", "vars": ["x0", "k", "x", "n"]}},
        {"id": "S", "type": "expr_const",
         "params": {"expr": "(x - x0)**k / (1 - (x - x0)**k)",
                    "vars": ["x0", "k", "x"]}},
        {"id": "lo", "type": "formula", "params": {"expr": "x0 - 1"}},
        {"id": "hi", "type": "formula", "params": {"expr": "x0 + 1"}},
        {"id": "nsym", "type": "symbol", "params": {"name": "n"}},
        {"id": "disp", "type": "sum_display",
         "params": {"lower": "1", "upper": "oo"}},
        {"id": "intro", "type": "text", "params": {"text":
            "Доказать, что ряд сходится неравномерно на интервале:"}},
        {"id": "fb", "type": "expr_block"},
        {"id": "rng", "type": "text", "params": {"text": "#lo# < x < #hi#"}},
        {"id": "stmt", "type": "block_list", "params": {"count": 3}},
        {"id": "ansT", "type": "text", "params": {"text":
            "Замена t = (x − #x0#)^#k# ∈ [0; 1) на данном интервале — "
            "геометрический ряд: сумма S(x) ниже, остаток rₙ(x) = "
            "t^(n+1)/(1 − t). При x → концам интервала t → 1 и "
            "sup rₙ(x) = +∞ при каждом n ⇒ остаток не мал равномерно, "
            "сходимость неравномерная."}},
        {"id": "fbS", "type": "expr_block", "params": {"prefix": "S(x)"}},
        {"id": "ansBl", "type": "block_list", "params": {"count": 2}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "x0:out", "to": "vd:x0"}, {"from": "k:out", "to": "vd:k"},
        {"from": "vd:out", "to": "term:values"},
        {"from": "vd:out", "to": "S:values"},
        {"from": "x0:out", "to": "lo:x0"}, {"from": "x0:out", "to": "hi:x0"},
        {"from": "term:out", "to": "disp:term"},
        {"from": "nsym:out", "to": "disp:index"},
        {"from": "disp:out", "to": "fb:in"},
        {"from": "lo:out", "to": "rng:lo"}, {"from": "hi:out", "to": "rng:hi"},
        {"from": "intro:out", "to": "stmt:in0"},
        {"from": "fb:out", "to": "stmt:in1"},
        {"from": "rng:out", "to": "stmt:in2"},
        {"from": "x0:out", "to": "ansT:x0"}, {"from": "k:out", "to": "ansT:k"},
        {"from": "S:out", "to": "fbS:in"},
        {"from": "ansT:out", "to": "ansBl:in0"},
        {"from": "fbS:out", "to": "ansBl:in1"},
        {"from": "stmt:out", "to": "task:statement"},
        {"from": "ansBl:out", "to": "task:answer"},
    ],
    "meta": {"seed": 16, "max_attempts": 100},
}


# ---------- №7. Рациональная дробь → степенной ряд + f^(m)(x) ----------
# Обратное конструирование: сначала простейшие дроби A/(x+p) + B/(x+q),
# из них собирается «внешний вид» условия — разложение заведомо красивое.
_S7_RATIONAL = {
    "nodes": [
        {"id": "A", "type": "random_natural", "params": {"min": 1, "max": 4}},
        {"id": "B", "type": "random_natural", "params": {"min": 1, "max": 4}},
        {"id": "pp", "type": "random_natural", "params": {"min": 1, "max": 5}},
        {"id": "qq", "type": "random_natural", "params": {"min": 1, "max": 5}},
        {"id": "neq", "type": "compare", "params": {"op": "=="}},
        {"id": "g", "type": "guard", "params": {"mode": "require_false"}},
        {"id": "x0", "type": "random_natural", "params": {"min": 0, "max": 3}},
        {"id": "m", "type": "random_choice",
         "params": {"elem_type": "number", "items": ["50", "100", "200"]}},
        {"id": "na", "type": "formula", "params": {"expr": "A + B"}},
        {"id": "nb", "type": "formula", "params": {"expr": "A*q + B*p"}},
        {"id": "dp", "type": "formula", "params": {"expr": "x0 + p"}},
        {"id": "dq", "type": "formula", "params": {"expr": "x0 + q"}},
        {"id": "less", "type": "compare", "params": {"op": "<"}},
        {"id": "R", "type": "select", "params": {"value_type": "number"}},
        {"id": "rlo", "type": "formula", "params": {"expr": "x0 - R"}},
        {"id": "rhi", "type": "formula", "params": {"expr": "x0 + R"}},
        {"id": "mp", "type": "formula", "params": {"expr": "m + 1"}},
        {"id": "vdf", "type": "var_dict",
         "params": {"names": ["na", "nb", "p", "q"]}},
        {"id": "fx", "type": "expr_const",
         "params": {"expr": "(na*x + nb)/((x + p)*(x + q))",
                    "vars": ["na", "nb", "p", "q", "x"]}},
        {"id": "ap", "type": "apart"},
        {"id": "vdt", "type": "var_dict",
         "params": {"names": ["A", "B", "dp", "dq", "x0"]}},
        {"id": "gterm", "type": "expr_const",
         "params": {"expr":
            "(-1)**n * (A/dp**(n+1) + B/dq**(n+1)) * (x - x0)**n",
            "vars": ["A", "B", "dp", "dq", "x0", "x", "n"]}},
        {"id": "nsym", "type": "symbol", "params": {"name": "n"}},
        {"id": "disp", "type": "sum_display",
         "params": {"lower": "0", "upper": "oo"}},
        {"id": "intro", "type": "text", "params": {"text":
            "Представить f(x) в виде степенного ряда по степеням (x − x₀), "
            "x₀ = #x0#. Указать область сходимости. Найти f^(#m#)(x)."}},
        {"id": "fbF", "type": "expr_block", "params": {"prefix": "f(x)"}},
        {"id": "stmt", "type": "block_list", "params": {"count": 2}},
        {"id": "fbAp", "type": "expr_block", "params": {"prefix": "f(x)"}},
        {"id": "fbSer", "type": "expr_block", "params": {"prefix": "f(x)"}},
        {"id": "regT", "type": "text", "params": {"text":
            "Область сходимости: |x − #x0#| < #R#, т.е. (#rlo#; #rhi#) "
            "(до ближайшего полюса)."}},
        {"id": "derT", "type": "text", "params": {"text":
            "f^(#m#)(x) = #m#!·(#A#/(x + #p#)^#mp# + #B#/(x + #q#)^#mp#) — "
            "производные простейших дробей; знак «+», т.к. #m# чётно."}},
        {"id": "ansBl", "type": "block_list", "params": {"count": 4}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "pp:out", "to": "neq:a"}, {"from": "qq:out", "to": "neq:b"},
        {"from": "neq:out", "to": "g:cond"}, {"from": "pp:out", "to": "g:value"},
        {"from": "A:out", "to": "na:A"}, {"from": "B:out", "to": "na:B"},
        {"from": "A:out", "to": "nb:A"}, {"from": "B:out", "to": "nb:B"},
        {"from": "pp:out", "to": "nb:p"}, {"from": "qq:out", "to": "nb:q"},
        {"from": "x0:out", "to": "dp:x0"}, {"from": "pp:out", "to": "dp:p"},
        {"from": "x0:out", "to": "dq:x0"}, {"from": "qq:out", "to": "dq:q"},
        {"from": "dp:out", "to": "less:a"}, {"from": "dq:out", "to": "less:b"},
        {"from": "less:out", "to": "R:cond"},
        {"from": "dp:out", "to": "R:on_true"}, {"from": "dq:out", "to": "R:on_false"},
        {"from": "x0:out", "to": "rlo:x0"}, {"from": "R:out", "to": "rlo:R"},
        {"from": "x0:out", "to": "rhi:x0"}, {"from": "R:out", "to": "rhi:R"},
        {"from": "m:out", "to": "mp:m"},
        {"from": "na:out", "to": "vdf:na"}, {"from": "nb:out", "to": "vdf:nb"},
        {"from": "pp:out", "to": "vdf:p"}, {"from": "qq:out", "to": "vdf:q"},
        {"from": "vdf:out", "to": "fx:values"},
        {"from": "fx:out", "to": "ap:in"},
        {"from": "A:out", "to": "vdt:A"}, {"from": "B:out", "to": "vdt:B"},
        {"from": "dp:out", "to": "vdt:dp"}, {"from": "dq:out", "to": "vdt:dq"},
        {"from": "x0:out", "to": "vdt:x0"},
        {"from": "vdt:out", "to": "gterm:values"},
        {"from": "gterm:out", "to": "disp:term"},
        {"from": "nsym:out", "to": "disp:index"},
        {"from": "x0:out", "to": "intro:x0"}, {"from": "m:out", "to": "intro:m"},
        {"from": "fx:out", "to": "fbF:in"},
        {"from": "intro:out", "to": "stmt:in0"}, {"from": "fbF:out", "to": "stmt:in1"},
        {"from": "ap:out", "to": "fbAp:in"},
        {"from": "disp:out", "to": "fbSer:in"},
        {"from": "x0:out", "to": "regT:x0"}, {"from": "R:out", "to": "regT:R"},
        {"from": "rlo:out", "to": "regT:rlo"}, {"from": "rhi:out", "to": "regT:rhi"},
        {"from": "m:out", "to": "derT:m"}, {"from": "mp:out", "to": "derT:mp"},
        {"from": "A:out", "to": "derT:A"}, {"from": "B:out", "to": "derT:B"},
        {"from": "pp:out", "to": "derT:p"}, {"from": "qq:out", "to": "derT:q"},
        {"from": "fbAp:out", "to": "ansBl:in0"},
        {"from": "fbSer:out", "to": "ansBl:in1"},
        {"from": "regT:out", "to": "ansBl:in2"},
        {"from": "derT:out", "to": "ansBl:in3"},
        {"from": "stmt:out", "to": "task:statement"},
        {"from": "ansBl:out", "to": "task:answer"},
    ],
    "meta": {"seed": 17, "max_attempts": 300},
}


# ---------- №8. Ряд Тейлора ln(x+a) + почленное дифференцирование ----------
_S8_TAYLOR_LN = {
    "nodes": [
        {"id": "a", "type": "random_natural", "params": {"min": 2, "max": 9}},
        {"id": "vd", "type": "var_dict", "params": {"names": ["a"]}},
        {"id": "fx", "type": "expr_const",
         "params": {"expr": "log(x + a)", "vars": ["a", "x"]}},
        # Готовые тождества: Eq(…, Sum(…)) собирается одним выражением.
        {"id": "eq1", "type": "expr_const",
         "params": {"expr": "Eq(log(x + a), log(a) + "
                            "Sum((-1)**(k+1) * x**k / (k * a**k), (k, 1, oo)))",
                    "vars": ["a", "x", "k"]}},
        {"id": "eq2", "type": "expr_const",
         "params": {"expr": "Eq(1/(x + a), "
                            "Sum((-1)**k * x**k / a**(k+1), (k, 0, oo)))",
                    "vars": ["a", "x", "k"]}},
        {"id": "intro", "type": "text", "params": {"text":
            "Разложить f(x) в ряд Тейлора в точке x₀ = 0. Продифференцировать "
            "ряд почленно. Указать область сходимости."}},
        {"id": "fbF", "type": "expr_block", "params": {"prefix": "f(x)"}},
        {"id": "stmt", "type": "block_list", "params": {"count": 2}},
        {"id": "fb1", "type": "expr_block"},
        {"id": "fb2", "type": "expr_block"},
        {"id": "regT", "type": "text", "params": {"text":
            "Область сходимости ряда: −#a# < x ≤ #a#; после почленного "
            "дифференцирования: |x| < #a#."}},
        {"id": "ansBl", "type": "block_list", "params": {"count": 3}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "a:out", "to": "vd:a"},
        {"from": "vd:out", "to": "fx:values"},
        {"from": "vd:out", "to": "eq1:values"},
        {"from": "vd:out", "to": "eq2:values"},
        {"from": "fx:out", "to": "fbF:in"},
        {"from": "intro:out", "to": "stmt:in0"}, {"from": "fbF:out", "to": "stmt:in1"},
        {"from": "eq1:out", "to": "fb1:in"},
        {"from": "eq2:out", "to": "fb2:in"},
        {"from": "a:out", "to": "regT:a"},
        {"from": "fb1:out", "to": "ansBl:in0"},
        {"from": "fb2:out", "to": "ansBl:in1"},
        {"from": "regT:out", "to": "ansBl:in2"},
        {"from": "stmt:out", "to": "task:statement"},
        {"from": "ansBl:out", "to": "task:answer"},
    ],
    "meta": {"seed": 18, "max_attempts": 100},
}


SERIES_EXAM: dict[str, dict] = {
    "s1_comparison": {
        "title": "№1. Сходимость: сравнение с p-рядом",
        "note": "Случайная ветка структуры (select expr): сходится/расходится.",
        "graph": _S1_COMPARISON,
    },
    "s2_dalambert": {
        "title": "№2. Сходимость: признак Даламбера (факториалы)",
        "note": "L = a^b/c^c в замкнутой форме; guard отсекает L=1.",
        "graph": _S2_DALAMBERT,
    },
    "s3_leibniz": {
        "title": "№3. Абсолютная/условная сходимость",
        "note": "Категория ответа разыгрывается, q подбирается под неё.",
        "graph": _S3_LEIBNIZ,
    },
    "s4_power": {
        "title": "№4. Радиус и интервал сходимости степенного ряда",
        "note": "R заложен конструктивно; поведение концов известно заранее.",
        "graph": _S4_POWER,
    },
    "s5_weierstrass": {
        "title": "№5. Признак Вейерштрасса",
        "note": "q = 2p+2+m гарантирует мажоранту; c = k² для целого √c.",
        "graph": _S5_WEIERSTRASS,
    },
    "s6_nonuniform": {
        "title": "№6. Неравномерная сходимость",
        "note": "Геометрический ряд по t=(x−x0)^k; сумма и остаток точно.",
        "graph": _S6_NONUNIFORM,
    },
    "s7_rational": {
        "title": "№7. Рациональная дробь → степенной ряд, f^(m)(x)",
        "note": "Обратное конструирование от простейших дробей; apart в ответе.",
        "graph": _S7_RATIONAL,
    },
    "s8_taylor_ln": {
        "title": "№8. Ряд Тейлора ln(x+a), почленное дифференцирование",
        "note": "Тождества Eq(…, Sum(…)) одним выражением.",
        "graph": _S8_TAYLOR_LN,
    },
}


def series_exam_names() -> list[str]:
    """Имена заданий контрольной в порядке следования."""
    return list(SERIES_EXAM)


def generate_variant(seed: int = 0) -> list[tuple[str, object]]:
    """
    Сгенерировать целый вариант контрольной: список (заголовок, StaticTask).

    Каждое задание получает согласованный сид (seed·100 + номер), поэтому
    вариант воспроизводим целиком.
    """
    import copy
    from core.graph import GraphExecutor, GraphSpec

    out: list[tuple[str, object]] = []
    for i, (name, entry) in enumerate(SERIES_EXAM.items(), start=1):
        spec = copy.deepcopy(entry["graph"])
        spec.setdefault("meta", {})["seed"] = seed * 100 + i
        task = GraphExecutor(GraphSpec.parse(spec)).run()
        out.append((entry["title"], task))
    return out
