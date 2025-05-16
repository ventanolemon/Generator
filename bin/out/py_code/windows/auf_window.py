from PyQt6.QtWidgets import QMainWindow
from PyQt6.QtGui import QIcon
from PyQt6 import uic


class AuthWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        uic.loadUi("resources/templates/AuthWindow.ui", self)
        self.setWindowIcon(QIcon("resources/MIREA_Gerb_Colour.jpg"))
        # self.pushButtonCloseWindow.clicked.connect(self.close)
        self.AboutProg.triggered.connect(self.close)