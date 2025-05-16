import base64
import os.path
import re

from PyQt6 import uic
from PyQt6.QtCore import QByteArray
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QMainWindow, QFileDialog, QLineEdit


# Класс окна профиля
class WindowProfile(QMainWindow):
    # Функция инициализации
    def __init__(self, helper, window_main, user):
        super().__init__()

        self.helper = helper
        self.window_main = window_main
        self.user = user

        self.initUI()

    # Функция инициализации интерфейса
    def initUI(self):
        uic.loadUi('templates/window_profile.ui', self)
        self.setWindowIcon(QIcon('icon.png'))

        self.aboutAppAction.triggered.connect(self.helper.open_dialog_about_app)
        self.exitAction.triggered.connect(self.helper.close_app)
        self.backAction.triggered.connect(self.open_window_main)

        self.selectAvatarPushButton.clicked.connect(self.select_avatar)
        self.clearPushButton.clicked.connect(self.clear_avatar)
        self.savePushButton.clicked.connect(self.save)
        self.exitPushButton.clicked.connect(self.open_window_main)

        self.newPasswordLineEdit.textChanged.connect(self.password_validate)
        self.nicknameLineEdit.textChanged.connect(self.nickname_validate)
        self.showPasswordCheckBox.stateChanged.connect(self.change_mode_show_password)
        self.showNewPasswordCheckBox.stateChanged.connect(self.change_mode_show_new_password)
        self.passwordLineEdit.setEchoMode(QLineEdit.EchoMode.Password)
        self.newPasswordLineEdit.setEchoMode(QLineEdit.EchoMode.Password)

        self.load_data()

    # Функция сохранения данных
    def save(self):
        new_nickname = self.nicknameLineEdit.text()
        password = self.passwordLineEdit.text()
        new_password = self.newPasswordLineEdit.text()
        avatar = self.avatarTextEdit.toPlainText()

        if new_nickname != self.user[3]:
            if not self.nickname_validate():
                self.helper.show_message_box("Никнейм указан некорректно!", False)
                return

            query = f"""
                        UPDATE users
                        SET nickname = '{new_nickname}'
                        WHERE id = {self.user[0]}
                        """
            self.helper.db.execute_query(query)
            self.user[3] = new_nickname
            self.helper.show_message_box("Изменен никнейм!", False)

        if password != "":
            if not self.password_validate():
                self.helper.show_message_box("Пароль указан некорректно!", False)
                return

            if self.helper.db.get_sha256_hash(password) != self.user[2]:
                self.helper.show_message_box("Текущий пароль указан неверно!", False)
                return
            print(new_password)
            new_password = self.helper.db.get_sha256_hash(new_password)

            query = f"""
                        UPDATE users
                        SET password = '{new_password}'
                        WHERE id = {self.user[0]}
                        """
            self.helper.db.execute_query(query)
            self.user[2] = new_password
            self.helper.show_message_box("Изменен пароль!", False)
        else:
            if new_password:
                self.helper.show_message_box("Не указан текущий пароль!", False)
                return

        if os.path.exists(avatar):
            with open(avatar, 'rb') as file:
                image_data = file.read()
            image_data_encoded = base64.b64encode(image_data).decode('utf-8')

            query = f"""
                        UPDATE users
                        SET avatar = '{image_data_encoded}'
                        WHERE id = {self.user[0]}
                        """
            self.helper.db.execute_query(query)
            self.user[4] = image_data_encoded
            self.helper.show_message_box("Изменен аватар!", False)

        self.load_data()

    # Загрузка текущих данных пользователя
    def load_data(self):
        query = f"SELECT * FROM users WHERE id = {self.user[0]}"
        data = self.helper.db.execute_query(query)
        self.emailLineEdit.setText(data[1])
        self.nicknameLineEdit.setText(data[3])
        self.passwordLineEdit.clear()
        self.newPasswordLineEdit.clear()
        self.avatarTextEdit.clear()

        if self.user[4]:
            image_data = base64.b64decode(self.user[4])
            byte_array = QByteArray(image_data)
            pixmap = QPixmap()
            pixmap.loadFromData(byte_array)
            self.avatarImageLabel.setPixmap(pixmap)
        else:
            pixmap = QPixmap('data/default_avatar.jpg')
            self.avatarImageLabel.setPixmap(pixmap)
        print(self.helper.db.execute_query(query))
        print(self.user)

    # Открытие главного окна
    def open_window_main(self):
        self.window_main.show()
        self.close()

    # Функция проверки валидации поля password
    def password_validate(self):
        password = self.newPasswordLineEdit.text()

        if ((not re.match(self.helper.PASSWORD_PATTERN, password) or len(password) < 4 or len(password) > 20
             or not re.search(r'[A-Z]', password)) or not re.search(r'[a-z]', password)
                or not re.search(r'\d', password)):
            self.newPasswordLineEdit.setStyleSheet("background-color: red; color: white;")
            self.newPasswordStatusLabel.setText(f"Не подходит!")
            return False
        else:
            self.newPasswordStatusLabel.setText(f"")
            self.newPasswordLineEdit.setStyleSheet("background-color: white; color: black;")
            return True

    # Функция перевода режима показа пароля
    def change_mode_show_password(self, state):
        if state == 2:
            self.passwordLineEdit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.passwordLineEdit.setEchoMode(QLineEdit.EchoMode.Password)

    # Функция перевода режима показа нового пароля
    def change_mode_show_new_password(self, state):
        if state == 2:
            self.newPasswordLineEdit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            self.newPasswordLineEdit.setEchoMode(QLineEdit.EchoMode.Password)

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
        elif self.user[4]:
            image_data = base64.b64decode(self.user[4])
            byte_array = QByteArray(image_data)
            pixmap = QPixmap()
            pixmap.loadFromData(byte_array)
            self.avatarImageLabel.setPixmap(pixmap)
        else:
            self.avatarTextEdit.setText('')
            self.avatarImageLabel.clear()
            pixmap = QPixmap('data/default_avatar.jpg')
            self.avatarImageLabel.setPixmap(pixmap)

    # Удаление аватара
    def clear_avatar(self):
        yes = self.helper.show_message_box("Вы действительно хотите удалить аватар?", True)
        if yes:
            self.user[4] = None
            query = f"""
                        UPDATE users
                        SET avatar = NULL
                        WHERE id = {self.user[0]}
                        """
            self.helper.db.execute_query(query)
            self.helper.show_message_box("Аватар удалён!", False)
            self.load_data()
