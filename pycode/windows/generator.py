# Импорт библиотек
import pycode.helper as hp
from PyQt6 import uic
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QVBoxLayout
from pycode.exercises.linal.ex2_d import get_exercise
from pycode.exercises.linal.linal_main import SecondWindow


class GeneratorWindow(QMainWindow):
    """Класс окна авторизации"""

    def __init__(self):
        """Конструктор"""
        super().__init__()

        self.mainObject = None
        self.answer = None

        # Настройка окна
        uic.loadUi('resources/templates/gen.ui', self)
        self.setWindowIcon(QIcon("resources/icon.png"))
        self.initiolaise()

    def initiolaise(self):
        self.setWindowTitle("Генератор")

        self.generateButton.hide()
        self.taskText.hide()
        self.taskTitle.hide()
        self.answerButton.hide()

        self.subject.addItems(["Линал", "Англ", "Инфа"])
        self.type.addItems(["задание на 2d плоскость"])

        self.type.itemClicked.connect(self.generate_exercise)
        self.generateButton.clicked.connect(self.generate_2_d_task)
        self.subject.currentTextChanged.connect(self.update_tasks_list)
        self.answerButton.clicked.connect(self.show_answer)

    def generate_exercise(self, item):
        self.generateButton.hide()
        self.taskText.hide()
        self.taskTitle.hide()

        if item.text() == "задание на 2d плоскость":
            self.generateButton.show()

    def update_tasks_list(self, text):
        self.type.clear()
        if text == "Линал":
            self.type.addItems(["задание на 2d плоскость"])
        if text == "Англ":
            self.type.addItems(["диктант по модулю 1", "диктант по модулю 2"])

    def generate_2_d_task(self):
        self.generator.setLayout(QVBoxLayout())
        self.second_ui = SecondWindow()
        self.generator.layout().addWidget(self.second_ui)
        # self.taskText.show()
        # self.taskTitle.show()
        # self.answerButton.show()
        #
        # text, answer = get_exercise()
        # self.taskText.setText(text)
        # self.answer = answer

    def show_answer(self):
        self.taskText.setText(self.answer)
        self.answerButton.hide()
