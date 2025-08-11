# Импорт библиотек
import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout
from PyQt6 import uic
import pyqtgraph as pg
import numpy as np


class GraphWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

    def add_graph(self, data):
        plot = pg.PlotWidget()
        plot.plot(data)
        self.layout.addWidget(plot)


class Profile(QMainWindow):
    def __init__(self):
        self.mainObject = None

        super().__init__()

        uic.loadUi(r"C:\Users\happy\PycharmProjects\PythonProject4\resources\templates\profile_interface.ui", self)
        self.graphics_area.setWidgetResizable(True)
        # Создаем контейнер для графиков
        self.content = GraphWidget()
        self.graphics_area.setWidget(self.content)

        # Генерируем данные для графиков
        data = np.random.randn(100)

        # Добавляем несколько графиков
        for _ in range(10):  # Создаем 10 графиков
            self.content.add_graph(data)

        self.initiolaise()

    def initiolaise(self):
        self.setWindowTitle("Профиль")

        self.generator.clicked.connect(self.go_to_generator)

    def add_graphic(self):
        # Создаем виджет для графика
        self.widget = pg.GraphicsLayoutWidget()
        self.scroll.setWidget(self.widget)

        # Создаем график
        self.plot = self.widget.addPlot()

        # Добавляем данные для примера
        self.plot.plot([1, 2, 3, 4, 5], [1, 4, 9, 16, 25])

    def go_to_generator(self):
        self.mainObject.change_cur_obj(self.mainObject.generator)


def except_hook(cls, exception, traceback):
    """Функция для обработки ошибок PyQT"""
    sys.__excepthook__(cls, exception, traceback)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    wind = Profile()
    wind.show()
    sys.excepthook = except_hook
    sys.exit(app.exec())
