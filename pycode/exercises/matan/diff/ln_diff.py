import random
import sympy as sp


def get_ln_diff():
    x = sp.Symbol("x")

    # для знаменателя
    stepen_zn_1, stepen_zn_2, stepen_zn_3 = random.randint(2, 7), random.randint(2, 7), random.choice(range(2, 8, 2))
    a1, b1 = random.choice([-2, -1, 1, 2]), random.randint(-2, 4)
    a2, b2 = random.choice([-2, -1, 1, 2]), random.randint(-2, 4)
    a3, b3 = random.choice([-2, -1, 1, 2]), random.randint(-2, 4)

    k = random.choice(range(2, 5))

    chisl = (a1 * x + b1) * x ** stepen_zn_1
    znam = ((a3 * x + b3) ** stepen_zn_3) * sp.sqrt((a2 * x ** stepen_zn_2 + b2))

    res_ev = (chisl / znam) ** (1 / k)
    answer = sp.diff(res_ev, x)
    return ("formula", sp.latex(res_ev)), ("formula", sp.latex(sp.simplify(answer)))


if __name__ == "__main__":
    res = get_ln_diff()
    print(res[0][1])
    print(res[1][1])

