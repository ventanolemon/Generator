from PyQt6 import uic
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QLineEdit

from bin.window_main import WindowMain
from bin.window_reg import Reg


# Класс окна авторизации
class Auth(QMainWindow):
    # Функция инициализации
    def __init__(self, helper):
        super().__init__()

        self.helper = helper

        self.initUI()

    # Функция инициализации интерфейса
    def initUI(self):
        uic.loadUi('templates/window_auth.ui', self)
        self.setWindowIcon(QIcon('icon.png'))

        self.authPushButton.clicked.connect(self.auth)
        self.regPushButton.clicked.connect(self.open_window_reg)
        self.exitPushButton.clicked.connect(self.close_this_window)

        self.aboutAppAction.triggered.connect(self.helper.open_dialog_about_app)
        self.exitAction.triggered.connect(self.helper.close_app)

        self.showPasswordCheckBox.stateChanged.connect(self.change_mode_show_password)
        self.passwordLineEdit.setEchoMode(QLineEdit.EchoMode.Password)

        if not self.helper.debug_mode:
            self.usersComboBox.hide()
            self.debugEnterPushButton.hide()
            self.enterPushButton.hide()
        else:
            self.update_users_debug()
            self.debugEnterPushButton.clicked.connect(self.debug_auth)

    # Функция обновления поля для тестового ввода
    def update_users_debug(self):
        self.usersComboBox.clear()
        query = "SELECT email FROM users"
        users = self.helper.db.execute_query(query, is_fetch_one=False)
        for i in users:
            self.usersComboBox.addItem(i[0])

    # Функция перевода режима показа пароля
    def change_mode_show_password(self, state):
        if state == 2:
            self.passwordLineEdit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.passwordLineEdit.setEchoMode(QLineEdit.EchoMode.Password)

    # Открытие окна регистрации
    def open_window_reg(self):
        self.window_reg = Reg(self.helper, self)
        self.window_reg.show()
        self.hide()

    # Закрытие окна
    def close_this_window(self):
        self.close()

    # Функция авторизации
    def auth(self):
        email = self.emailLineEdit.text()
        password = self.passwordLineEdit.text()

        query = f"""
        SELECT u.id, u.email, u.password, u.nickname, u.avatar, u.position_id, p.title AS position_title
        FROM users as u
        JOIN positions p ON u.position_id = p.id
        WHERE email='{email}'"""
        user = self.helper.db.execute_query(query)

        if user:
            if user[2] == self.helper.db.get_sha256_hash(password):
                user = list(user)
                self.window_main = WindowMain(self.helper, self, user)
                self.window_main.show()
                self.hide()
                self.emailLineEdit.setText("")
                self.passwordLineEdit.setText("")
            else:
                self.helper.show_message_box("Неверный пароль!", False)

        else:
            self.helper.show_message_box("Аккаунта не найдено!", False)

    # Вход в тестовом режиме
    def debug_auth(self):
        email = self.usersComboBox.currentText()

        query = f"""
                SELECT u.id, u.email, u.password, u.nickname, u.avatar, u.position_id, p.title AS position_title
                FROM users as u
                JOIN positions p ON u.position_id = p.id
                WHERE email='{email}'"""
        user = self.helper.db.execute_query(query)

        if user:
            user = list(user)
            self.window_main = WindowMain(self.helper, self, user)
            self.window_main.show()
            self.hide()
            self.emailLineEdit.setText("")
            self.passwordLineEdit.setText("")
