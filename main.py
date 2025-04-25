# Импорт библиотек
import sys
from PyQt6.QtWidgets import QApplication
from pycode.windows.auth_window import AuthWindow
from pycode.windows.reg_window import RegWindow


class MainMenu:
    def __init__(self, auth, reg):
        self.auth = auth
        self.reg = reg
        self.cur_obj = self.auth
        self.cur_obj.mainObject = self
        
    def change_cur_obj(self, new):
        self.cur_obj.hide()
        self.cur_obj = new
        self.cur_obj.mainObject = self
        self.cur_obj.show()

    def __str__(self):
        return "главное меню"

    def __repr__(self):
        return "главное меню"


def except_hook(cls, exception, traceback):
    """Функция для обработки ошибок PyQT"""
    sys.__excepthook__(cls, exception, traceback)


# Точка старта приложения
if __name__ == "__main__":
    app = QApplication(sys.argv)

    auth = AuthWindow()
    reg = RegWindow()

    start_window = MainMenu(auth, reg)
    start_window.cur_obj.show()
    # start_window = AuthWindow()
    # start_window.show()

    sys.excepthook = except_hook
    sys.exit(app.exec())
