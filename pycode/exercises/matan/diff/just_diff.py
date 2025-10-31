import random
import sympy as sp



e = sp.Symbol("e")
def get_ev(res, ind=None):
    a, m = random.randint(2, 10), random.randint(2, 10)
    base_equals = [sp.sin(res), sp.tan(res), sp.asin(res), sp.atan(res), a ** res - 1, sp.ln(1 + res),
                   (e ** res) - 1,
                   (1 + res) ** m - 1]
    if ind is not None:
        return base_equals[ind]
    return random.choice(base_equals)


def get_just_diff():
    x = sp.Symbol("x")
    const_1, const_2, const_3, const_4 = random.choices([i for i in range(-3, 6) if i], k=4)
    st_1, st_2, st_3, st_4 = random.choices([i for i in range(-2, 5) if i], k=4)
    first_x, second_x, third_x, fourth_x = (const_1 * x ** st_1, const_2 * x ** st_2, const_3 * x ** st_3,
                                            const_4 * x ** st_4)

    ev_1, ev_2, ev_3, ev_4 = get_ev(first_x), get_ev(second_x), get_ev(third_x), get_ev(fourth_x)

    res_ev = ev_1 * ev_2 + ev_3 / ev_4

    answer = sp.diff(res_ev, x)
    return ("formula", sp.latex(res_ev)), ("formula", sp.latex(answer))


if __name__ == "__main__":
    res = get_just_diff()
    print(res[0][1])
    print(res[1][1])
