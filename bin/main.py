import sys

from bin.helper import Helper
from bin.window_auth import Auth
from PyQt6.QtWidgets import QApplication


def except_hook(cls, exception, traceback):
    sys.__excepthook__(cls, exception, traceback)


if __name__ == '__main__':
    sys.excepthook = except_hook
    app = QApplication(sys.argv)
    helper = Helper()
    ex = Auth(helper)
    ex.show()
    sys.exit(app.exec())
