import sqlite3
import re
import json
import ast
import math

from PyQt6.QtWidgets import (
    QMainWindow, QTableWidgetItem, QAbstractItemView,
    QMessageBox, QHeaderView
)
from PyQt6.uic import loadUi

from const import db
from pycode.exercises.fisic.adder import TaskTypeEditor


class ExerciseWindow(QMainWindow):
    partitions_id = None

    def __init__(self, main_obj):
        super().__init__()
        loadUi('pycode/exercises/fisic/fisic_interface_main.ui', self)

        self.update = False
        self.main_obj = main_obj

        # Инициализация компонентов
        self.exersiseText.textChanged.connect(self.update_variables)
        self.saveType.clicked.connect(self.save_exercise)

        # Настройка таблицы
        self.varsDiaposone.setColumnCount(5)
        self.varsDiaposone.setHorizontalHeaderLabels([
            'Переменная', 'Минимум', 'Максимум', 'Запрещенные', 'Размерность'
        ])
        self.varsDiaposone.setEditTriggers(QAbstractItemView.EditTrigger.AllEditTriggers)
        self.varsDiaposone.verticalHeader().setVisible(False)

        # Растягиваем столбцы на всю ширину таблицы
        header = self.varsDiaposone.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        # Словарь для хранения переменных
        self.variables = {}

        self.setWindowTitle("Конструктор по физике")

    def parse_scientific_notation(self, text):
        """
        Парсит строку в формате научной нотации:
        - "1.5e-3" или "1.5E-3"
        - "2.5×10^3" или "2.5*10^3"
        - "3.2e3"
        - обычные числа: "100", "0.005"
        """
        if not text.strip():
            return None

        text = text.strip().replace(',', '.').replace('×', '*').replace(' ', '')

        # Замена формата 10^ на e
        text = re.sub(r'(\d+\.?\d*)\*10\^([+-]?\d+)', r'\1e\2', text)
        text = re.sub(r'10\^([+-]?\d+)', r'1e\1', text)

        try:
            # Пробуем преобразовать в float
            return float(text)
        except ValueError:
            # Если не удалось, пытаемся разобрать другие форматы
            match = re.match(r'^([+-]?\d+\.?\d*)e([+-]?\d+)$', text, re.IGNORECASE)
            if match:
                coefficient = float(match.group(1))
                exponent = int(match.group(2))
                return coefficient * (10 ** exponent)

            raise ValueError(f"Некорректный формат числа: {text}")

    def format_number_display(self, value):
        """
        Форматирует число для отображения в таблице
        """
        if value is None:
            return ""

        if isinstance(value, (int, float)):
            if value == 0:
                return "0"
            elif abs(value) >= 10000 or (abs(value) < 0.001 and abs(value) > 1e-15):
                # Научная нотация для больших/малых чисел
                exponent = math.floor(math.log10(abs(value)))
                coefficient = value / (10 ** exponent)
                return f"{coefficient:.2f}×10^{exponent}"
            else:
                # Обычный формат
                if value == int(value):
                    return str(int(value))
                else:
                    return f"{value:.4f}".rstrip('0').rstrip('.')
        else:
            return str(value)

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
            if item and item.text() in out_vars:
                rows_to_delete.append(row)

        for row in sorted(rows_to_delete, reverse=True):
            self.varsDiaposone.removeRow(row)

        for var in new_vars:
            row_position = self.varsDiaposone.rowCount()
            self.varsDiaposone.insertRow(row_position)

            # Создаем редактируемые ячейки
            self.varsDiaposone.setItem(row_position, 0, QTableWidgetItem(var))
            self.varsDiaposone.setItem(row_position, 1, QTableWidgetItem('0'))
            self.varsDiaposone.setItem(row_position, 2, QTableWidgetItem('100'))
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
            return self._update_exercise()
        else:
            return self._create_exercise()

    def _create_exercise(self):
        """Создание нового упражнения"""
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
                return

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
            adder = TaskTypeEditor(exercise_data, main_obj=self.main_obj)
            adder.show()
            self.main_obj.cur_sub = adder
        except Exception as e:
            self.show_error(f"Ошибка сохранения: {str(e)}")

    def _update_exercise(self):
        """Обновление существующего упражнения"""
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
                    return

                exercise_data['variables'][var_name] = {
                    'min': var_min,
                    'max': var_max,
                    'forbidden': forbidden,
                    'dimension': dimension
                }

            params = json.dumps(exercise_data, ensure_ascii=False)

            sql_query = "UPDATE Partitions SET generation_parametrs = ? WHERE id = ?"
            cursor.execute(sql_query, (params, self.partitions_id))

            if cursor.rowcount == 0:
                QMessageBox.warning(self, "Предупреждение", "Запись не найдена в базе данных")
                return

            conn.commit()
            QMessageBox.information(self, "Успех", "Тип задания сохранён")
            self.close()
            self.update = False

    def edit_exercise(self, partitions_id, json_file):
        self.partitions_id = partitions_id
        self.update = True
        try:
            data = json.loads(json_file)

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

                # Заполняем ячейки таблицы с форматированием чисел
                self.varsDiaposone.setItem(row_position, 0, QTableWidgetItem(var_name))
                self.varsDiaposone.setItem(row_position, 1, QTableWidgetItem(
                    self.format_number_display(var_info.get('min', 0))
                ))
                self.varsDiaposone.setItem(row_position, 2, QTableWidgetItem(
                    self.format_number_display(var_info.get('max', 100))
                ))
                self.varsDiaposone.setItem(row_position, 3,
                                           QTableWidgetItem(', '.join(map(str, var_info.get('forbidden', []))))
                                           )
                self.varsDiaposone.setItem(row_position, 4, QTableWidgetItem(var_info.get('dimension', '')))

                # Сохраняем переменные в словарь
                self.variables[var_name] = {
                    'min': var_info.get('min', 0),
                    'max': var_info.get('max', 100),
                    'forbidden': var_info.get('forbidden', []),
                    'dimension': var_info.get('dimension', '')
                }

        except FileNotFoundError:
            self.show_error("Файл не найден!")
        except json.JSONDecodeError:
            self.show_error("Ошибка декодирования JSON!")
        except Exception as e:
            self.show_error(f"Произошла ошибка: {str(e)}")

    def validate_number(self, row, column):
        """Валидация чисел с поддержкой научной нотации"""
        item = self.varsDiaposone.item(row, column)
        if not item:
            return None

        text = item.text().strip()
        if not text:
            return None

        try:
            value = self.parse_scientific_notation(text)

            # Обновляем отображение в таблице для согласованности
            formatted_value = self.format_number_display(value)
            if formatted_value != text:
                self.varsDiaposone.setItem(row, column, QTableWidgetItem(formatted_value))

            return value

        except ValueError as e:
            self.show_error(f"Некорректное число в строке {row + 1}, колонке {column + 1}: {str(e)}")
            return None

    def parse_forbidden(self, row, column):
        """Парсит запрещенные значения с поддержкой научной нотации"""
        item = self.varsDiaposone.item(row, column)
        if not item:
            return []

        forbidden_values = []
        for x in item.text().split(','):
            x = x.strip()
            if x:
                try:
                    value = self.parse_scientific_notation(x)
                    forbidden_values.append(value)
                except ValueError:
                    # Если не удалось распарсить, оставляем как строку
                    forbidden_values.append(x)

        return forbidden_values

    def validate_formula(self, formula, allowed_vars):
        """Валидация формулы"""
        allowed = allowed_vars | {'sqrt', 'sin', 'cos', 'tan', 'log', 'log10', 'log2',
                                  'exp', 'pi', 'e', 'g', 'G', 'R', 'k'}
        try:
            syntax_tree = ast.parse(formula, mode='eval')
            for node in ast.walk(syntax_tree):
                if isinstance(node, ast.Name):
                    if node.id not in allowed:
                        raise ValueError(f"Недопустимый идентификатор в формуле: {node.id}")
        except SyntaxError:
            raise ValueError("Некорректный синтаксис формулы")

    def show_error(self, message):
        QMessageBox.critical(self, 'Ошибка', message)