"""
Холст графа следует теме приложения — и остаётся читаемым в обеих.

Дефект был виден глазами: при переключении на светлую тему холст
оставался чёрным. Причина не в забытом вызове, а в устройстве: цвета
холста были константами и ставились кистью один раз при создании сцены,
а QSS до QGraphicsScene не доходит.

Чинить это вторым набором «светлых» констант нельзя — он разошёлся бы с
темой при первой её правке (ровно так разошёлся первый). Поэтому цвета
ВЫВОДЯТСЯ из палитры, а проверяется здесь не «какие получились числа», а
свойства, которые обязаны выполняться при любой палитре:

    1. смена темы меняет фон холста — и у уже открытой сцены;
    2. на этом фоне видно провода, текст и заголовки.

Второе — числом, а не на глаз. Замер и нашёл то, чего не было видно из
кода: салатовый провод (#9CCC65) на белом холсте давал контраст 1.5, а
заголовок узла в светлой теме рисовался тёмным текстом по тёмной
заливке — цвет категории от темы не зависит, а цвет текста зависел.

Запуск:
    python -m unittest tests.test_canvas_theme
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor

from ui.editors.graph_canvas import style
from ui.theme import DARK, LIGHT, apply_theme


#: Порог для ЛИНИЙ: провод — штрих в 2.4 пикселя, ему хватает меньшего
#: запаса, чем букве. Ниже этого провод сливается с холстом.
WIRE_MIN = 2.2
#: Порог для ТЕКСТА: подписи портов, сводка, заголовок.
TEXT_MIN = 4.0

THEMES = (("тёмная", DARK), ("светлая", LIGHT))


class ContrastTests(unittest.TestCase):
    """При любой теме на холсте всё должно быть видно."""

    def tearDown(self):
        style.apply_palette(DARK)

    def test_wires_are_visible_on_the_canvas(self):
        for name, palette in THEMES:
            style.apply_palette(palette)
            for port_type, color in style.PORT_COLORS.items():
                with self.subTest(тема=name, тип=port_type.name):
                    self.assertGreaterEqual(
                        style.contrast(color, style.SCENE_BG), WIRE_MIN,
                        f"{color.name()} на {style.SCENE_BG.name()}")

    def test_branch_highlight_is_visible(self):
        for name, palette in THEMES:
            style.apply_palette(palette)
            for key, color in style.BRANCH_COLORS.items():
                with self.subTest(тема=name, ветка=key):
                    self.assertGreaterEqual(
                        style.contrast(color, style.SCENE_BG), WIRE_MIN)

    def test_node_texts_are_readable(self):
        for name, palette in THEMES:
            style.apply_palette(palette)
            pairs = {
                "подписи портов": (style.NODE_TEXT, style.NODE_BG),
                "сводка узла": (style.SUMMARY_TEXT, style.SUMMARY_BG),
                "подпись провода": (style.EDGE_NOTE_TEXT, style.SCENE_BG),
                "текст комментария": (style.COMMENT_TEXT, style.SCENE_BG),
            }
            for what, (fg, bg) in pairs.items():
                with self.subTest(тема=name, что=what):
                    self.assertGreaterEqual(style.contrast(fg, bg), TEXT_MIN)

    def test_header_text_is_readable_on_every_category(self):
        """
        Тот самый случай, который поймал замер: заливка заголовка от темы
        не зависит, а цвет текста зависел — в светлой теме выходило
        тёмное по тёмному.
        """
        for name, palette in THEMES:
            style.apply_palette(palette)
            for category, fill in style.CATEGORY_COLORS.items():
                with self.subTest(тема=name, категория=category):
                    self.assertGreaterEqual(
                        style.contrast(style.on_color(fill), fill), TEXT_MIN)

    def test_the_old_fixed_palette_did_fail(self):
        """
        Регрессия наоборот. Без неё проверки выше не отличаются от
        «так было всегда».
        """
        white = QColor("#FFFFFF")
        salad = QColor("#9CCC65")          # PortType.LIST до правки
        self.assertLess(style.contrast(salad, white), WIRE_MIN)
        dark_text = QColor(LIGHT.text)     # цвет текста светлой темы
        dark_fill = QColor("#6C3483")      # заливка категории «source»
        self.assertLess(style.contrast(dark_text, dark_fill), TEXT_MIN)


class MeaningTests(unittest.TestCase):
    """Тон — часть языка графа; меняется только светлота."""

    def tearDown(self):
        style.apply_palette(DARK)

    def test_hue_survives_the_theme(self):
        hues = {}
        for name, palette in THEMES:
            style.apply_palette(palette)
            hues[name] = {t: c.hue() for t, c in style.PORT_COLORS.items()}
        for port_type in hues["тёмная"]:
            with self.subTest(тип=port_type.name):
                self.assertEqual(hues["тёмная"][port_type],
                                 hues["светлая"][port_type])

    def test_lightness_does_change(self):
        """Иначе первая проверка выполнялась бы и без всякой адаптации."""
        style.apply_palette(DARK)
        dark = style.PORT_COLORS[list(style.PORT_COLORS)[0]].lightness()
        style.apply_palette(LIGHT)
        light = style.PORT_COLORS[list(style.PORT_COLORS)[0]].lightness()
        self.assertGreater(dark, light)

    def test_types_stay_distinguishable(self):
        """Подгонка светлоты не должна схлопнуть разные типы в один цвет."""
        for name, palette in THEMES:
            style.apply_palette(palette)
            names = {c.name() for c in style.PORT_COLORS.values()}
            with self.subTest(тема=name):
                self.assertEqual(len(names), len(style.PORT_COLORS))


class LiveSceneTests(unittest.TestCase):
    """Уже открытый редактор обязан перекраситься, а не только новый."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        apply_theme(self.app, "dark")

    def _scene(self):
        from ui.editors.graph_canvas.scene import GraphScene
        return GraphScene()

    def test_open_scene_follows_the_theme(self):
        apply_theme(self.app, "dark")
        scene = self._scene()
        before = scene.backgroundBrush().color().name()
        apply_theme(self.app, "light")
        after = scene.backgroundBrush().color().name()
        self.assertNotEqual(before, after,
                            "фон открытого холста не изменился при смене темы")
        self.assertEqual(after, style.SCENE_BG.name())

    def test_new_scene_gets_the_current_theme(self):
        apply_theme(self.app, "light")
        scene = self._scene()
        self.assertEqual(scene.backgroundBrush().color().name(),
                         style.SCENE_BG.name())

    def test_closed_scene_does_not_keep_the_registry_alive(self):
        """Реестр сцен держит слабые ссылки — иначе он копил бы редакторы."""
        import gc
        scene = self._scene()
        count_before = len(style._scenes)
        del scene
        gc.collect()
        self.assertLessEqual(len(style._scenes), count_before)


if __name__ == "__main__":
    unittest.main()
