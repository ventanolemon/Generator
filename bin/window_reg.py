import os
import re
import base64
from PyQt6 import uic
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QMainWindow, QLineEdit, QFileDialog


# Класс окна регистрации
class Reg(QMainWindow):
    # Функция инициализации
    def __init__(self, helper, window_auth):
        super().__init__()

        self.helper = helper
        self.window_auth = window_auth

        self.initUI()

    # Функция инициализации интерфейса
    def initUI(self):
        uic.loadUi('templates/window_reg.ui', self)
        self.setWindowIcon(QIcon('icon.png'))

        self.selectAvatarPushButton.clicked.connect(self.select_avatar)
        self.authPushButton.clicked.connect(self.open_auth_window)
        self.regPushButton.clicked.connect(self.reg)
        self.exitPushButton.clicked.connect(self.helper.close_app)

        self.aboutAppAction.triggered.connect(self.helper.open_dialog_about_app)
        self.exitAction.triggered.connect(self.helper.close_app)

        self.emailLineEdit.textChanged.connect(self.email_validate)
        self.passwordLineEdit.textChanged.connect(self.password_validate)
        self.nicknameLineEdit.textChanged.connect(self.nickname_validate)
        self.showPasswordCheckBox.stateChanged.connect(self.change_mode_show_password)
        self.passwordLineEdit.setEchoMode(QLineEdit.EchoMode.Password)

        pixmap = QPixmap('data/default_avatar.jpg')
        self.avatarImageLabel.setPixmap(pixmap)

    # Функция открытия окна авторизации
    def open_auth_window(self):
        self.window_auth.show()
        self.close()

    # Функция проверки валидации поля email
    def email_validate(self):
        if not re.match(self.helper.EMAIL_PATTERN, self.emailLineEdit.text()):
            self.emailLineEdit.setStyleSheet("background-color: red; color: white;")
            self.emailStatusLabel.setText(f"Не подходит!")
            return False
        else:
            self.emailStatusLabel.setText(f"")
            self.emailLineEdit.setStyleSheet("background-color: white; color: black;")
            return True

    # Функция проверки валидации поля password
    def password_validate(self):
        password = self.passwordLineEdit.text()

        if ((not re.match(self.helper.PASSWORD_PATTERN, password) or len(password) < 4 or len(password) > 20
             or not re.search(r'[A-Z]', password)) or not re.search(r'[a-z]', password)
                or not re.search(r'\d', password)):
            self.passwordLineEdit.setStyleSheet("background-color: red; color: white;")
            self.passwordStatusLabel.setText(f"Не подходит!")
            return False
        else:
            self.passwordStatusLabel.setText(f"")
            self.passwordLineEdit.setStyleSheet("background-color: white; color: black;")
            return True

    # Функция перевода режима показа пароля
    def change_mode_show_password(self, state):
        if state == 2:
            self.passwordLineEdit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.passwordLineEdit.setEchoMode(QLineEdit.EchoMode.Password)

    # Функция проверки валидации поля password
    def nickname_validate(self):
        nickname = self.nicknameLineEdit.text()

        if not re.match(self.helper.NICKNAME_PATTERN, nickname) or len(nickname) < 4 or len(nickname) > 20:
            self.nicknameLineEdit.setStyleSheet("background-color: red; color: white;")
            self.nicknameStatusLabel.setText(f"Не подходит!")
            return False
        else:
            self.nicknameStatusLabel.setText(f"")
            self.nicknameLineEdit.setStyleSheet("background-color: white; color: black;")
            return True

    # Функция выбора аватара
    def select_avatar(self):
        fname = QFileDialog.getOpenFileName(self, 'Выбрать картинку', '',
                                            'Картинка (*.jpg);;Картинка (*.png)')[0]
        if fname:
            self.avatarTextEdit.setText(fname)
            pixmap = QPixmap(fname)
            self.avatarImageLabel.setPixmap(pixmap)
        else:
            self.avatarTextEdit.setText('')
            self.avatarImageLabel.clear()
            pixmap = QPixmap('data/default_avatar.jpg')
            self.avatarImageLabel.setPixmap(pixmap)

    # Открытие окна регистрации
    def reg(self):
        self.email_validate()
        self.password_validate()
        self.nickname_validate()

        if not self.email_validate():
            self.helper.show_message_box("Почта указана некорректно!", False)
            return

        if not self.password_validate():
            self.helper.show_message_box("Пароль указан некорректно!", False)
            return

        if not self.nickname_validate():
            self.helper.show_message_box("Никнейм указан некорректно!", False)
            return

        if self.avatarTextEdit.toPlainText() and not os.path.exists(self.avatarTextEdit.toPlainText()):
            self.helper.show_message_box("Изображение аватара не найдено!", False)
            return

        email = self.emailLineEdit.text()
        password = self.helper.db.get_sha256_hash(self.passwordLineEdit.text())
        nickname = self.nicknameLineEdit.text()
        avatar_path = self.avatarTextEdit.toPlainText()

        query = f"SELECT email FROM users WHERE email='{email}'"
        if self.helper.db.execute_query(query, is_fetch_one=True):
            self.helper.show_message_box("Почта уже используется!", False)
            return

        if avatar_path:
            with open(avatar_path, 'rb') as file:
                image_data = file.read()
            image_data_encoded = base64.b64encode(image_data).decode('utf-8')  # Кодируем в строку base64
            query = f"""INSERT INTO users (email, password, nickname, avatar, position_id) 
            VALUES ('{email}', '{password}', '{nickname}', '{image_data_encoded}', 3)"""
        else:
            query = f"""INSERT INTO users (email, password, nickname, position_id) 
            VALUES ('{email}', '{password}', '{nickname}', 3)"""
        self.helper.db.execute_query(query)

        self.helper.show_message_box("Вы зарегистрировались!", False)

        if self.helper.debug_mode:
            self.window_auth.update_users_debug()
        self.open_auth_window()
