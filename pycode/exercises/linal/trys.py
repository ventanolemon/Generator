from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QComboBox,
    QPushButton,
    QMessageBox
)
from PyQt6.QtCore import Qt
import json
import os


class CascadingMenuApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.menu_data = self.load_menu_data('menu_data.json')
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Каскадное меню из JSON')
        self.setGeometry(200, 200, 800, 150)

        # Основной контейнер
        self.central = QWidget()
        self.setCentralWidget(self.central)
        self.layout = QHBoxLayout(self.central)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        # Инициализация первого меню
        self.create_first_menu()

    def load_menu_data(self, filename):
        """Загрузка структуры меню из JSON файла"""
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Преобразование JSON данных в правильный формат
            return {key: value if isinstance(value, list) else []
                    for key, value in data.items()}

        except Exception as e:
            QMessageBox.critical(
                self,
                'Ошибка',
                f'Не удалось загрузить данные меню: {str(e)}'
            )
            return {}

    def create_first_menu(self):
        """Создание начального выпадающего списка"""
        self.clear_layout()
        if not self.menu_data:
            return

        first_menu = QComboBox()
        first_menu.addItems(self.menu_data.get('Основное меню', []))
        first_menu.currentIndexChanged.connect(self.update_menus)
        self.layout.addWidget(first_menu)

    def update_menus(self):
        """Обновление цепочки меню при изменении выбора"""
        # Удаляем старые меню после текущего
        sender = self.sender()
        current_index = self.layout.indexOf(sender)

        while self.layout.count() > current_index + 1:
            item = self.layout.takeAt(current_index + 1)
            if item.widget():
                item.widget().deleteLater()

        # Получаем текущий путь выбора
        selected_path = []
        for i in range(current_index + 1):
            menu = self.layout.itemAt(i).widget()
            selected_path.append(menu.currentText())

        # Получаем следующие варианты из JSON данных
        current_key = selected_path[-1]
        next_items = self.menu_data.get(current_key, [])

        if next_items:
            new_menu = QComboBox()
            new_menu.addItems(next_items)
            new_menu.currentIndexChanged.connect(self.update_menus)
            self.layout.addWidget(new_menu)
        else:
            confirm_btn = QPushButton('Подтвердить выбор')
            confirm_btn.clicked.connect(self.show_selection)
            self.layout.addWidget(confirm_btn)

    def show_selection(self):
        """Вывод итогового выбора"""
        result = []
        for i in range(self.layout.count()):
            widget = self.layout.itemAt(i).widget()
            if isinstance(widget, QComboBox):
                result.append(widget.currentText())

        QMessageBox.information(
            self,
            'Выбор завершен',
            f'Ваш выбор: {" → ".join(result)}'
        )
        self.create_first_menu()

    def clear_layout(self):
        """Полная очистка layout"""
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


if __name__ == '__main__':
    app = QApplication([])
    ex = CascadingMenuApp()
    ex.show()
    app.exec()
