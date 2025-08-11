from PyQt6.QtWidgets import QApplication, QMainWindow, QFrame, QWidget, QVBoxLayout
from PyQt6.uic import loadUi
from pycode.exercises.linal import ex2_d
from pycode.exercises.linal import ex3_d


class LinalMain(QMainWindow):
    def __init__(self, main_obj):
        super().__init__()
        # loadUi('main_window.ui', self)  # Загружаем основной UI

        self.main_obj = main_obj

        # self.ex2_d = SecondWindow()
        # self.ex3_d = ThirdWindow()
        # Получаем фрейм из основного интерфейса
        # self.frame = self.findChild(QFrame, 'frame')
        # Создаем второй интерфейс
        # self.second_ui = SecondWindow()
        # self.frame.layout().addWidget(self.second_ui)

    def get_ex(self, partitions_id):
        if partitions_id == 1:
            task_obj = SecondWindow()
        elif partitions_id == 4:
            task_obj = ThirdWindow()

        self.main_obj.second_ui = task_obj
        self.main_obj.generator.layout().addWidget(self.main_obj.second_ui)


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

        text, answer = ex2_d.get_exercise()

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


class ThirdWindow(QWidget):
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

        text, answer = ex3_d.get_exercise()

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

