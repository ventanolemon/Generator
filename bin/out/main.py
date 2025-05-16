import sys
from PyQt6.QtWidgets import QApplication
from py_code.windows.auf_window import AuthWindow


def except_hook(cls, exception, traceback):
    sys.__excepthook__(cls, exception, traceback)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    start_window = AuthWindow()
    start_window.show()

    sys.excepthook = except_hook
    sys.exit(app.exec())
