# Импорт библиотек
import sys
from PyQt6.QtWidgets import QApplication
from pycode.windows.auth_window import AuthWindow
from pycode.windows.reg_window import RegWindow
from pycode.windows.generator import GeneratorWindow


class MainMenu:
    def __init__(self, auth, reg, gen):
        self.auth = auth
        self.reg = reg
        self.generator = gen
        self.cur_obj = self.auth
        self.cur_obj.mainObject = self

        # Центрируем все окна при инициализации
        self.center_window(self.auth)
        self.center_window(self.reg)
        self.center_window(self.generator)

    def center_window(self, window):
        """Центрирует окно на экране"""
        frame_geometry = window.frameGeometry()
        screen_center = window.screen().availableGeometry().center()
        frame_geometry.moveCenter(screen_center)
        window.move(frame_geometry.topLeft())
        
    def change_cur_obj(self, new):
        self.cur_obj.hide()
        self.cur_obj = new
        self.cur_obj.mainObject = self
        self.center_window(self.cur_obj)
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
    generator = GeneratorWindow()

    # auth.login = "ventano"
    # auth.password = "2112005"
    # auth.check_input()

    start_window = MainMenu(auth, reg, generator)
    start_window.cur_obj.show()
    # start_window = AuthWindow()
    # start_window.show()

    sys.excepthook = except_hook
    sys.exit(app.exec())
