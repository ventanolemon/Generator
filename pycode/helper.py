from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtGui import QIcon


def show_message(text, info_text="", title="Система",
                 message_type="Information",
                 buttons=['Ok'],
                 icon='Information'):
    """
    Улучшенная версия функции для отображения сообщений с настройками

    Параметры:
        text (str): Основной текст сообщения
        info_text (str): Дополнительный информационный текст
        title (str): Заголовок окна
        message_type (str): Тип сообщения ('Information', 'Warning', 'Critical', 'Question', 'About')
        buttons (list): Список кнопок ['Ok', 'Cancel', 'Yes', 'No', ...]
        icon (str): Тип иконки ('Information', 'Warning', 'Critical', 'Question', 'NoIcon')

    Возвращает:
        QMessageBox: настроенный диалог
    """
    msg = QMessageBox()
    msg.setWindowTitle(title)
    msg.setText(text)

    # Установка иконки окна
    try:
        msg.setWindowIcon(QIcon("resources/icon.png"))
    except:
        pass  # Если иконка не найдена, продолжаем без неё

    # Установка типа сообщения и иконки
    icon_mapping = {
        'Information': QMessageBox.Icon.Information,
        'Warning': QMessageBox.Icon.Warning,
        'Critical': QMessageBox.Icon.Critical,
        'Question': QMessageBox.Icon.Question,
        'NoIcon': QMessageBox.Icon.NoIcon
    }
    msg.setIcon(icon_mapping.get(icon, QMessageBox.Icon.Information))

    # Установка дополнительного текста
    if info_text:
        msg.setInformativeText(info_text)

    # Маппинг кнопок из строк в StandardButton
    button_mapping = {
        'Ok': QMessageBox.StandardButton.Ok,
        'Open': QMessageBox.StandardButton.Open,
        'Save': QMessageBox.StandardButton.Save,
        'Cancel': QMessageBox.StandardButton.Cancel,
        'Close': QMessageBox.StandardButton.Close,
        'Yes': QMessageBox.StandardButton.Yes,
        'No': QMessageBox.StandardButton.No,
        'Abort': QMessageBox.StandardButton.Abort,
        'Retry': QMessageBox.StandardButton.Retry,
        'Ignore': QMessageBox.StandardButton.Ignore
    }

    # Русские названия кнопок
    button_texts = {
        'Ok': "ОК",
        'Open': "Открыть",
        'Save': "Сохранить",
        'Cancel': "Отмена",
        'Close': "Закрыть",
        'Yes': "Да",
        'No': "Нет",
        'Abort': "Прервать",
        'Retry': "Повторить",
        'Ignore': "Игнорировать"
    }

    # Собираем стандартные кнопки
    standard_buttons = QMessageBox.StandardButton.NoButton
    for btn in buttons:
        if btn in button_mapping:
            standard_buttons |= button_mapping[btn]

    msg.setStandardButtons(standard_buttons)

    # Устанавливаем русские названия кнопок
    for btn in buttons:
        if btn in button_mapping and btn in button_texts:
            button = msg.button(button_mapping[btn])
            if button:  # Проверка на случай, если кнопка не была создана
                button.setText(button_texts[btn])

    return msg