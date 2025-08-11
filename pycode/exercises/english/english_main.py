from PyQt6.QtWidgets import QApplication, QMainWindow, QFrame, QWidget
from PyQt6.uic import loadUi
from pycode.exercises.linal.ex2_d import get_exercise
# -*- coding: utf-8 -*-
import random
from random import choice
from json import load
import os
from functools import reduce


LAST = []
LAST_WRONG = []


class SecondWindow(QWidget):
    def __init__(self):
        super().__init__()
        loadUi('pycode/exercises/linal/linal2-d.ui', self)
        self.generateButton.clicked.connect(self.generate_task)
        self.answerButton.clicked.connect(self.show_answer)

        self.task_text = None
        self.answer = None

        self.taskText.hide()
        self.taskTitle.hide()
        self.answerButton.hide()

    def generate_task(self):
        self.taskText.show()
        self.taskTitle.show()
        self.answerButton.show()

        text, answer = get_exercise()

        self.taskText.setText(text)
        self.task_text = text
        self.answer = answer

    def show_answer(self):
        self.taskText.setText(self.answer)
        # self.answerButton.hide()
        self.answerButton.setText("показать задание")
        self.answerButton.clicked.connect(self.show_task)

    def show_task(self):
        self.taskText.setText(self.task_text)
        self.answerButton.setText("показать ответ")
        self.answerButton.clicked.connect(self.show_answer)

    def test(self, part):
        global LAST_WRONG
        global LAST

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
                var = self.choice_word(now)
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

    def choice_word(self, sl):
        global LAST
        slovo = choice(list(sl.keys()))
        if slovo not in LAST:
            LAST.append(slovo)
            if len(LAST) > len(list(sl.keys())) // 3:
                LAST = LAST[1:]
            return slovo
        elif len(sl) - len(LAST) <= 0:
            if random.randint(0, 2):
                try:
                    return self.choice_word(sl)
                except Exception:
                    return slovo
            return slovo
        else:
            return self.choice_word(sl)
