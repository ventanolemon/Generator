"""
Тесты темы (контракт K1 плана docs/ui_rework_plan.md, задача A3).

Проверяем: словарь QSS-классов покрыт в обеих палитрах, apply_theme
реально ставит стиль приложению, current_palette корректно резолвит имена.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_theme
"""

from __future__ import annotations
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui.theme import (
    DARK, LIGHT, Palette, apply_theme, build_qss, current_palette,
)

try:
    from PyQt6.QtWidgets import QApplication
    HAS_QT = True
except Exception:
    HAS_QT = False


# Словарь классов K1 — обе стороны (Opus/Fable) используют ровно эти имена.
K1_CLASSES = (
    "title", "subtitle", "card", "toolbar", "toolbtn",
    "badge", "badge-warn", "badge-error", "danger", "muted",
)


class BuildQssTests(unittest.TestCase):
    def test_nonempty_for_both_palettes(self):
        for pal in (DARK, LIGHT):
            qss = build_qss(pal)
            self.assertIsInstance(qss, str)
            self.assertGreater(len(qss.strip()), 0)

    def test_k1_class_vocabulary_covered(self):
        for pal in (DARK, LIGHT):
            qss = build_qss(pal)
            for cls in K1_CLASSES:
                self.assertIn(
                    f'[class="{cls}"]', qss,
                    msg=f"нет селектора для класса {cls!r}",
                )

    def test_accent_extension_covered(self):
        # Расширение сверх минимума K1 (используется InteractiveTaskView).
        self.assertIn('[class="accent"]', build_qss(DARK))

    def test_palettes_differ(self):
        self.assertNotEqual(build_qss(DARK), build_qss(LIGHT))

    def test_tokens_present_in_output(self):
        qss = build_qss(DARK)
        self.assertIn(DARK.bg, qss)
        self.assertIn(DARK.accent, qss)


class CurrentPaletteTests(unittest.TestCase):
    def test_resolution(self):
        self.assertIs(current_palette("dark"), DARK)
        self.assertIs(current_palette("light"), LIGHT)
        self.assertIs(current_palette("LIGHT"), LIGHT)  # регистронезависимо

    def test_default_and_fallback_is_dark(self):
        self.assertIs(current_palette(None), DARK)
        self.assertIs(current_palette(""), DARK)
        self.assertIs(current_palette("solarized"), DARK)

    def test_palette_has_contract_tokens(self):
        for token in ("bg", "surface", "surface_alt", "text", "text_muted",
                      "accent", "danger", "success", "border"):
            self.assertTrue(hasattr(Palette, "__dataclass_fields__"))
            self.assertIn(token, Palette.__dataclass_fields__)


@unittest.skipUnless(HAS_QT, "PyQt6 не установлен")
class ApplyThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        self.app.setStyleSheet("")

    def test_apply_dark_sets_stylesheet(self):
        apply_theme(self.app, "dark")
        self.assertGreater(len(self.app.styleSheet().strip()), 0)
        self.assertIn(DARK.bg, self.app.styleSheet())

    def test_apply_light_sets_stylesheet(self):
        apply_theme(self.app, "light")
        self.assertGreater(len(self.app.styleSheet().strip()), 0)
        self.assertIn(LIGHT.bg, self.app.styleSheet())

    def test_default_is_dark(self):
        apply_theme(self.app)
        self.assertIn(DARK.bg, self.app.styleSheet())


if __name__ == "__main__":
    unittest.main()
