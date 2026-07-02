"""
Контрольная по ТФКП (комплексный анализ) — 4 генератора на граф-языке.

Прототип — банк заданий методички: №1 формы комплексного числа, №2 области
на плоскости, №3 все значения многозначной степени, №4 трансцендентные
уравнения. Ключевая новизна относительно рядов — ГРАФИКА: узлы
complex_region_plot / complex_points_plot рисуют область/точки (IMAGE),
дальше стандартный путь to_block. Символьные ответы собираются шаблонами
через subs_expr (точные r, φ вида π/3), условия отображаются неупрощёнными
через UnevaluatedExpr.

COMPLEX_EXAM: имя → {title, note, graph}; generate_complex_variant(seed)
исполняет все четыре графа с согласованными сидами.
"""

from __future__ import annotations


# Пул «красивых» множителей: |w| и arg w — табличные (π/6, π/4, π/3, …).
# Только суммы a + b·i: UnevaluatedExpr печатает их в скобках, произведение
# выглядит как в банке — ((−1+i)(−3+√3·i))^N. Чистые 2i/−3 печатались бы
# без скобок и сливались со знаком.
_NICE_FACTORS = [
    "1 + I", "1 - I", "-1 + I", "-1 - I",
    "sqrt(3) + I", "sqrt(3) - I", "-1 + sqrt(3)*I", "1 + sqrt(3)*I",
    "-3 + sqrt(3)*I", "2 - 2*sqrt(3)*I", "2 + 2*I", "-2 - 2*I",
]


# ---------- К1. Формы комплексного числа (алгебраическая/триг./показательная) —
_K1_FORMS = {
    "nodes": [
        {"id": "w1", "type": "random_choice",
         "params": {"elem_type": "expr", "items": _NICE_FACTORS}},
        {"id": "w2", "type": "random_choice",
         "params": {"elem_type": "expr", "items": _NICE_FACTORS}},
        {"id": "d", "type": "random_natural", "params": {"min": 0, "max": 1}},
        {"id": "N", "type": "random_natural", "params": {"min": 3, "max": 9}},
        {"id": "isprod", "type": "compare", "params": {"op": "==", "b": 1}},
        {"id": "zp", "type": "expr_binop", "params": {"op": "mul"}},
        {"id": "zq", "type": "expr_binop", "params": {"op": "div"}},
        {"id": "z0", "type": "select", "params": {"value_type": "expr"}},
        {"id": "zN", "type": "expr_binop", "params": {"op": "pow"}},
        {"id": "alg0", "type": "expand_complex"},
        {"id": "algS", "type": "simplify"},
        {"id": "alg", "type": "expand"},
        {"id": "r0", "type": "abs"},
        {"id": "r", "type": "simplify"},
        # Аргумент — структурно: φ = N·(φ₁ ± φ₂), приведённый к (−π; π].
        # (sympy arg(alg) не сворачивает «смешанные» углы вроде 7π/12.)
        {"id": "ph1", "type": "arg"},
        {"id": "ph2", "type": "arg"},
        {"id": "sgn", "type": "select", "params": {"value_type": "number"}},
        {"id": "sp1", "type": "constant_number", "params": {"value": 1}},
        {"id": "sm1", "type": "constant_number", "params": {"value": -1}},
        {"id": "pht", "type": "expr_const",
         "params": {"expr": "Mod(N0*(P1 + S0*P2) + pi, 2*pi) - pi",
                    "vars": ["N0", "P1", "P2", "S0"]}},
        {"id": "phs1", "type": "subs_expr", "params": {"name": "P1"}},
        {"id": "phs2", "type": "subs_expr", "params": {"name": "P2"}},
        {"id": "phsN", "type": "subs_expr", "params": {"name": "N0"}},
        {"id": "phsS", "type": "subs_expr", "params": {"name": "S0"}},
        {"id": "ph", "type": "simplify"},
        # Неупрощённое отображение условия: ((w1)·(w2))^N или (w1/w2)^N.
        {"id": "dtp", "type": "expr_const",
         "params": {"expr": "(UnevaluatedExpr(u)*UnevaluatedExpr(v))**N0",
                    "vars": ["u", "v", "N0"]}},
        {"id": "dtq", "type": "expr_const",
         "params": {"expr": "(UnevaluatedExpr(u)/UnevaluatedExpr(v))**N0",
                    "vars": ["u", "v", "N0"]}},
        {"id": "dt", "type": "select", "params": {"value_type": "expr"}},
        {"id": "su", "type": "subs_expr", "params": {"name": "u"}},
        {"id": "sv", "type": "subs_expr", "params": {"name": "v"}},
        {"id": "sN", "type": "subs_expr", "params": {"name": "N0"}},
        {"id": "intro", "type": "text", "params": {"text":
            "Представить данное комплексное число в алгебраической, "
            "тригонометрической и показательной форме."}},
        {"id": "fbZ", "type": "expr_block", "params": {"prefix": "z"}},
        {"id": "stmt", "type": "block_list", "params": {"count": 2}},
        {"id": "fbAlg", "type": "expr_block", "params": {"prefix": "z"}},
        {"id": "forms", "type": "text", "params": {"text":
            "Тригонометрическая форма: z = #r#·(cos(#phi#) + i·sin(#phi#)); "
            "показательная: z = #r#·e^(i·#phi#)."}},
        {"id": "ansBl", "type": "block_list", "params": {"count": 2}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "d:out", "to": "isprod:a"},
        {"from": "w1:out", "to": "zp:a"}, {"from": "w2:out", "to": "zp:b"},
        {"from": "w1:out", "to": "zq:a"}, {"from": "w2:out", "to": "zq:b"},
        {"from": "isprod:out", "to": "z0:cond"},
        {"from": "zp:out", "to": "z0:on_true"},
        {"from": "zq:out", "to": "z0:on_false"},
        {"from": "z0:out", "to": "zN:a"}, {"from": "N:out", "to": "zN:b"},
        {"from": "zN:out", "to": "alg0:in"},
        {"from": "alg0:out", "to": "algS:in"}, {"from": "algS:out", "to": "alg:in"},
        {"from": "alg:out", "to": "r0:in"}, {"from": "r0:out", "to": "r:in"},
        {"from": "w1:out", "to": "ph1:in"}, {"from": "w2:out", "to": "ph2:in"},
        {"from": "isprod:out", "to": "sgn:cond"},
        {"from": "sp1:out", "to": "sgn:on_true"}, {"from": "sm1:out", "to": "sgn:on_false"},
        {"from": "pht:out", "to": "phs1:in"}, {"from": "ph1:out", "to": "phs1:value"},
        {"from": "phs1:out", "to": "phs2:in"}, {"from": "ph2:out", "to": "phs2:value"},
        {"from": "phs2:out", "to": "phsN:in"}, {"from": "N:out", "to": "phsN:value"},
        {"from": "phsN:out", "to": "phsS:in"}, {"from": "sgn:out", "to": "phsS:value"},
        {"from": "phsS:out", "to": "ph:in"},
        {"from": "isprod:out", "to": "dt:cond"},
        {"from": "dtp:out", "to": "dt:on_true"},
        {"from": "dtq:out", "to": "dt:on_false"},
        {"from": "dt:out", "to": "su:in"}, {"from": "w1:out", "to": "su:value"},
        {"from": "su:out", "to": "sv:in"}, {"from": "w2:out", "to": "sv:value"},
        {"from": "sv:out", "to": "sN:in"}, {"from": "N:out", "to": "sN:value"},
        {"from": "sN:out", "to": "fbZ:in"},
        {"from": "intro:out", "to": "stmt:in0"}, {"from": "fbZ:out", "to": "stmt:in1"},
        {"from": "alg:out", "to": "fbAlg:in"},
        {"from": "r:out", "to": "forms:r"}, {"from": "ph:out", "to": "forms:phi"},
        {"from": "fbAlg:out", "to": "ansBl:in0"},
        {"from": "forms:out", "to": "ansBl:in1"},
        {"from": "stmt:out", "to": "task:statement"},
        {"from": "ansBl:out", "to": "task:answer"},
    ],
    "meta": {"seed": 21, "max_attempts": 100},
}


# ---------- К2. Область на комплексной плоскости (4 семейства) ----------
_K2_REGION = {
    "nodes": [
        {"id": "fam", "type": "random_natural", "params": {"min": 0, "max": 3}},
        # f0: кольцо r1 < |z − A| < r2.
        {"id": "A0", "type": "random_natural", "params": {"min": 1, "max": 3}},
        {"id": "r1", "type": "random_natural", "params": {"min": 1, "max": 2}},
        {"id": "dr", "type": "random_natural", "params": {"min": 1, "max": 2}},
        {"id": "r2", "type": "formula", "params": {"expr": "r1 + dr"}},
        {"id": "c0a", "type": "template",
         "params": {"text": "abs(z - #A#) > #r1#"}},
        {"id": "c0b", "type": "template",
         "params": {"text": "abs(z - #A#) < #r2#"}},
        {"id": "l0", "type": "list_new",
         "params": {"count": 2, "elem_type": "string"}},
        {"id": "st0", "type": "text",
         "params": {"text": "#r1# < |z − #A#| < #r2#"}},
        {"id": "an0", "type": "text", "params": {"text":
            "Открытое кольцо с центром #A# и радиусами #r1# и #r2# "
            "(окружности-границы не входят)."}},
        # f1: круг |z + Ai| < r в левой полуплоскости Re z < 0.
        {"id": "A1", "type": "random_natural", "params": {"min": 1, "max": 2}},
        {"id": "rr", "type": "random_natural", "params": {"min": 1, "max": 3}},
        {"id": "c1a", "type": "template",
         "params": {"text": "abs(z + #A#*i) < #r#"}},
        {"id": "c1b", "type": "template", "params": {"text": "re(z) < 0"}},
        {"id": "l1", "type": "list_new",
         "params": {"count": 2, "elem_type": "string"}},
        {"id": "st1", "type": "text",
         "params": {"text": "|z + #A#i| < #r#,  Re z < 0"}},
        {"id": "an1", "type": "text", "params": {"text":
            "Часть открытого круга радиуса #r# с центром −#A#i, лежащая левее "
            "мнимой оси (Re z < 0); границы не входят."}},
        # f2: открытый прямоугольник 0 < Re z < a, −b < Im z < 0.
        {"id": "a2", "type": "random_natural", "params": {"min": 2, "max": 4}},
        {"id": "b2", "type": "random_natural", "params": {"min": 2, "max": 4}},
        {"id": "c2a", "type": "template", "params": {"text": "re(z) > 0"}},
        {"id": "c2b", "type": "template", "params": {"text": "re(z) < #a#"}},
        {"id": "c2c", "type": "template", "params": {"text": "im(z) > -#b#"}},
        {"id": "c2d", "type": "template", "params": {"text": "im(z) < 0"}},
        {"id": "l2", "type": "list_new",
         "params": {"count": 4, "elem_type": "string"}},
        {"id": "st2", "type": "text",
         "params": {"text": "0 < Re z < #a#,  −#b# < Im z < 0"}},
        {"id": "an2", "type": "text", "params": {"text":
            "Открытый прямоугольник (0; #a#) × (−#b#; 0) (стороны не входят)."}},
        # f3: сектор |z| < r, 0 < arg z < π/k.
        {"id": "r3", "type": "random_natural", "params": {"min": 2, "max": 4}},
        {"id": "k3", "type": "random_natural", "params": {"min": 2, "max": 4}},
        {"id": "c3a", "type": "template", "params": {"text": "abs(z) < #r#"}},
        {"id": "c3b", "type": "template", "params": {"text": "arg(z) > 0"}},
        {"id": "c3c", "type": "template", "params": {"text": "arg(z) < pi/#k#"}},
        {"id": "l3", "type": "list_new",
         "params": {"count": 3, "elem_type": "string"}},
        {"id": "st3", "type": "text",
         "params": {"text": "|z| < #r#,  0 < arg z < π/#k#"}},
        {"id": "an3", "type": "text", "params": {"text":
            "Открытый круговой сектор радиуса #r# с раствором π/#k# от "
            "положительной вещественной полуоси (границы не входят)."}},
        # Выбор семейства.
        {"id": "conds", "type": "pick",
         "params": {"count": 4, "value_type": "list"}},
        {"id": "stx", "type": "pick", "params": {"count": 4, "value_type": "block"}},
        {"id": "anx", "type": "pick", "params": {"count": 4, "value_type": "block"}},
        {"id": "plot", "type": "complex_region_plot",
         "params": {"span": 6, "title": "область"}},
        {"id": "img", "type": "to_block", "params": {"caption": ""}},
        {"id": "intro", "type": "text", "params": {"text":
            "Изобразить на комплексной плоскости область, заданную "
            "неравенством или системой неравенств:"}},
        {"id": "stmt", "type": "block_list", "params": {"count": 2}},
        {"id": "ansBl", "type": "block_list", "params": {"count": 2}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "r1:out", "to": "r2:r1"}, {"from": "dr:out", "to": "r2:dr"},
        {"from": "A0:out", "to": "c0a:A"}, {"from": "r1:out", "to": "c0a:r1"},
        {"from": "A0:out", "to": "c0b:A"}, {"from": "r2:out", "to": "c0b:r2"},
        {"from": "c0a:out", "to": "l0:in0"}, {"from": "c0b:out", "to": "l0:in1"},
        {"from": "r1:out", "to": "st0:r1"}, {"from": "A0:out", "to": "st0:A"},
        {"from": "r2:out", "to": "st0:r2"},
        {"from": "A0:out", "to": "an0:A"}, {"from": "r1:out", "to": "an0:r1"},
        {"from": "r2:out", "to": "an0:r2"},
        {"from": "A1:out", "to": "c1a:A"}, {"from": "rr:out", "to": "c1a:r"},
        {"from": "c1a:out", "to": "l1:in0"}, {"from": "c1b:out", "to": "l1:in1"},
        {"from": "A1:out", "to": "st1:A"}, {"from": "rr:out", "to": "st1:r"},
        {"from": "rr:out", "to": "an1:r"}, {"from": "A1:out", "to": "an1:A"},
        {"from": "a2:out", "to": "c2b:a"}, {"from": "b2:out", "to": "c2c:b"},
        {"from": "c2a:out", "to": "l2:in0"}, {"from": "c2b:out", "to": "l2:in1"},
        {"from": "c2c:out", "to": "l2:in2"}, {"from": "c2d:out", "to": "l2:in3"},
        {"from": "a2:out", "to": "st2:a"}, {"from": "b2:out", "to": "st2:b"},
        {"from": "a2:out", "to": "an2:a"}, {"from": "b2:out", "to": "an2:b"},
        {"from": "r3:out", "to": "c3a:r"}, {"from": "k3:out", "to": "c3c:k"},
        {"from": "c3a:out", "to": "l3:in0"}, {"from": "c3b:out", "to": "l3:in1"},
        {"from": "c3c:out", "to": "l3:in2"},
        {"from": "r3:out", "to": "st3:r"}, {"from": "k3:out", "to": "st3:k"},
        {"from": "r3:out", "to": "an3:r"}, {"from": "k3:out", "to": "an3:k"},
        {"from": "fam:out", "to": "conds:index"},
        {"from": "l0:out", "to": "conds:in0"}, {"from": "l1:out", "to": "conds:in1"},
        {"from": "l2:out", "to": "conds:in2"}, {"from": "l3:out", "to": "conds:in3"},
        {"from": "fam:out", "to": "stx:index"},
        {"from": "st0:out", "to": "stx:in0"}, {"from": "st1:out", "to": "stx:in1"},
        {"from": "st2:out", "to": "stx:in2"}, {"from": "st3:out", "to": "stx:in3"},
        {"from": "fam:out", "to": "anx:index"},
        {"from": "an0:out", "to": "anx:in0"}, {"from": "an1:out", "to": "anx:in1"},
        {"from": "an2:out", "to": "anx:in2"}, {"from": "an3:out", "to": "anx:in3"},
        {"from": "conds:out", "to": "plot:conds"},
        {"from": "plot:out", "to": "img:in"},
        {"from": "intro:out", "to": "stmt:in0"}, {"from": "stx:out", "to": "stmt:in1"},
        {"from": "anx:out", "to": "ansBl:in0"}, {"from": "img:out", "to": "ansBl:in1"},
        {"from": "stmt:out", "to": "task:statement"},
        {"from": "ansBl:out", "to": "task:answer"},
    ],
    "meta": {"seed": 22, "max_attempts": 100},
}


# ---------- К3. Все значения многозначной степени ----------
_K3_POWER_VALUES = {
    "nodes": [
        {"id": "fam", "type": "random_natural", "params": {"min": 0, "max": 1}},
        {"id": "m", "type": "random_natural", "params": {"min": 2, "max": 9}},
        {"id": "p", "type": "random_choice",
         "params": {"elem_type": "number", "items": ["2", "3"]}},
        {"id": "vd", "type": "var_dict", "params": {"names": ["m", "p"]}},
        # Отображение выражения: m^i или (−m)^√p.
        {"id": "d0", "type": "expr_const",
         "params": {"expr": "m**I", "vars": ["m"]}},
        {"id": "d1", "type": "expr_const",
         "params": {"expr": "(-m)**sqrt(p)", "vars": ["m", "p"]}},
        {"id": "disp", "type": "pick", "params": {"count": 2, "value_type": "expr"}},
        # Общий член значений (K — номер ветви).
        {"id": "t0", "type": "expr_const",
         "params": {"expr": "exp(-2*pi*K) * (cos(log(m)) + I*sin(log(m)))",
                    "vars": ["K", "m"]}},
        {"id": "t1", "type": "expr_const",
         "params": {"expr": "m**sqrt(p) * (cos(sqrt(p)*pi*(2*K + 1)) "
                            "+ I*sin(sqrt(p)*pi*(2*K + 1)))",
                    "vars": ["K", "m", "p"]}},
        {"id": "term", "type": "pick", "params": {"count": 2, "value_type": "expr"}},
        {"id": "cnt", "type": "select", "params": {"value_type": "number"}},
        {"id": "c3", "type": "constant_number", "params": {"value": 3}},
        {"id": "c5", "type": "constant_number", "params": {"value": 5}},
        {"id": "off", "type": "select", "params": {"value_type": "number"}},
        {"id": "o1", "type": "constant_number", "params": {"value": 1}},
        {"id": "o2", "type": "constant_number", "params": {"value": 2}},
        {"id": "isf0", "type": "compare", "params": {"op": "==", "b": 0}},
        # Точки: k = i − off, подстановка в общий член.
        {"id": "loop", "type": "repeat", "params": {
            "imports": ["term:expr", "off:number"],
            "outputs": ["pts:expr:list"],
            "body": {
                "nodes": [
                    {"id": "tv", "type": "input_var",
                     "params": {"name": "term", "type": "expr"}},
                    {"id": "ov", "type": "input_var",
                     "params": {"name": "off", "type": "number"}},
                    {"id": "li", "type": "loop_index"},
                    {"id": "kf", "type": "formula", "params": {"expr": "i - off"}},
                    {"id": "vk", "type": "var_dict", "params": {"names": ["K"]}},
                    {"id": "sub", "type": "expr_subs"},
                    {"id": "pt", "type": "output_var",
                     "params": {"name": "pts", "type": "expr"}},
                ],
                "edges": [
                    {"from": "li:out", "to": "kf:i"},
                    {"from": "ov:out", "to": "kf:off"},
                    {"from": "kf:out", "to": "vk:K"},
                    {"from": "tv:out", "to": "sub:in"},
                    {"from": "vk:out", "to": "sub:values"},
                    {"from": "sub:out", "to": "pt:value"},
                ],
            }}},
        {"id": "plot", "type": "complex_points_plot",
         "params": {"title": "значения (k = −1..)"}},
        {"id": "img", "type": "to_block"},
        {"id": "an0", "type": "text", "params": {"text":
            "#m#^i = e^(i(ln #m# + 2πk)) = e^(−2πk)·(cos(ln #m#) + "
            "i·sin(ln #m#)), k ∈ ℤ — все значения лежат на луче "
            "arg w = ln #m#; на рисунке k = −1, 0, 1."}},
        {"id": "an1", "type": "text", "params": {"text":
            "(−#m#)^√#p# = e^(√#p#·(ln #m# + iπ(2k+1))) = "
            "#m#^√#p#·(cos(√#p#·π(2k+1)) + i·sin(√#p#·π(2k+1))), k ∈ ℤ — "
            "все значения лежат на окружности радиуса #m#^√#p#; "
            "на рисунке k = −2..2."}},
        {"id": "anx", "type": "pick", "params": {"count": 2, "value_type": "block"}},
        {"id": "intro", "type": "text", "params": {"text":
            "Вычислить все значения заданного выражения и изобразить эти "
            "значения на комплексной плоскости."}},
        {"id": "fbW", "type": "expr_block", "params": {"prefix": "w"}},
        {"id": "stmt", "type": "block_list", "params": {"count": 2}},
        {"id": "ansBl", "type": "block_list", "params": {"count": 2}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "m:out", "to": "vd:m"}, {"from": "p:out", "to": "vd:p"},
        {"from": "vd:out", "to": "d0:values"}, {"from": "vd:out", "to": "d1:values"},
        {"from": "vd:out", "to": "t0:values"}, {"from": "vd:out", "to": "t1:values"},
        {"from": "fam:out", "to": "disp:index"},
        {"from": "d0:out", "to": "disp:in0"}, {"from": "d1:out", "to": "disp:in1"},
        {"from": "fam:out", "to": "term:index"},
        {"from": "t0:out", "to": "term:in0"}, {"from": "t1:out", "to": "term:in1"},
        {"from": "fam:out", "to": "isf0:a"},
        {"from": "isf0:out", "to": "cnt:cond"},
        {"from": "c3:out", "to": "cnt:on_true"}, {"from": "c5:out", "to": "cnt:on_false"},
        {"from": "isf0:out", "to": "off:cond"},
        {"from": "o1:out", "to": "off:on_true"}, {"from": "o2:out", "to": "off:on_false"},
        {"from": "cnt:out", "to": "loop:count"},
        {"from": "term:out", "to": "loop:term"},
        {"from": "off:out", "to": "loop:off"},
        {"from": "loop:pts", "to": "plot:points"},
        {"from": "plot:out", "to": "img:in"},
        {"from": "m:out", "to": "an0:m"},
        {"from": "m:out", "to": "an1:m"}, {"from": "p:out", "to": "an1:p"},
        {"from": "fam:out", "to": "anx:index"},
        {"from": "an0:out", "to": "anx:in0"}, {"from": "an1:out", "to": "anx:in1"},
        {"from": "disp:out", "to": "fbW:in"},
        {"from": "intro:out", "to": "stmt:in0"}, {"from": "fbW:out", "to": "stmt:in1"},
        {"from": "anx:out", "to": "ansBl:in0"}, {"from": "img:out", "to": "ansBl:in1"},
        {"from": "stmt:out", "to": "task:statement"},
        {"from": "ansBl:out", "to": "task:answer"},
    ],
    "meta": {"seed": 23, "max_attempts": 100},
}


# ---------- К4. Трансцендентные уравнения (e^z, cos z, sh z) ----------
_K4_EQUATIONS = {
    "nodes": [
        {"id": "fam", "type": "random_natural", "params": {"min": 0, "max": 2}},
        # f0: e^z = W из пула красивых правых частей.
        {"id": "W", "type": "random_choice",
         "params": {"elem_type": "expr",
                    "items": ["3*I", "-2*I", "-4", "2 + 2*I", "-3 + 3*I"]}},
        {"id": "rW0", "type": "abs"}, {"id": "rW", "type": "simplify"},
        {"id": "phW", "type": "arg"},
        # f1: cos z = a; f2: sh z = b.
        {"id": "a4", "type": "random_natural", "params": {"min": 2, "max": 5}},
        {"id": "b4", "type": "random_natural", "params": {"min": 2, "max": 5}},
        {"id": "vd1", "type": "var_dict", "params": {"names": ["A0"]}},
        {"id": "vd2", "type": "var_dict", "params": {"names": ["B0"]}},
        {"id": "L1", "type": "expr_const",
         "params": {"expr": "log(A0 + sqrt(A0**2 - 1))", "vars": ["A0"]}},
        {"id": "E2", "type": "expr_const",
         "params": {"expr": "log(B0 + sqrt(B0**2 + 1))", "vars": ["B0"]}},
        # Отображение уравнения.
        {"id": "dd0", "type": "expr_const",
         "params": {"expr": "Eq(exp(z), W0)", "vars": ["z", "W0"]}},
        {"id": "sd0", "type": "subs_expr", "params": {"name": "W0"}},
        {"id": "dd1", "type": "expr_const",
         "params": {"expr": "Eq(cos(z), A0)", "vars": ["z", "A0"]}},
        {"id": "dd2", "type": "expr_const",
         "params": {"expr": "Eq(sinh(z), B0)", "vars": ["z", "B0"]}},
        {"id": "disp", "type": "pick", "params": {"count": 3, "value_type": "expr"}},
        # Шаблоны корней (K — номер, S — знак/ветвь ±1).
        {"id": "tt0", "type": "expr_const",
         "params": {"expr": "log(R0) + I*(F0 + 2*pi*K)",
                    "vars": ["R0", "F0", "K"]}},
        {"id": "s0r", "type": "subs_expr", "params": {"name": "R0"}},
        {"id": "s0f", "type": "subs_expr", "params": {"name": "F0"}},
        {"id": "tt1", "type": "expr_const",
         "params": {"expr": "2*pi*K + I*S*L0", "vars": ["K", "S", "L0"]}},
        {"id": "s1l", "type": "subs_expr", "params": {"name": "L0"}},
        {"id": "tt2", "type": "expr_const",
         "params": {"expr": "S*E0 + I*(pi*(1 - S)/2 + 2*pi*K)",
                    "vars": ["K", "S", "E0"]}},
        {"id": "s2e", "type": "subs_expr", "params": {"name": "E0"}},
        {"id": "term", "type": "pick", "params": {"count": 3, "value_type": "expr"}},
        {"id": "isf0", "type": "compare", "params": {"op": "==", "b": 0}},
        {"id": "cnt", "type": "select", "params": {"value_type": "number"}},
        {"id": "c3", "type": "constant_number", "params": {"value": 3}},
        {"id": "c6", "type": "constant_number", "params": {"value": 6}},
        {"id": "stp", "type": "select", "params": {"value_type": "number"}},
        {"id": "p1", "type": "constant_number", "params": {"value": 1}},
        {"id": "p2", "type": "constant_number", "params": {"value": 2}},
        # Корни: K = floor(i/step) − 1, S = ±1 чередуется внутри пары.
        {"id": "loop", "type": "repeat", "params": {
            "imports": ["term:expr", "step:number"],
            "outputs": ["pts:expr:list"],
            "body": {
                "nodes": [
                    {"id": "tv", "type": "input_var",
                     "params": {"name": "term", "type": "expr"}},
                    {"id": "sv", "type": "input_var",
                     "params": {"name": "step", "type": "number"}},
                    {"id": "li", "type": "loop_index"},
                    {"id": "kf", "type": "formula",
                     "params": {"expr": "floor(i/step) - 1"}},
                    {"id": "sf", "type": "formula",
                     "params": {"expr": "2*(i - step*floor(i/step)) - 1"}},
                    {"id": "vk", "type": "var_dict", "params": {"names": ["K", "S"]}},
                    {"id": "sub", "type": "expr_subs"},
                    {"id": "pt", "type": "output_var",
                     "params": {"name": "pts", "type": "expr"}},
                ],
                "edges": [
                    {"from": "li:out", "to": "kf:i"},
                    {"from": "sv:out", "to": "kf:step"},
                    {"from": "li:out", "to": "sf:i"},
                    {"from": "sv:out", "to": "sf:step"},
                    {"from": "kf:out", "to": "vk:K"},
                    {"from": "sf:out", "to": "vk:S"},
                    {"from": "tv:out", "to": "sub:in"},
                    {"from": "vk:out", "to": "sub:values"},
                    {"from": "sub:out", "to": "pt:value"},
                ],
            }}},
        {"id": "plot", "type": "complex_points_plot",
         "params": {"title": "корни (k = −1, 0, 1)"}},
        {"id": "img", "type": "to_block"},
        {"id": "an0", "type": "text", "params": {"text":
            "e^z = w: z = ln|w| + i(arg w + 2πk) = ln(#r#) + i(#phi# + 2πk), "
            "k ∈ ℤ — вертикальная решётка корней с шагом 2π."}},
        {"id": "an1", "type": "text", "params": {"text":
            "cos z = #a#: z = 2πk ± i·ln(#a# + √(#a#² − 1)) = 2πk ± i·#L#, "
            "k ∈ ℤ (пары корней на мнимых прямых)."}},
        {"id": "an2", "type": "text", "params": {"text":
            "sh z = #b#: z = #E# + 2πik и z = −#E# + iπ(2k + 1), где "
            "#E# = ln(#b# + √(#b#² + 1)), k ∈ ℤ."}},
        {"id": "anx", "type": "pick", "params": {"count": 3, "value_type": "block"}},
        {"id": "intro", "type": "text", "params": {"text":
            "Решить уравнение. Корни уравнения изобразить на комплексной "
            "плоскости (показаны ветви k = −1, 0, 1)."}},
        {"id": "fbE", "type": "expr_block"},
        {"id": "stmt", "type": "block_list", "params": {"count": 2}},
        {"id": "ansBl", "type": "block_list", "params": {"count": 2}},
        {"id": "task", "type": "static_task"},
    ],
    "edges": [
        {"from": "W:out", "to": "rW0:in"}, {"from": "rW0:out", "to": "rW:in"},
        {"from": "W:out", "to": "phW:in"},
        {"from": "a4:out", "to": "vd1:A0"}, {"from": "b4:out", "to": "vd2:B0"},
        {"from": "vd1:out", "to": "L1:values"}, {"from": "vd2:out", "to": "E2:values"},
        {"from": "dd0:out", "to": "sd0:in"}, {"from": "W:out", "to": "sd0:value"},
        {"from": "vd1:out", "to": "dd1:values"}, {"from": "vd2:out", "to": "dd2:values"},
        {"from": "fam:out", "to": "disp:index"},
        {"from": "sd0:out", "to": "disp:in0"},
        {"from": "dd1:out", "to": "disp:in1"}, {"from": "dd2:out", "to": "disp:in2"},
        {"from": "tt0:out", "to": "s0r:in"}, {"from": "rW:out", "to": "s0r:value"},
        {"from": "s0r:out", "to": "s0f:in"}, {"from": "phW:out", "to": "s0f:value"},
        {"from": "tt1:out", "to": "s1l:in"}, {"from": "L1:out", "to": "s1l:value"},
        {"from": "tt2:out", "to": "s2e:in"}, {"from": "E2:out", "to": "s2e:value"},
        {"from": "fam:out", "to": "term:index"},
        {"from": "s0f:out", "to": "term:in0"},
        {"from": "s1l:out", "to": "term:in1"}, {"from": "s2e:out", "to": "term:in2"},
        {"from": "fam:out", "to": "isf0:a"},
        {"from": "isf0:out", "to": "cnt:cond"},
        {"from": "c3:out", "to": "cnt:on_true"}, {"from": "c6:out", "to": "cnt:on_false"},
        {"from": "isf0:out", "to": "stp:cond"},
        {"from": "p1:out", "to": "stp:on_true"}, {"from": "p2:out", "to": "stp:on_false"},
        {"from": "cnt:out", "to": "loop:count"},
        {"from": "term:out", "to": "loop:term"},
        {"from": "stp:out", "to": "loop:step"},
        {"from": "loop:pts", "to": "plot:points"},
        {"from": "plot:out", "to": "img:in"},
        {"from": "rW:out", "to": "an0:r"}, {"from": "phW:out", "to": "an0:phi"},
        {"from": "a4:out", "to": "an1:a"}, {"from": "L1:out", "to": "an1:L"},
        {"from": "b4:out", "to": "an2:b"}, {"from": "E2:out", "to": "an2:E"},
        {"from": "fam:out", "to": "anx:index"},
        {"from": "an0:out", "to": "anx:in0"},
        {"from": "an1:out", "to": "anx:in1"}, {"from": "an2:out", "to": "anx:in2"},
        {"from": "disp:out", "to": "fbE:in"},
        {"from": "intro:out", "to": "stmt:in0"}, {"from": "fbE:out", "to": "stmt:in1"},
        {"from": "anx:out", "to": "ansBl:in0"}, {"from": "img:out", "to": "ansBl:in1"},
        {"from": "stmt:out", "to": "task:statement"},
        {"from": "ansBl:out", "to": "task:answer"},
    ],
    "meta": {"seed": 24, "max_attempts": 100},
}


COMPLEX_EXAM: dict[str, dict] = {
    "k1_forms": {
        "title": "№1. Формы комплексного числа",
        "note": "Пул «красивых» множителей; произведение/частное^N; точные "
                "r и φ; условие неупрощённым (UnevaluatedExpr + subs_expr).",
        "graph": _K1_FORMS,
    },
    "k2_region": {
        "title": "№2. Область на комплексной плоскости",
        "note": "4 семейства (кольцо/круг+полуплоскость/прямоугольник/сектор); "
                "complex_region_plot рисует область в ответ.",
        "graph": _K2_REGION,
    },
    "k3_power_values": {
        "title": "№3. Все значения многозначной степени",
        "note": "m^i (луч) и (−m)^√p (окружность); точки по ветвям k через "
                "цикл с expr-туннелем; complex_points_plot.",
        "graph": _K3_POWER_VALUES,
    },
    "k4_equations": {
        "title": "№4. Трансцендентные уравнения",
        "note": "e^z = w / cos z = a / sh z = b; корни по ветвям (K, S=±1) "
                "одним циклом; решётка корней на картинке.",
        "graph": _K4_EQUATIONS,
    },
}


def complex_exam_names() -> list[str]:
    """Имена заданий контрольной по ТФКП в порядке следования."""
    return list(COMPLEX_EXAM)


def generate_complex_variant(seed: int = 0) -> list[tuple[str, object]]:
    """Сгенерировать вариант контрольной по ТФКП: (заголовок, StaticTask)."""
    import copy
    from core.graph import GraphExecutor, GraphSpec

    out: list[tuple[str, object]] = []
    for i, (name, entry) in enumerate(COMPLEX_EXAM.items(), start=1):
        spec = copy.deepcopy(entry["graph"])
        spec.setdefault("meta", {})["seed"] = seed * 100 + i
        task = GraphExecutor(GraphSpec.parse(spec)).run()
        out.append((entry["title"], task))
    return out
