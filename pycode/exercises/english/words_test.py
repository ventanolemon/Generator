# -*- coding: utf-8 -*-
import random
from random import choice
from json import load
import os
from functools import reduce


LAST = []
LAST_WRONG = []


def choice_word(sl):
    global LAST
    slovo = choice(list(sl.keys()))
    if slovo not in LAST:
        LAST.append(slovo)
        if len(LAST) > len(list(sl.keys())) // 3:
            LAST = LAST[1:]
        return slovo
    elif len(now) - len(LAST) <= 0:
        if random.randint(0, 2):
            try:
                return choice_word(sl)
            except Exception:
                return slovo
        return slovo
    else:
        return choice_word(sl)


'''
all_words = slova_characters.copy()
all_words.update(slova_family)
all_words.update(slova_education)
now = {1: slova_characters, 2: slova_family, 3: slova_education, 4: all_words}[int(input())]
'''
def test(part):
    files = [i.path for i in os.scandir("words") if part in i.path]
    words = [load(open(file, encoding='utf-8')) for file in files]
    now = reduce(lambda a, b: a | b, words)
    while True:
        # var = choice(list(slova_characters.keys()))
        if len(LAST_WRONG) > 5:
            try:
                LAST.remove(LAST_WRONG[0])
            except Exception as ex:
                pass
            LAST_WRONG = LAST_WRONG[1:]
        if now:
            var = choice_word(now)
            print(now[var])
            if input() == var:
                print("YEEEEE", var)
                now.pop(var)
            else:
                print("NOOOOOO", var)
                LAST_WRONG.append(now)
                if len(LAST_WRONG) > 6:
                    LAST_WRONG = LAST_WRONG[:5]
        else:
            print("Thats all")
            break
