from PyQt6 import uic
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow

from bin.window_profile import WindowProfile


# Класс главного окна
class WindowMain(QMainWindow):
    # Функция инициализации
    def __init__(self, helper, window_auth, user):
        super().__init__()

        self.helper = helper
        self.window_auth = window_auth
        self.user = user

        self.initUI()

    # Функция инициализации интерфейса
    def initUI(self):
        uic.loadUi('templates/window_main.ui', self)
        self.setWindowIcon(QIcon('icon.png'))

        self.deleteAccountAction.triggered.connect(self.delete_account)
        self.exitAccountAction.triggered.connect(self.open_window_auth)
        self.aboutAppAction.triggered.connect(self.helper.open_dialog_about_app)
        self.exitAction.triggered.connect(self.helper.close_app)

        self.positionLabel.setText(f"Вы авторизовались как: {self.user[6]}")
        self.nicknameLabel.setText(f"{self.user[3]}")

        self.profilePushButton.clicked.connect(self.open_window_profile)
        self.deleteAccountPushButton.clicked.connect(self.delete_account)
        self.exitAccountPushButton.clicked.connect(self.open_window_auth)
        self.exitPushButton.clicked.connect(self.helper.close_app)

    # Открытие окна профиля
    def open_window_profile(self):
        self.window_profile = WindowProfile(self.helper, self, self.user)
        self.window_profile.show()
        self.hide()

    # Открытие окна авторизации
    def open_window_auth(self):
        self.window_auth.show()
        self.close()

    # Удаление аккаунта
    def delete_account(self):
        yes = self.helper.show_message_box("Вы действительно хотите удалить аккаунт?", True)
        if yes:
            query = f"DELETE FROM users WHERE email = '{self.user[1]}'"
            self.helper.db.execute_query(query)
            self.window_auth.update_users_debug()
            self.open_window_auth()
