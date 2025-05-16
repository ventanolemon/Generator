import os.path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from bin.database import Database
from bin.out.py_code.windows.dialog_about_app import DialogAboutApp


# Класс вспомогательного файла
class Helper:
    EMAIL_PATTERN = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    PASSWORD_PATTERN = r"^[a-zA-Z0-9_@/%+-]+$"
    NICKNAME_PATTERN = r"^[a-zA-Z0-9_]+$"

    # Инициализация свойств
    def __init__(self):
        self.debug_mode = self.check_debug_mode()
        self.name_app = "Приложение PyQTSQL"
        self.db = Database()

    # Функция на проверку файла режима отладки
    def check_debug_mode(self):
        filename = "data/debug_mode.txt"
        if os.path.exists(filename):
            with open(filename, mode="r", encoding="utf8") as f:
                return f.read() == "1"
        else:
            return False

    # Функция вызова диалогового окна
    def show_message_box(self, text, yes_no=False):
        message_box = QMessageBox()
        message_box.setText(text)
        message_box.setWindowTitle(self.name_app)
        message_box.setWindowIcon(QIcon('icon.png'))
        message_box.setIcon(QMessageBox.Icon.Information)
        if not yes_no:
            message_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            message_box.button(QMessageBox.StandardButton.Ok).setText("Ок")
        else:
            message_box.setStandardButtons(QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
            message_box.button(QMessageBox.StandardButton.Ok).setText("Ок")
            message_box.button(QMessageBox.StandardButton.Cancel).setText("Отмена")

        result = message_box.exec()
        return result == QMessageBox.StandardButton.Ok

    # Открытие окна справки
    def open_dialog_about_app(self):
        self.diaglog_about_app = DialogAboutApp(self)
        self.diaglog_about_app.exec()

    # Функция закрытия приложения
    def close_app(self):
        QApplication.instance().quit()
