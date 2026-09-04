"""
Выбор размещения ответов — один виджет на все представления выгрузки.

Почему виджет, а не три выпадающих списка
------------------------------------------
Подписи и пояснения здесь — не оформление, а описание того, что человек
получит на бумаге. Три копии этих подписей разошлись бы в формулировках,
и «в конце варианта» на одном экране начало бы значить не то же, что на
другом. Ровно так уже разошлись сами раскладки: у теста ответы
назывались «Эталон ответов», у таблицы — «Ответы».

Порядок и тексты совпадают с веб-диалогом
(`frontend/src/components/ExportDialog.tsx`) намеренно: преподаватель,
привыкший к вебу, не должен разбираться заново.
"""

from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QWidget

from core.export_api import ANSWER_PLACEMENTS

#: Размещение → (подпись, пояснение). Порядок — от самого
#: «преподавательского» к студенческому, как и в `ANSWER_PLACEMENTS`.
CHOICES: dict[str, tuple[str, str]] = {
    "under": (
        "Ответы под заданием",
        "Удобно себе для проверки; раздавать такой лист нельзя — "
        "ключ на виду.",
    ),
    "variant_end": (
        "Ответы в конце варианта",
        "Ключ к каждому варианту отдельной страницей — можно оторвать.",
    ),
    "file_end": (
        "Ответы в конце файла",
        "Все ответы одной пачкой в конце, с указанием варианта.",
    ),
    "hidden": (
        "Без ответов",
        "Только условия — лист для студентов.",
    ),
}


class AnswerPlacementBox(QComboBox):
    """Выпадающий список размещений. Значение — код из `ANSWER_PLACEMENTS`."""

    def __init__(self, parent: QWidget | None = None,
                 default: str = "file_end"):
        super().__init__(parent)
        for code in ANSWER_PLACEMENTS:
            label, hint = CHOICES[code]
            self.addItem(label, code)
            self.setItemData(self.count() - 1, hint, 3)   # Qt.ToolTipRole
        self.set_placement(default)
        self.currentIndexChanged.connect(self._refresh_hint)
        self._refresh_hint()

    def placement(self) -> str:
        """Выбранный код размещения."""
        return str(self.currentData())

    def set_placement(self, code: str) -> None:
        index = self.findData(code)
        if index >= 0:
            self.setCurrentIndex(index)

    def _refresh_hint(self) -> None:
        """
        Пояснение к ВЫБРАННОМУ — на самом списке.

        Без него подсказка видна только когда список раскрыт, то есть
        ровно тогда, когда выбор ещё не сделан. А знать, что «ответы под
        заданием» раздавать нельзя, надо после выбора.
        """
        _label, hint = CHOICES.get(self.placement(), ("", ""))
        self.setToolTip(hint)
