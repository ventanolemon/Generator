# Импорт библиотек
import pycode.helper as hp
from PyQt6 import uic
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QMessageBox
import sqlite3


class RegWindow(QMainWindow):
    def __init__(self):
        """Конструктор"""
        super().__init__()

        self.login = None
        self.password = None
        self.mainObject = None

        # Настройка окна
        uic.loadUi('resources/templates/reg_window.ui', self)
        self.setWindowIcon(QIcon("resources/icon.png"))

        # Обработчики событий
        # self.actionAboutApp.triggered.connect(self.open_about_app_dialog)
        self.exitButton.clicked.connect(self.close)
        self.registrateButton.clicked.connect(self.inputLogAndPass)
        self.authButton.clicked.connect(self.auth)

    def inputLogAndPass(self):
        self.login = self.loginInput.text()
        self.password = self.passwordInput.text()
        if not self.login:
            message_box = hp.show_message(
                text="Введите логин",
                message_type="Information",  # Тип сообщения - вопрос
                icon='Information'  # Иконка вопроса
            )
            message_box.exec()
            return None
        if not self.password:
            message_box = hp.show_message(
                text="Введите пароль",
                message_type="Information",  # Тип сообщения - вопрос
                icon='Information'  # Иконка вопроса
            )
            message_box.exec()
            return None
        with sqlite3.connect("resources/users_database.db") as db:
            cur = db.cursor()
            # print(cur.execute("SELECT login FROM users").fetchall())
            try:
                cur.execute(f"INSERT INTO users VALUES ('{self.login}', '{self.password}')")
                print("yeeee")
            except sqlite3.IntegrityError:
                message_box = hp.show_message(
                    text="Логин уже занят",
                    message_type="Information",  # Тип сообщения - вопрос
                    icon='Information'  # Иконка вопроса
                )
                message_box.exec()
        self.loginInput.setText("")
        self.passwordInput.setText("")

        print(self.login, self.password)

    def auth(self):
        self.mainObject.change_cur_obj(self.mainObject.auth)

    def open_about_app_dialog(self):
        """Открытие диалогового окна"""
        hp.show_message("О программе", "Инфо", "Ошибка",
                        "Critical", ['Ok'], 'Critical').exec()

        # 1. Создаем диалог с вопросом и кнопками Да/Нет
        message_box = hp.show_message(
            text="Вы уверены, что хотите продолжить?",
            message_type="Question",  # Тип сообщения - вопрос
            buttons=['Yes', 'No'],  # Кнопки Да и Нет
            icon='Question'  # Иконка вопроса
        )

        # 2. Показываем диалог и ждем выбора пользователя
        result = message_box.exec()

        # 3. Обрабатываем результат
        if result == QMessageBox.StandardButton.Yes:
            print("Пользователь выбрал Да")
            # Здесь код, который выполняется при выборе "Да"
            # Например:
            # self.save_data()
            # self.close_window()
            # self.process_operation()
        else:
            print("Пользователь выбрал Нет")
            # Здесь код, который выполняется при выборе "Нет"
            # Например:
            # self.cancel_operation()
            # self.show_warning("Операция отменена")
