from PyQt6.QtWidgets import QApplication, QMainWindow, QFrame, QWidget
from PyQt6.uic import loadUi

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        loadUi('main_window.ui', self)  # Загружаем основной UI

        # Получаем фрейм из основного интерфейса
        self.frame = self.findChild(QFrame, 'frame')

        # Создаем второй интерфейс
        self.second_ui = SecondWindow()
        self.frame.layout().addWidget(self.second_ui)

class SecondWindow(QWidget):
    def __init__(self):
        super().__init__()
        loadUi('pycode/exercises/linal/linal2-d.ui', self)
