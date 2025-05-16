from PyQt6 import uic
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QDialog


# Инициализация класса
class DialogAboutApp(QDialog):
    # Функция инициализации
    def __init__(self, helper):
        super().__init__()
        self.helper = helper
        self.initUI()

    # Функция инилизации интерфейса
    def initUI(self):
        # Загрузка шаблона
        uic.loadUi('templates/dialog_about_app.ui', self)

        # Загрузка иконки
        self.setWindowIcon(QIcon('icon.png'))

        self.nameLabel.setText(self.helper.name_app)
        pixmap = QPixmap("icon.png")
        self.logoLabel.setPixmap(pixmap)

        text = "Простое демо-приложения для демонстрации работы базы данных и авторизации."
        text += "\n\n Разработчик: Иванов И.И."
        self.infoTextEdit.setText(text)

        self.okPushButton.clicked.connect(self.close_dialog)

    # Функция закрытия диалога
    def close_dialog(self):
        self.close()
