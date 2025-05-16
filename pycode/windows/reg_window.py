# Импорт библиотек
import pycode.helper as hp
from PyQt6 import uic
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QLineEdit, QProgressDialog
from PyQt6.QtCore import QThread, pyqtSignal, Qt
import requests
import json


class RegistrationThread(QThread):
    """Поток для выполнения асинхронной регистрации"""
    finished = pyqtSignal(dict)  # Сигнал с результатом регистрации
    error = pyqtSignal(str)  # Сигнал с ошибкой

    def __init__(self, register_data):
        super().__init__()
        self.register_data = register_data

    def run(self):
        try:
            response = requests.post(
                'http://localhost:8080/register',
                headers={'Content-Type': 'application/json'},
                data=json.dumps(self.register_data),
                timeout=10  # Таймаут 10 секунд
            )
            self.finished.emit({
                'status_code': response.status_code,
                'response': response.json()
            })
        except requests.exceptions.RequestException as e:
            self.error.emit(f"Ошибка сети: {str(e)}")
        except json.JSONDecodeError as e:
            self.error.emit(f"Ошибка разбора JSON: {str(e)}")
        except Exception as e:
            self.error.emit(f"Неизвестная ошибка: {str(e)}")


class RegWindow(QMainWindow):
    def __init__(self):
        """Конструктор"""
        super().__init__()

        self.login = None
        self.password = None
        self.email = None
        self.fio = None
        self.group = None
        self.student = None
        self.mainObject = None

        # Настройка окна
        uic.loadUi('resources/templates/reg_window.ui', self)
        self.setWindowIcon(QIcon("resources/icon.png"))
        self.setWindowTitle("Регистрация")
        self.passwordInput.setEchoMode(QLineEdit.EchoMode.Password)

        # Обработчики событий
        self.exitButton.clicked.connect(self.close)
        self.registrateButton.clicked.connect(self.inputLogAndPass)
        self.authButton.clicked.connect(self.auth)

    def inputLogAndPass(self):
        self.login = self.loginInput.text()
        self.password = self.passwordInput.text()
        self.fio = self.fioInput.text()
        self.group = self.groupInput.text()

        # Проверка заполнения обязательных полей
        if not self.login:
            self.show_message("Введите логин", "Information")
            return
        if not self.password:
            self.show_message("Введите пароль", "Information")
            return

        # Показываем диалог загрузки
        self.show_loading_dialog("Регистрация...")

        # Данные для регистрации
        register_data = {
            'login': self.login,
            'password': self.password,
            'email': self.email,
            'FIO': self.fio,
            'group': self.group,
            'student': self.student
        }

        # Создаем и запускаем поток регистрации
        self.thread = RegistrationThread(register_data)
        self.thread.finished.connect(self.handle_registration_result)
        self.thread.error.connect(self.handle_registration_error)
        self.thread.start()

    def show_loading_dialog(self, message):
        """Показывает диалоговое окно загрузки"""
        self.progress_dialog = QProgressDialog(message, None, 0, 0, self)
        self.progress_dialog.setWindowTitle("Пожалуйста, подождите")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setCancelButton(None)
        self.progress_dialog.show()

    def show_message(self, text, message_type):
        """Показывает информационное сообщение"""
        message_box = hp.show_message(
            text=text,
            message_type=message_type,
            icon=message_type
        )
        message_box.exec()

    def handle_registration_result(self, result):
        """Обрабатывает результат регистрации"""
        self.progress_dialog.close()

        status_code = result['status_code']
        response = result['response']

        if status_code == 201:
            self.clear_inputs()
            self.go_to_generator()
        elif status_code == 400:
            self.show_message(response.get('error', 'Логин уже занят'), "Information")
        else:
            self.show_message(f"Ошибка регистрации: {response.get('error', 'Неизвестная ошибка')}", "Critical")

    def handle_registration_error(self, error_msg):
        """Обрабатывает ошибку регистрации"""
        self.progress_dialog.close()
        self.show_message(error_msg, "Critical")

    def clear_inputs(self):
        """Очищает поля ввода"""
        self.loginInput.setText("")
        self.passwordInput.setText("")
        self.fioInput.setText("")
        self.groupInput.setText("")

    def auth(self):
        self.mainObject.change_cur_obj(self.mainObject.auth)

    def go_to_generator(self):
        self.mainObject.change_cur_obj(self.mainObject.generator)

    def open_about_app_dialog(self):
        """Открытие диалогового окна"""
        self.show_message("О программе", "Information")
