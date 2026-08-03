"""
Окно «Обновления»: витрина для core/updates.

Проверяется не «нарисовалось ли», а то, что окно НЕ ВРЁТ. У этой витрины
три способа соврать, и каждый вреден по-своему:

  * показать отказ проверки как «обновлений нет» — тогда «подпись не
    соответствует доверенному ключу» и «сервер предлагает откат» выглядят
    тишиной, хотя это признаки того, что с каналом что-то не так;
  * промолчать про сборку без ключа — пользователь будет считать сбоем
    сети то, что является свойством сборки;
  * сказать «обновлено», когда обновление лишь подготовлено, — человек
    перезапустится, увидит прежнюю версию и решит, что механизм не работает.

Транспорт и загрузчик — фейковые (инжекция выигрывает у боевого urllib), но
подписи настоящие: окно ходит через настоящий Updater с настоящим Keyring,
поэтому проверяется реальный путь, а не заглушка.

Запуск: QT_QPA_PLATFORM=offscreen python -m unittest tests.test_updates_window
"""

from __future__ import annotations
import base64
import hashlib
import io
import json
import os
import shutil
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import PyQt6  # noqa: F401
    from PyQt6.QtWidgets import QApplication, QPushButton
    HAS_QT = True
except Exception:
    HAS_QT = False

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey)
    HAS_CRYPTO = True
except ImportError:                                  # pragma: no cover
    HAS_CRYPTO = False

if HAS_QT and HAS_CRYPTO:
    from core.repository import Repository
    from core.settings import Settings
    from core.updates import (
        InstallState, Keyring, PackageInstaller, UpdateHome, Updater,
    )
    from core.updates.trust import canonical_keyset, key_fingerprint
    from core.updates.updater import release_manifest_bytes
    from core.updates.packages import package_manifest_bytes
    from ui.app_context import AppContext
    from ui.windows.updates_window import UpdatesWindow


def _zip(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buffer.getvalue()


@unittest.skipUnless(HAS_QT and HAS_CRYPTO, "нужны PyQt6 и cryptography")
class UpdatesWindowTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = UpdateHome(self.tmp / "home")

        self.key = Ed25519PrivateKey.generate()
        self.pub = base64.b64encode(self.key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)).decode()
        self.bundled = {
            "payload": canonical_keyset(1, [{
                "id": key_fingerprint(self.pub), "public_key": self.pub,
                "status": "active"}]),
            "signature": ""}

        self.artifact = _zip({"marker.txt": "новая версия"})
        self.package = _zip({"physics/__init__.py":
                             'class P:\n    type_id = "physics.projectile"\n'
                             '\n\ndef register(r):\n    r.register(P)\n'})
        self.release = self._release("1.4.0", 7)
        self.catalog = {"packages": []}
        self.pkg_manifest = self._package_manifest()
        self.keyset_response = {"configured": False}

        self.repo = Repository(str(self.tmp / "db.sqlite"))
        self.settings = Settings(_ini_settings())
        self.ctx = AppContext(
            repo=self.repo, settings=self.settings,
            user_id_provider=lambda: "alla",
            user_role_provider=lambda: "teacher",
            updater=self._updater(), package_installer=None)
        self.ctx.package_installer = PackageInstaller(
            self.home, keyring=self.ctx.updater.keyring,
            state=self.ctx.updater.state, transport=self._transport,
            downloader=self._downloader)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- фейковый сервер с настоящими подписями ----------

    def _release(self, version: str, sequence: int, signer=None) -> dict:
        manifest = {"version": version, "channel": "stable",
                    "platform": "any", "sequence": sequence,
                    "size_bytes": len(self.artifact),
                    "sha256": hashlib.sha256(self.artifact).hexdigest()}
        signature = base64.b64encode((signer or self.key).sign(
            release_manifest_bytes(manifest))).decode()
        return {"update_available": True, "channel": "stable",
                "platform": "any", "manifest": manifest,
                "signature": signature, "signing_key_id": "",
                "url": "https://cdn/app.zip", "notes": "Починили важное",
                "mandatory": False, "published_at": 0}

    def _package_manifest(self) -> dict:
        manifest = {"name": "physics", "version": "0.2.0", "sequence": 3,
                    "size_bytes": len(self.package),
                    "sha256": hashlib.sha256(self.package).hexdigest(),
                    "api_version": "1",
                    "node_types": ["physics.projectile"]}
        signature = base64.b64encode(
            self.key.sign(package_manifest_bytes(manifest))).decode()
        return {"manifest": manifest, "signature": signature,
                "signing_key_id": "", "url": "https://cdn/physics.zip",
                "summary": "механика"}

    def _transport(self, path: str, params, method: str) -> dict:
        if path == "/updates/check":
            return json.loads(json.dumps(self.release))
        if path == "/updates/keys":
            return json.loads(json.dumps(self.keyset_response))
        if path == "/packages":
            return json.loads(json.dumps(self.catalog))
        if path.startswith("/packages/") and path.endswith("/manifest"):
            return json.loads(json.dumps(self.pkg_manifest))
        raise AssertionError(f"неожиданный вызов {path}")

    def _downloader(self, url: str, size: int) -> bytes:
        return self.package if "physics" in url else self.artifact

    def _updater(self, bundled=None) -> "Updater":
        return Updater(
            self.home, base_url="http://fake-server",
            keyring=Keyring(self.home.keyring_path,
                            bundled=self.bundled if bundled is None
                            else bundled),
            state=InstallState(self.home.state_path),
            transport=self._transport, downloader=self._downloader)

    # ---------- помощники ----------

    def _window(self) -> "UpdatesWindow":
        window = UpdatesWindow(self.ctx)
        self.addCleanup(window.close)
        return window

    def _settle(self, window, timeout: float = 5.0) -> None:
        """Докрутить цикл событий до конца фонового вызова — реальный путь
        QThread → сигнал → слот, а не подмена слота."""
        deadline = time.monotonic() + timeout
        while window._worker is not None:            # noqa: SLF001
            self.assertLess(time.monotonic(), deadline,
                            "воркер не завершился за отведённое время")
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()

    @staticmethod
    def _buttons(window) -> list:
        return window.findChildren(QPushButton)


class TrustDisplayTests(UpdatesWindowTestBase):
    def test_fingerprints_are_shown(self):
        window = self._window()
        self.assertIn(key_fingerprint(self.pub), window.trust_label.text())

    def test_build_without_a_key_says_so_and_blocks_actions(self):
        # Иначе пользователь будет считать сбоем сети то, что является
        # свойством сборки.
        self.ctx.updater = self._updater(
            bundled={"payload": "", "signature": ""})
        self.ctx.package_installer = PackageInstaller(
            self.home, keyring=self.ctx.updater.keyring,
            state=self.ctx.updater.state, transport=self._transport)
        window = self._window()
        self.assertIn("не впечатан ключ", window.trust_label.text())
        self.assertFalse(window.check_btn.isEnabled())
        self.assertIn("не будет принято", window.app_status.text())

    def test_installed_version_is_shown(self):
        self.ctx.updater.state.set_app(version="1.0.0", sequence=3)
        window = self._window()
        self.assertIn("1.0.0", window.version_label.text())
        self.assertIn("3", window.version_label.text())


class CheckTests(UpdatesWindowTestBase):
    def test_available_update_is_described(self):
        window = self._window()
        window._on_check()                            # noqa: SLF001
        self._settle(window)
        self.assertIn("1.4.0", window.app_status.text())
        self.assertIn("Починили важное", window.app_status.text())
        self.assertTrue(window.stage_btn.isEnabled())

    def test_up_to_date_is_plain(self):
        self.release = {"update_available": False, "reason": "up_to_date"}
        window = self._window()
        window._on_check()                            # noqa: SLF001
        self._settle(window)
        self.assertIn("последняя версия", window.app_status.text())
        self.assertFalse(window.stage_btn.isEnabled())

    def test_forged_signature_is_reported_as_a_refusal_not_as_silence(self):
        # Главный тест файла. Отказ — событие, а не «обновлений нет».
        stranger = Ed25519PrivateKey.generate()
        self.release = self._release("1.4.0", 7, signer=stranger)
        window = self._window()
        window._on_check()                            # noqa: SLF001
        self._settle(window)
        text = window.app_status.text()
        self.assertIn("отклонено", text.lower())
        self.assertIn("доверенному ключу", text)
        self.assertFalse(window.stage_btn.isEnabled())

    def test_rollback_offer_is_reported_as_a_refusal(self):
        self.ctx.updater.state.set_app(version="2.0.0", sequence=9)
        window = self._window()
        window._on_check()                            # noqa: SLF001
        self._settle(window)
        self.assertIn("отклонено", window.app_status.text().lower())
        self.assertIn("Откат", window.app_status.text())

    def test_mandatory_is_surfaced(self):
        self.release["mandatory"] = True
        window = self._window()
        window._on_check()                            # noqa: SLF001
        self._settle(window)
        self.assertIn("обязательное", window.app_status.text())

    def test_network_failure_does_not_look_like_good_news(self):
        def broken(path, params, method):
            raise RuntimeError("сеть недоступна")
        self.ctx.updater._transport = broken           # noqa: SLF001
        window = self._window()
        window._on_check()                            # noqa: SLF001
        self._settle(window)
        self.assertIn("Не удалось проверить", window.app_status.text())
        self.assertFalse(window.stage_btn.isEnabled())


class StageTests(UpdatesWindowTestBase):
    def test_staging_says_it_is_not_installed_yet(self):
        # Соврать здесь легко и неприятно: человек перезапустится, увидит
        # прежнюю версию и решит, что механизм не работает.
        window = self._window()
        window._on_check()                            # noqa: SLF001
        self._settle(window)
        window._on_stage()                            # noqa: SLF001
        self._settle(window)

        self.assertIn("следующем запуске", window.app_status.text())
        self.assertIn("Подготовлено", window.pending_label.text())
        self.assertEqual(self.ctx.updater.state.app_version(), "",
                         "версия не должна считаться установленной")

    def test_broken_download_is_reported(self):
        self.ctx.updater._downloader = (                # noqa: SLF001
            lambda url, size: b"x" * len(self.artifact))
        window = self._window()
        window._on_check()                            # noqa: SLF001
        self._settle(window)
        window._on_stage()                            # noqa: SLF001
        self._settle(window)
        self.assertIn("Не удалось подготовить", window.app_status.text())
        self.assertIn("sha256", window.app_status.text())


class PackagesTests(UpdatesWindowTestBase):
    def _seed_catalog(self, **over) -> None:
        entry = {"name": "physics", "version": "0.2.0", "summary": "механика",
                 "node_types": ["physics.projectile"], "api_version": "1",
                 "installed_version": "0.2.0", "installed": True}
        entry.update(over)
        self.catalog = {"packages": [entry]}

    def test_catalog_lists_packages(self):
        self._seed_catalog()
        window = self._window()
        window._on_catalog()                          # noqa: SLF001
        self._settle(window)
        self.assertIn("Пакетов в каталоге: 1", window.pkg_status.text())
        labels = [b.text() for b in self._buttons(window)]
        self.assertIn("Установить", labels)

    def test_empty_catalog_says_so(self):
        window = self._window()
        window._on_catalog()                          # noqa: SLF001
        self._settle(window)
        self.assertIn("нет ни одного пакета", window.pkg_status.text())

    def test_package_for_another_api_offers_no_install_button(self):
        # Он не «немного не подойдёт» — он упал бы посреди генерации.
        self._seed_catalog(api_version="9")
        window = self._window()
        window._on_catalog()                          # noqa: SLF001
        self._settle(window)
        labels = [b.text() for b in self._buttons(window)]
        self.assertNotIn("Установить", labels)

    def test_install_verifies_signature_and_reports_restart(self):
        self._seed_catalog()
        window = self._window()
        window._on_install("physics")                 # noqa: SLF001
        self._settle(window)
        self.assertIn("установлен", window.pkg_status.text())
        self.assertIn("следующем запуске", window.pkg_status.text())
        self.assertEqual(
            self.ctx.updater.state.package_sequence("physics"), 3)

    def test_forged_package_is_refused_with_a_reason(self):
        stranger = Ed25519PrivateKey.generate()
        manifest = self.pkg_manifest["manifest"]
        self.pkg_manifest["signature"] = base64.b64encode(
            stranger.sign(package_manifest_bytes(manifest))).decode()
        self._seed_catalog()
        window = self._window()
        window._on_install("physics")                 # noqa: SLF001
        self._settle(window)
        self.assertIn("Не установлен", window.pkg_status.text())
        self.assertIn("доверенному ключу", window.pkg_status.text())
        self.assertEqual(self.ctx.updater.state.packages(), {})


class NoServerTests(UpdatesWindowTestBase):
    def test_without_an_address_the_window_says_where_to_set_it(self):
        self.ctx.updater.set_base_url("")
        window = self._window()
        self.assertIn("Настройках", window.app_status.text())
        self.assertFalse(window.check_btn.isEnabled())


def _ini_settings():
    from PyQt6.QtCore import QSettings
    return QSettings(tempfile.mktemp(suffix=".ini"), QSettings.Format.IniFormat)


if __name__ == "__main__":
    unittest.main()
