# Импорт библиотек
import pycode.helper as hp
from PyQt6 import uic
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMainWindow, QMessageBox, QProgressDialog, QLineEdit
from PyQt6.QtCore import QThread, pyqtSignal, Qt
import requests


class AuthRequestThread(QThread):
    """Поток для выполнения асинхронного запроса авторизации"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, login, password):
        super().__init__()
        self.login = login
        self.password = password

    def run(self):
        try:
            st_accept = "text/html"
            headers = {"Accept": st_accept}
            data = requests.get("http://localhost:8080/get_users", headers).json()
            self.finished.emit({"data": data})
        except Exception as e:
            self.error.emit(str(e))


class AuthWindow(QMainWindow):
    """Класс окна авторизации"""

    def __init__(self):
        """Конструктор"""
        super().__init__()

        self.login = None
        self.password = None
        self.mainObject = None

        # Настройка окна
        uic.loadUi('resources/templates/auth_window.ui', self)
        self.setWindowIcon(QIcon("resources/icon.png"))

        self.passwordInput.setEchoMode(QLineEdit.EchoMode.Password)

        # Обработчики событий
        self.actionAboutApp.triggered.connect(self.open_about_app_dialog)
        self.exitButton.clicked.connect(self.close)
        self.enterButton.clicked.connect(self.inputLogAndPass)
        self.registrtionButton.clicked.connect(self.registration)
        self.guestButton.clicked.connect(self.go_to_generator)

    def inputLogAndPass(self):
        self.login = self.loginInput.text()
        self.password = self.passwordInput.text()
        # Создаем и показываем диалог загрузки
        self.progress_dialog = QProgressDialog("Проверка авторизации...", "Отмена", 0, 0, self)
        self.progress_dialog.setWindowTitle("Загрузка")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setCancelButton(None)  # Убираем кнопку отмены
        self.progress_dialog.show()

        # Создаем и запускаем поток для запроса
        self.auth_thread = AuthRequestThread(self.login, self.password)
        self.auth_thread.finished.connect(self.handle_auth_result)
        self.auth_thread.error.connect(self.handle_auth_error)
        self.auth_thread.start()

    def go_to_generator(self):
        self.mainObject.change_cur_obj(self.mainObject.generator)

    def registration(self):
        self.mainObject.change_cur_obj(self.mainObject.reg)

    def handle_auth_result(self, data):
        """Обработка результата авторизации"""
        self.progress_dialog.close()
        data = data["data"]
        if (self.login, self.password) in [tuple(i.values()) for i in data]:
            self.go_to_generator()
        else:
            hp.show_message("Ошибка авторизации", "Неверный логин или пароль", "Ошибка",
                            "Critical", ['Ok'], 'Critical').exec()

        self.loginInput.setText("")
        self.passwordInput.setText("")

    def handle_auth_error(self, error_msg):
        """Обработка ошибки при авторизации"""
        self.progress_dialog.close()
        hp.show_message("Ошибка соединения", f"Не удалось подключиться к серверу: {error_msg}", "Ошибка",
                        "Critical", ['Ok'], 'Critical').exec()

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


if __name__ == "__main__":
    au = AuthWindow()