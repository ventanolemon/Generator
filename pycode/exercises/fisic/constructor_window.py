import sqlite3

from PyQt6.QtWidgets import (
    QMainWindow,
    QTableWidgetItem,
    QAbstractItemView,
    QMessageBox, QHeaderView, QWidget
)
from PyQt6.uic import loadUi
import json
import re
import ast  # Добавлен импорт модуля ast

from pycode.exercises.fisic.adder import TaskTypeEditor


db = r'C:\Users\happy\PycharmProjects\PythonProject4\resources\users_database.db'
class ExerciseWindow(QMainWindow):
    partitions_id = None

    def __init__(self, main_obj):
        super().__init__()
        loadUi('pycode/exercises/fisic/fisic_interface_main.ui', self)  # загружаем UI файл

        self.update = False

        # Инициализация компонентов
        self.exersiseText.textChanged.connect(self.update_variables)
        self.saveType.clicked.connect(self.save_exercise)

        # Настройка таблицы с возможностью редактирования
        self.varsDiaposone.setColumnCount(5)
        self.varsDiaposone.setHorizontalHeaderLabels(
            ['Переменная',
            'Минимум',
            'Максимум',
            'Запрещенные',
            'Размерность']
        )
        self.varsDiaposone.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.varsDiaposone.verticalHeader().setVisible(False)

        # Растягиваем столбцы на всю ширину таблицы
        header = self.varsDiaposone.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        # Словарь для хранения переменных
        self.variables = {}

        self.setWindowTitle("Конструктор по физике")

        self.main_obj = main_obj


    def update_variables(self):
        text = self.exersiseText.toPlainText()
        found_vars = re.findall(r'#(\w+)#', text)
        self.update_table(found_vars)

    def update_table(self, found_vars):
        current_vars = set(self.get_table_variables())
        new_vars = set(found_vars) - current_vars

        out_vars = current_vars - set(found_vars)
        rows_to_delete = []
        for row in range(self.varsDiaposone.rowCount()):
            item = self.varsDiaposone.item(row, 0)

            if item:
                # Проверяем, содержится ли значение в множестве
                if item.text() in out_vars:
                    rows_to_delete.append(row)
        for row in sorted(rows_to_delete):
            self.varsDiaposone.removeRow(row)

        for var in new_vars:
            row_position = self.varsDiaposone.rowCount()
            self.varsDiaposone.insertRow(row_position)

            # Создаем редактируемые ячейки
            self.varsDiaposone.setItem(row_position, 0, QTableWidgetItem(var))
            self.varsDiaposone.setItem(row_position, 1, QTableWidgetItem('0'))  # значение по умолчанию
            self.varsDiaposone.setItem(row_position, 2, QTableWidgetItem('100'))  # значение по умолчанию
            self.varsDiaposone.setItem(row_position, 3, QTableWidgetItem(''))
            self.varsDiaposone.setItem(row_position, 4, QTableWidgetItem(''))

            # Сохраняем переменную в словарь
            self.variables[var] = {
                'min': 0,
                'max': 100,
                'forbidden': [],
                'dimension': ''
            }

    def get_table_variables(self):
        variables = []
        for row in range(self.varsDiaposone.rowCount()):
            item = self.varsDiaposone.item(row, 0)
            if item:
                variables.append(item.text())
        return variables

    def save_exercise(self):
        if self.update:
            with sqlite3.connect(db) as conn:
                exercise_data = {
                    'condition': self.exersiseText.toPlainText().strip(),
                    'result_letter': self.resultLetter.text().strip(),
                    'formula': self.resultFormula.toPlainText().strip(),
                    'dimension': self.resultRasm.text().strip(),
                    'variables': {}
                }
                cursor = conn.cursor()

                for row in range(self.varsDiaposone.rowCount()):
                    var_name = self.varsDiaposone.item(row, 0).text().strip()
                    var_min = self.validate_number(row, 1)
                    var_max = self.validate_number(row, 2)
                    forbidden = self.parse_forbidden(row, 3)
                    dimension = self.varsDiaposone.item(row, 4).text().strip()

                    if var_min is None or var_max is None:
                        return  # Валидация уже показала ошибку

                    exercise_data['variables'][var_name] = {
                        'min': var_min,
                        'max': var_max,
                        'forbidden': forbidden,
                        'dimension': dimension
                    }
                params = json.dumps(exercise_data)

                sql_query = """
                                UPDATE Partitions 
                                SET constracted = ?, generation_parametrs = ?
                                WHERE id = ?
                                """
                cursor.execute(
                    sql_query,
                    (1, params, self.partitions_id))
                rows_affected = cursor.rowcount

                if rows_affected == 0:
                    QMessageBox.warning(self, "Предупреждение", "Запись не найдена в базе данных")
                    return
                conn.commit()
                # self.saved.emit()
                QMessageBox.information(self, "Успех", "Тип задания сохранён")
                self.close()
                self.update = False
                return None

        exercise_data = {
            'condition': self.exersiseText.toPlainText().strip(),
            'result_letter': self.resultLetter.text().strip(),
            'formula': self.resultFormula.toPlainText().strip(),
            'dimension': self.resultRasm.text().strip(),
            'variables': {}
        }

        # Проверка обязательных полей
        if not exercise_data['condition']:
            self.show_error("Условие задачи не может быть пустым!")
            return

        if not exercise_data['result_letter']:
            self.show_error("Укажите букву для результата!")
            return

        # Проверка совпадения переменных
        used_vars = set(re.findall(r'#(\w+)#', exercise_data['condition']))
        table_vars = set(self.get_table_variables())

        if missing_vars := used_vars - table_vars:
            self.show_error(f"Отсутствуют переменные: {', '.join(missing_vars)}")
            return

        # Собираем данные переменных из таблицы
        for row in range(self.varsDiaposone.rowCount()):
            var_name = self.varsDiaposone.item(row, 0).text().strip()
            var_min = self.validate_number(row, 1)
            var_max = self.validate_number(row, 2)
            forbidden = self.parse_forbidden(row, 3)
            dimension = self.varsDiaposone.item(row, 4).text().strip()

            if var_min is None or var_max is None:
                return  # Валидация уже показала ошибку

            exercise_data['variables'][var_name] = {
                'min': var_min,
                'max': var_max,
                'forbidden': forbidden,
                'dimension': dimension
            }

        # Проверка формулы
        if exercise_data['formula']:
            try:
                self.validate_formula(exercise_data['formula'], table_vars)
            except ValueError as e:
                self.show_error(str(e))
                return

        # Сохранение данных
        try:
            # print(exercise_data)
            adder = TaskTypeEditor(exercise_data, main_obj=self.main_obj)
            adder.show()
            self.main_obj.cur_sub = adder

            # self.save_to_file(exercise_data)
            # QMessageBox.information(self, 'Успех', 'Данные успешно сохранены!')
        except Exception as e:
            self.show_error(f"Ошибка сохранения: {str(e)}")

    def edit_exercise(self, partitions_id, json_file):
        self.partitions_id = partitions_id
        self.update = True
        try:
            # Читаем JSON файл
            # with open(json_file_path, 'r', encoding='utf-8') as file:
            data = json.loads(json_file)

            # print(data)

            # Заполняем основные поля
            self.exersiseText.setPlainText(data.get('condition', ''))
            self.resultLetter.setText(data.get('result_letter', ''))
            self.resultFormula.setPlainText(data.get('formula', ''))
            self.resultRasm.setText(data.get('dimension', ''))

            # Очищаем таблицу перед заполнением новыми данными
            self.varsDiaposone.setRowCount(0)
            self.variables.clear()

            # Заполняем таблицу переменных
            variables_data = data.get('variables', {})
            for var_name, var_info in variables_data.items():
                row_position = self.varsDiaposone.rowCount()
                self.varsDiaposone.insertRow(row_position)

                # Заполняем ячейки таблицы
                self.varsDiaposone.setItem(row_position, 0, QTableWidgetItem(var_name))
                self.varsDiaposone.setItem(row_position, 1, QTableWidgetItem(str(var_info.get('min', 0))))
                self.varsDiaposone.setItem(row_position, 2, QTableWidgetItem(str(var_info.get('max', 100))))
                self.varsDiaposone.setItem(row_position, 3,
                                           QTableWidgetItem(', '.join(map(str, var_info.get('forbidden', [])))))
                self.varsDiaposone.setItem(row_position, 4, QTableWidgetItem(var_info.get('dimension', '')))

                # Сохраняем переменные в словарь
                self.variables[var_name] = {
                    'min': var_info.get('min', 0),
                    'max': var_info.get('max', 100),
                    'forbidden': var_info.get('forbidden', []),
                    'dimension': var_info.get('dimension', '')
                }

            # QMessageBox.information(self, 'Успех', 'Данные успешно загружены!')

        except FileNotFoundError:
            self.show_error("Файл не найден!")
        except json.JSONDecodeError:
            self.show_error("Ошибка декодирования JSON!")
        except Exception as e:
            self.show_error(f"Произошла ошибка: {str(e)}")

    # Вспомогательные методы
    def validate_number(self, row, column):
        item = self.varsDiaposone.item(row, column)
        if not item:
            return None

        text = item.text().strip()
        try:
            return float(text) if text else None
        except ValueError:
            self.show_error(f"Некорректное число в строке {row+1}, колонке {column+1}")
            return None

    def parse_forbidden(self, row, column):
        item = self.varsDiaposone.item(row, column)
        if not item:
            return []

        return [x.strip() for x in item.text().split(',') if x.strip()]

    def validate_formula(self, formula, allowed_vars):
        allowed = allowed_vars | {'sqrt', 'sin', 'cos', 'tan', 'log', 'g', 'G'}  # Разрешенные функции
        try:
            # Безопасная проверка формулы
            syntax_tree = ast.parse(formula, mode='eval')

            for node in ast.walk(syntax_tree):
                if isinstance(node, ast.Name):
                    if node.id not in allowed:
                        raise ValueError(f"Недопустимый идентификатор в формуле: {node.id}")
        except SyntaxError:
            raise ValueError("Некорректный синтаксис формулы")

    def save_to_file(self, data):
        # Пример сохранения в JSON
        with open('exercise.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def show_error(self, message):
        QMessageBox.critical(self, 'Ошибка', message)

