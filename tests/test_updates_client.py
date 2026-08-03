"""
Обновление приложения: клиентская половина.

Проверяется не «скачалось ли», а то, ради чего клиентская половина вообще
существует: что клиент НЕ принимает. Сервер входит в модель угроз, поэтому
каждый его ответ здесь портят по одному полю и смотрят, что обновление
отвергнуто до того, как хоть один байт лёг на диск.

Отдельный блок — атомарность переключения. Обрыв между «старое дерево
уехало» и «новое встало» имитируется вручную: это единственное место, где
пользователь может остаться без приложения, и вести себя оно обязано
предсказуемо в обе стороны.

Запуск: python -m unittest tests.test_updates_client -v
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.updates.keyring import Keyring                    # noqa: E402
from core.updates.state import InstallState                 # noqa: E402
from core.updates.trust import canonical_keyset             # noqa: E402
from core.updates.updater import (                          # noqa: E402
    UpdateError, UpdateHome, Updater, release_manifest_bytes,
)
from tests.test_updates_trust import (                      # noqa: E402
    HAS_CRYPTO, entry, keypair,
)


def zip_bytes(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buffer.getvalue()


@unittest.skipUnless(HAS_CRYPTO, "нужна библиотека cryptography")
class UpdaterTestBase(unittest.TestCase):
    """Фейковый сервер: отдаёт ровно то, что отдал бы настоящий."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = UpdateHome(self.tmp / "home")
        self.key, self.pub = keypair()
        self.bundled = {"payload": canonical_keyset(1, [entry(self.pub)]),
                        "signature": ""}
        self.artifact = zip_bytes({"marker.txt": "новая версия",
                                   "core/thing.py": "x = 2\n"})
        self.calls: list[tuple] = []
        self.keyset_response = {"configured": False}
        self.release = self._release("1.4.0", sequence=7)

        self.home.app.mkdir(parents=True)
        (self.home.app / "marker.txt").write_text("старая версия",
                                                  encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- фейковый сервер ----------

    def _release(self, version: str, sequence: int, *, channel: str = "stable",
                 platform: str = "any", signer=None, payload: bytes = None,
                 ) -> dict:
        payload = self.artifact if payload is None else payload
        manifest = {"version": version, "channel": channel,
                    "platform": platform, "sequence": sequence,
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest()}
        signature = base64.b64encode(
            (signer or self.key).sign(release_manifest_bytes(manifest))).decode()
        return {"update_available": True, "channel": channel,
                "platform": platform, "manifest": manifest,
                "signature": signature, "signing_key_id": "",
                "url": "https://cdn/app.zip", "notes": "", "mandatory": False,
                "published_at": 0}

    def transport(self, path: str, params, method: str) -> dict:
        self.calls.append((path, params, method))
        if path == "/updates/check":
            return json.loads(json.dumps(self.release))
        if path == "/updates/keys":
            return json.loads(json.dumps(self.keyset_response))
        raise AssertionError(f"неожиданный вызов {path}")

    def downloader(self, url: str, expected_size: int) -> bytes:
        return self.artifact

    def updater(self, **kwargs) -> Updater:
        params = dict(
            base_url="https://server",
            keyring=Keyring(self.home.keyring_path, bundled=self.bundled),
            state=InstallState(self.home.state_path),
            transport=self.transport, downloader=self.downloader)
        params.update(kwargs)
        return Updater(self.home, **params)

    def assertNothingDownloaded(self):
        # Пустой каталог карантина безвреден; вредны ФАЙЛЫ в нём — не
        # сверенные байты, которые кто-нибудь потом подхватит.
        self.assertEqual(
            [p for p in self.home.incoming.rglob("*") if p.is_file()], [],
            "в карантине остались непроверенные байты")
        self.assertEqual(
            [p for p in self.home.staged.rglob("*") if p.is_file()], [],
            "распаковано то, что не прошло проверку")


class CheckTests(UpdaterTestBase):
    def test_signed_release_is_offered(self):
        checked = self.updater().check()
        self.assertTrue(checked["update_available"])
        self.assertTrue(checked["verified"])

    def test_no_update_passes_through(self):
        self.release = {"update_available": False, "reason": "up_to_date"}
        self.assertFalse(self.updater().check()["update_available"])

    def test_current_state_is_sent_to_the_server(self):
        up = self.updater()
        up.state.set_app(version="1.0.0", sequence=3)
        up.check()
        path, params, _ = self.calls[-1]
        self.assertEqual(path, "/updates/check")
        self.assertEqual(params["current_sequence"], 3)
        self.assertEqual(params["current_version"], "1.0.0")

    def test_tampered_version_is_refused(self):
        # Подпись покрывает манифест ЦЕЛИКОМ: переклеить подписанный артефакт
        # под другую версию не выйдет.
        self.release["manifest"]["version"] = "9.9.9"
        checked = self.updater().check()
        self.assertFalse(checked["update_available"])
        self.assertIn("Подпись", checked["rejected"])

    def test_tampered_sha256_is_refused(self):
        self.release["manifest"]["sha256"] = "0" * 64
        self.assertFalse(self.updater().check()["update_available"])

    def test_signature_by_a_stranger_is_refused(self):
        stranger, _ = keypair()
        self.release = self._release("1.4.0", sequence=7, signer=stranger)
        checked = self.updater().check()
        self.assertFalse(checked["update_available"])
        self.assertIn("доверенному ключу", checked["rejected"])

    def test_rollback_is_refused_although_the_signature_is_valid(self):
        up = self.updater()
        up.state.set_app(version="2.0.0", sequence=9)
        checked = up.check()
        self.assertFalse(checked["update_available"])
        self.assertTrue(checked["verified"])       # подпись настоящая!
        self.assertIn("Откат", checked["rejected"])

    def test_same_sequence_is_refused(self):
        up = self.updater()
        up.state.set_app(version="1.4.0", sequence=7)
        self.assertFalse(up.check()["update_available"])

    def test_release_for_another_platform_is_refused(self):
        self.release = self._release("1.4.0", sequence=7, platform="win64")
        self.release["platform"] = "any"           # сервер «говорит» одно…
        checked = self.updater().check()           # …подписано другое
        self.assertFalse(checked["update_available"])
        self.assertIn("win64", checked["rejected"])

    def test_release_from_another_channel_is_refused(self):
        self.release = self._release("1.4.0", sequence=7, channel="beta")
        checked = self.updater(channel="stable").check()
        self.assertFalse(checked["update_available"])

    def test_mandatory_flag_is_passed_through_untouched(self):
        # Сигнал приложению, а не команда: решает клиент.
        self.release["mandatory"] = True
        self.assertTrue(self.updater().check()["mandatory"])

    def test_unconfigured_build_refuses_everything(self):
        up = self.updater(keyring=Keyring(None, bundled={"payload": "",
                                                         "signature": ""}))
        checked = up.check()
        self.assertFalse(checked["update_available"])
        self.assertIn("собран без ключа", checked["rejected"])


class StageTests(UpdaterTestBase):
    def test_happy_path_stages_but_does_not_switch(self):
        up = self.updater()
        pending = up.stage(up.check())
        self.assertEqual(pending["version"], "1.4.0")
        self.assertTrue((self.home.staged / "1.4.0" / "marker.txt").exists())
        # Дерево приложения ещё прежнее: подготовка ≠ установка.
        self.assertEqual(
            (self.home.app / "marker.txt").read_text(encoding="utf-8"),
            "старая версия")
        self.assertEqual(up.state.app_sequence(), 0)

    def test_signature_is_rechecked_before_downloading(self):
        # `checked` мог приехать из кеша UI — доверять ему нельзя.
        up = self.updater()
        checked = up.check()
        checked["manifest"]["sequence"] = 99
        with self.assertRaises(Exception):
            up.stage(checked)
        self.assertNothingDownloaded()

    def test_sha256_mismatch_leaves_nothing_on_disk(self):
        up = self.updater(downloader=lambda url, size: b"x" * len(self.artifact))
        with self.assertRaisesRegex(UpdateError, "sha256"):
            up.stage(up.check())
        self.assertNothingDownloaded()
        self.assertIsNone(up.state.pending())

    def test_oversized_artifact_is_cut_off(self):
        # Без ограничения по подписанному размеру сервер забивает диск, а
        # проверка хеша случится, когда места уже нет.
        big = self.artifact + b"0" * 4096
        up = self.updater(downloader=lambda url, size: big)
        with self.assertRaisesRegex(UpdateError, "Размер"):
            up.stage(up.check())
        self.assertNothingDownloaded()

    def test_archive_escaping_the_directory_is_refused(self):
        evil = zip_bytes({"../../pwned.txt": "нет"})
        self.artifact = evil
        self.release = self._release("1.4.0", sequence=7, payload=evil)
        up = self.updater()
        with self.assertRaisesRegex(UpdateError, "за пределы"):
            up.stage(up.check())
        self.assertFalse((self.tmp / "pwned.txt").exists())

    def test_staging_twice_replaces_the_previous_staging(self):
        up = self.updater()
        up.stage(up.check())
        self.artifact = zip_bytes({"marker.txt": "ещё новее"})
        self.release = self._release("1.5.0", sequence=8)
        up.stage(up.check())
        self.assertEqual(up.state.pending()["version"], "1.5.0")


class ApplyTests(UpdaterTestBase):
    def test_switch_replaces_the_tree_and_keeps_a_backup(self):
        up = self.updater()
        up.stage(up.check())
        applied = up.apply_pending(allow_self_replace=True)

        self.assertEqual(applied["version"], "1.4.0")
        self.assertEqual(
            (self.home.app / "marker.txt").read_text(encoding="utf-8"),
            "новая версия")
        backups = list(self.home.backup.iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "marker.txt").read_text(encoding="utf-8"),
                         "старая версия")
        self.assertEqual(up.state.app_sequence(), 7)
        self.assertIsNone(up.state.pending())

    def test_applied_release_cannot_be_offered_again(self):
        up = self.updater()
        up.stage(up.check())
        up.apply_pending(allow_self_replace=True)
        self.assertFalse(self.updater().check()["update_available"])

    def test_nothing_to_apply_is_not_an_error(self):
        self.assertIsNone(self.updater().apply_pending(allow_self_replace=True))

    def test_two_updates_in_the_same_second_do_not_collide(self):
        # Метки времени в секундах недостаточно: переименование каталога
        # поверх существующего непустого падает, то есть переключение
        # срывалось бы ровно тогда, когда обновляются часто.
        up = self.updater()
        up.stage(up.check())
        up.apply_pending(allow_self_replace=True)

        self.artifact = zip_bytes({"marker.txt": "ещё новее"})
        self.release = self._release("1.5.0", sequence=8)
        up.stage(up.check())
        up.apply_pending(allow_self_replace=True)

        self.assertEqual(
            (self.home.app / "marker.txt").read_text(encoding="utf-8"),
            "ещё новее")
        self.assertEqual(up.state.app_sequence(), 8)

    def test_backups_do_not_pile_up(self):
        # Иначе через год на диске лежит десяток полных деревьев.
        up = self.updater()
        for index, sequence in enumerate((7, 8, 9), start=4):
            self.artifact = zip_bytes({"marker.txt": f"версия {index}"})
            self.release = self._release(f"1.{index}.0", sequence=sequence)
            up.stage(up.check())
            up.apply_pending(allow_self_replace=True)
        kept = [p for p in self.home.backup.iterdir() if p.is_dir()]
        self.assertEqual(len(kept), 1)
        # И это копия последней перед текущей, а не случайная.
        self.assertEqual((kept[0] / "marker.txt").read_text(encoding="utf-8"),
                         "версия 5")

    def test_missing_staged_tree_leaves_the_app_intact(self):
        up = self.updater()
        up.stage(up.check())
        shutil.rmtree(self.home.staged / "1.4.0")
        with self.assertRaisesRegex(UpdateError, "исчезло"):
            up.apply_pending(allow_self_replace=True)
        self.assertEqual(
            (self.home.app / "marker.txt").read_text(encoding="utf-8"),
            "старая версия")

    def test_refuses_to_replace_the_tree_it_runs_from(self):
        # На Windows это просто не выйдет, на Linux выйдет — и процесс
        # останется со старыми открытыми файлами. Понятный отказ лучше.
        class SelfHome(UpdateHome):
            @property
            def app(self):
                return Path(_ROOT)

        home = SelfHome(self.home.root)
        up = Updater(home, base_url="https://server",
                     keyring=Keyring(home.keyring_path, bundled=self.bundled),
                     state=InstallState(home.state_path),
                     transport=self.transport, downloader=self.downloader)
        up.stage(up.check())
        with self.assertRaisesRegex(UpdateError, "из которого выполняется"):
            up.apply_pending()
        self.assertTrue((Path(_ROOT) / "main.py").exists())


class CrashRecoveryTests(UpdaterTestBase):
    """Обрыв ровно между двумя переименованиями."""

    def _interrupt_after_backup(self, up) -> dict:
        pending = up.state.pending()
        backup = self.home.backup / "app-crash"
        intent = {"staged": pending["path"], "app": str(self.home.app),
                  "backup": str(backup), "version": pending["version"],
                  "sequence": pending["sequence"], "signing_key_id": ""}
        up._write_intent(intent)                     # noqa: SLF001
        backup.parent.mkdir(parents=True, exist_ok=True)
        self.home.app.replace(backup)                # первое переименование
        return intent

    def test_recovers_forward_when_the_new_tree_is_ready(self):
        up = self.updater()
        up.stage(up.check())
        self._interrupt_after_backup(up)

        outcome = self.updater().recover()
        self.assertIn("вперёд", outcome)
        self.assertEqual(
            (self.home.app / "marker.txt").read_text(encoding="utf-8"),
            "новая версия")
        self.assertEqual(InstallState(self.home.state_path).app_sequence(), 7)

    def test_rolls_back_when_the_new_tree_is_gone(self):
        up = self.updater()
        up.stage(up.check())
        intent = self._interrupt_after_backup(up)
        shutil.rmtree(intent["staged"])              # новое дерево пропало

        outcome = self.updater().recover()
        self.assertIn("откачено", outcome)
        self.assertEqual(
            (self.home.app / "marker.txt").read_text(encoding="utf-8"),
            "старая версия")
        # Версия НЕ повышена: установилось прежнее.
        self.assertEqual(InstallState(self.home.state_path).app_sequence(), 0)

    def test_intent_left_before_the_first_rename_is_just_dropped(self):
        up = self.updater()
        up.stage(up.check())
        up._write_intent({"staged": up.state.pending()["path"],   # noqa: SLF001
                          "app": str(self.home.app),
                          "backup": str(self.home.backup / "app-x"),
                          "version": "1.4.0", "sequence": 7})
        outcome = self.updater().recover()
        self.assertIn("не начиналось", outcome)
        self.assertIsNotNone(InstallState(self.home.state_path).pending())

    def test_unreadable_intent_does_not_block_startup(self):
        self.home.root.mkdir(parents=True, exist_ok=True)
        self.home.intent_path.write_text("{битое", encoding="utf-8")
        self.assertIn("отброшено", self.updater().recover())
        self.assertFalse(self.home.intent_path.exists())


class KeyRotationOverTheWireTests(UpdaterTestBase):
    def test_client_follows_rotation_and_then_trusts_the_new_key(self):
        key2, pub2 = keypair()
        payload = canonical_keyset(2, [entry(pub2), entry(self.pub)])
        self.keyset_response = {
            "configured": True, "sequence": 2, "payload": payload,
            "signature": base64.b64encode(
                self.key.sign(payload.encode())).decode()}

        up = self.updater()
        # До ротации релиз, подписанный новым ключом, — подделка.
        self.release = self._release("1.4.0", sequence=7, signer=key2)
        self.assertFalse(up.check()["update_available"])

        self.assertEqual(up.refresh_keys()["sequence"], 2)
        self.assertTrue(up.check()["update_available"])

    def test_rotation_signed_by_a_stranger_is_refused(self):
        stranger, stranger_pub = keypair()
        payload = canonical_keyset(2, [entry(stranger_pub)])
        self.keyset_response = {
            "configured": True, "sequence": 2, "payload": payload,
            "signature": base64.b64encode(
                stranger.sign(payload.encode())).decode()}
        up = self.updater()
        with self.assertRaises(Exception):
            up.refresh_keys()
        self.assertEqual(up.keyring.active_keys(), [self.pub])

    def test_server_without_keys_configured_changes_nothing(self):
        up = self.updater()
        self.assertIsNone(up.refresh_keys())
        self.assertEqual(up.keyring.sequence(), 1)


if __name__ == "__main__":
    unittest.main()
