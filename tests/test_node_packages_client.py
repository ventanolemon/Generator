"""
Пакеты узлов: клиентская половина.

Установка пакета — исполнение чужого кода на этой машине, и защищает от
этого ровно одно: подпись. Поэтому здесь сначала проверяется, что без
подписи не устанавливается ничего, и только потом — что установленное
подключается правильно.

Остальные проверки (`api_version`, объявленные типы, коллизии) от
вредоносного пакета не спасают — он к тому моменту уже исполнился, — но
ловят пересборку не тем, чем подписывали, и «два источника одного type_id»,
то есть неопределённость, чей код исполнится. Тесты на них написаны именно
в этом качестве.

Запуск: python -m unittest tests.test_node_packages_client -v
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

from core.graph.registry import NodeRegistry                # noqa: E402
from core.updates.keyring import Keyring                    # noqa: E402
from core.updates.packages import (                         # noqa: E402
    MODULE_NAMESPACE, PackageError, PackageInstaller,
    package_manifest_bytes, registry_with_packages,
)
from core.updates.state import InstallState                 # noqa: E402
from core.updates.trust import canonical_keyset             # noqa: E402
from core.updates.updater import UpdateHome                 # noqa: E402
from tests.test_updates_trust import (                      # noqa: E402
    HAS_CRYPTO, entry, keypair,
)

# Пакет-образец. Классы минимальные намеренно: проверяется установщик, а не
# контракт Node — реестр хранит классы по `type_id` и о большем не спрашивает.
PACKAGE_SOURCE = '''
class ProjectileNode:
    type_id = "physics.projectile"


class EnergyNode:
    type_id = "physics.energy"


def register(registry):
    registry.register(ProjectileNode)
    registry.register(EnergyNode)
'''

HIJACKING_SOURCE = '''
class FakeFormulaNode:
    type_id = "formula"


def register(registry):
    registry.register(FakeFormulaNode)
'''

LYING_SOURCE = '''
class ExtraNode:
    type_id = "physics.extra"


def register(registry):
    registry.register(ExtraNode)
'''


def zip_bytes(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buffer.getvalue()


@unittest.skipUnless(HAS_CRYPTO, "нужна библиотека cryptography")
class PackageTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = UpdateHome(self.tmp / "home")
        self.key, self.pub = keypair()
        self.bundled = {"payload": canonical_keyset(1, [entry(self.pub)]),
                        "signature": ""}
        self.artifact = zip_bytes(
            {"physics/__init__.py": PACKAGE_SOURCE})
        self.node_types = ["physics.projectile", "physics.energy"]
        self.catalog_response = {"packages": [
            {"name": "physics", "version": "0.2.0", "summary": "механика",
             "node_types": self.node_types, "api_version": "1",
             "installed_version": "0.2.0", "installed": True}]}

    def tearDown(self):
        for name in [m for m in sys.modules
                     if m.startswith(MODULE_NAMESPACE)]:
            sys.modules.pop(name, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- фейковый сервер ----------

    def manifest(self, *, name: str = "physics", version: str = "0.2.0",
                 sequence: int = 3, api_version: str = "1",
                 node_types=None, signer=None) -> dict:
        types = self.node_types if node_types is None else node_types
        body = {"name": name, "version": version, "sequence": sequence,
                "size_bytes": len(self.artifact),
                "sha256": hashlib.sha256(self.artifact).hexdigest(),
                "api_version": api_version,
                "node_types": sorted(str(t) for t in types)}
        signature = base64.b64encode(
            (signer or self.key).sign(package_manifest_bytes(body))).decode()
        return {"manifest": body, "signature": signature,
                "signing_key_id": "", "url": "https://cdn/physics.zip",
                "summary": "механика"}

    def transport(self, path: str, params, method: str) -> dict:
        if path == "/packages":
            return json.loads(json.dumps(self.catalog_response))
        if path.startswith("/packages/") and path.endswith("/manifest"):
            return json.loads(json.dumps(self.described))
        raise AssertionError(f"неожиданный вызов {path}")

    def installer(self, **kwargs) -> PackageInstaller:
        self.described = getattr(self, "described", None) or self.manifest()
        params = dict(
            keyring=Keyring(self.home.keyring_path, bundled=self.bundled),
            state=InstallState(self.home.state_path),
            transport=self.transport,
            downloader=lambda url, size: self.artifact)
        params.update(kwargs)
        return PackageInstaller(self.home, **params)

    def assertNothingInstalled(self):
        self.assertFalse((self.home.packages / "physics").exists())
        self.assertEqual(
            [p for p in (self.home.packages / ".incoming").rglob("*")
             if p.is_file()], [])


class CatalogTests(PackageTestBase):
    def test_server_installed_flag_is_not_confused_with_local(self):
        # `installed` на сервере — про то, какие графы он готов исполнять.
        # К этой машине это отношения не имеет.
        entry_ = self.installer().catalog()["packages"][0]
        self.assertTrue(entry_["installed"])         # серверное
        self.assertFalse(entry_["local_installed"])  # здесь ещё нет
        self.assertIsNone(entry_["local_version"])

    def test_unsupported_api_version_is_marked(self):
        self.catalog_response["packages"][0]["api_version"] = "9"
        self.assertFalse(self.installer().catalog()["packages"][0]["supported"])

    def test_local_version_appears_after_install(self):
        installer = self.installer()
        installer.install("physics")
        entry_ = installer.catalog()["packages"][0]
        self.assertTrue(entry_["local_installed"])
        self.assertEqual(entry_["local_version"], "0.2.0")


class InstallTests(PackageTestBase):
    def test_signed_package_installs(self):
        out = self.installer().install("physics")
        self.assertEqual(out["version"], "0.2.0")
        self.assertTrue(
            (self.home.packages / "physics" / "physics" / "__init__.py"
             ).exists())
        self.assertEqual(
            InstallState(self.home.state_path).package_sequence("physics"), 3)

    def test_stranger_signature_installs_nothing(self):
        stranger, _ = keypair()
        self.described = self.manifest(signer=stranger)
        with self.assertRaisesRegex(PackageError, "доверенному ключу"):
            self.installer().install("physics")
        self.assertNothingInstalled()

    def test_tampered_node_types_break_the_signature(self):
        # node_types входит в подписанный манифест именно для этого: иначе
        # пакет объявил бы, что предоставляет `formula`, и перехватывал бы
        # чужие графы.
        self.described = self.manifest()
        self.described["manifest"]["node_types"] = ["formula"]
        with self.assertRaises(PackageError):
            self.installer().install("physics")
        self.assertNothingInstalled()

    def test_foreign_api_version_is_refused_before_download(self):
        self.described = self.manifest(api_version="9")
        called = []
        with self.assertRaisesRegex(PackageError, "api_version"):
            self.installer(downloader=lambda u, s: called.append(u)
                           or self.artifact).install("physics")
        self.assertEqual(called, [], "качали то, что и подключать не будем")
        self.assertNothingInstalled()

    def test_rollback_is_refused(self):
        installer = self.installer()
        installer.install("physics")
        self.described = self.manifest(version="0.1.0", sequence=2)
        with self.assertRaisesRegex(PackageError, "Откат"):
            installer.install("physics")
        self.assertEqual(installer.state.package_sequence("physics"), 3)

    def test_types_without_the_package_prefix_are_refused(self):
        self.described = self.manifest(node_types=["physics.ok", "formula"])
        with self.assertRaisesRegex(PackageError, "обязаны начинаться"):
            self.installer().install("physics")
        self.assertNothingInstalled()

    def test_manifest_for_another_package_is_refused(self):
        # Сервер отдал манифест не того пакета — честно подписанный, но
        # чужой. Устанавливать его под запрошенным именем нельзя.
        self.described = self.manifest(name="chemistry",
                                       node_types=["chemistry.mole"])
        with self.assertRaisesRegex(PackageError, "подписан манифест"):
            self.installer().install("physics")

    def test_sha256_mismatch_installs_nothing(self):
        installer = self.installer(downloader=lambda u, s: b"x" * len(
            self.artifact))
        with self.assertRaisesRegex(PackageError, "sha256"):
            installer.install("physics")
        self.assertNothingInstalled()

    def test_upgrade_replaces_the_previous_tree(self):
        installer = self.installer()
        installer.install("physics")
        self.artifact = zip_bytes({"physics/__init__.py": PACKAGE_SOURCE,
                                   "physics/extra.py": "y = 1\n"})
        self.described = self.manifest(version="0.3.0", sequence=4)
        installer.install("physics")
        self.assertTrue(
            (self.home.packages / "physics" / "physics" / "extra.py").exists())
        self.assertEqual(installer.state.package_sequence("physics"), 4)

    def test_uninstall_removes_files_and_state(self):
        installer = self.installer()
        installer.install("physics")
        self.assertTrue(installer.uninstall("physics"))
        self.assertNothingInstalled()
        self.assertEqual(installer.state.packages(), {})


class LoadTests(PackageTestBase):
    def registry(self) -> NodeRegistry:
        registry = NodeRegistry()

        class FormulaNode:
            type_id = "formula"

        registry.register(FormulaNode)
        return registry

    def test_declared_types_appear_in_the_registry(self):
        installer = self.installer()
        installer.install("physics")
        registry = self.registry()
        report = installer.load_into(registry)
        self.assertEqual(report["failed"], {})
        self.assertEqual(report["loaded"]["physics"],
                         ["physics.energy", "physics.projectile"])
        self.assertTrue(registry.has("physics.projectile"))

    def test_module_lands_in_its_own_namespace(self):
        # Иначе пакет с расхожим именем перехватил бы чужой импорт.
        installer = self.installer()
        installer.install("physics")
        installer.load_into(self.registry())
        self.assertIn(f"{MODULE_NAMESPACE}.physics", sys.modules)
        self.assertNotIn("physics", sys.modules)

    def test_package_registering_something_else_is_rejected(self):
        # Подпись сошлась, а собрано не то, чем подписывали.
        self.artifact = zip_bytes({"physics/__init__.py": LYING_SOURCE})
        self.described = self.manifest()
        installer = self.installer()
        installer.install("physics")
        registry = self.registry()
        report = installer.load_into(registry)
        self.assertIn("physics", report["failed"])
        self.assertIn("не то, что объявлено", report["failed"]["physics"])
        # И ничего от него в рабочем реестре не осталось: подключить
        # отказались — значит отказались целиком.
        self.assertEqual(registry.type_ids(), ["formula"])

    def test_type_colliding_with_a_builtin_is_refused_before_import(self):
        # Проверка стоит ДО импорта: два источника одного type_id — это
        # неопределённость, чей код исполнится.
        self.artifact = zip_bytes({"physics/__init__.py": HIJACKING_SOURCE})
        self.described = self.manifest(node_types=["physics.projectile"])
        installer = self.installer()
        installer.install("physics")
        installer.state.set_package("physics", version="0.2.0", sequence=3,
                                    api_version="1", node_types=["formula"])
        report = installer.load_into(self.registry())
        self.assertIn("занятые типы", report["failed"]["physics"])
        self.assertNotIn(f"{MODULE_NAMESPACE}.physics", sys.modules)

    def test_package_without_entry_point_fails_alone(self):
        self.artifact = zip_bytes({"physics/__init__.py": "x = 1\n"})
        self.described = self.manifest()
        installer = self.installer()
        installer.install("physics")
        report = installer.load_into(self.registry())
        self.assertIn("register", report["failed"]["physics"])

    def test_package_without_module_fails_alone(self):
        self.artifact = zip_bytes({"readme.txt": "ничего"})
        self.described = self.manifest()
        installer = self.installer()
        installer.install("physics")
        report = installer.load_into(self.registry())
        self.assertIn("__init__.py", report["failed"]["physics"])

    def test_one_broken_package_does_not_take_down_the_rest(self):
        # Приложение обязано подниматься и с битым пакетом: иначе неудачная
        # установка оставляет пользователя без программы.
        installer = self.installer()
        installer.install("physics")
        installer.state.set_package("broken", version="1.0", sequence=1,
                                    api_version="1",
                                    node_types=["broken.thing"])
        report = installer.load_into(self.registry())
        self.assertIn("physics", report["loaded"])
        self.assertIn("broken", report["failed"])

    def test_package_built_for_another_api_is_not_loaded(self):
        installer = self.installer()
        installer.install("physics")
        installer.state.set_package("physics", version="0.2.0", sequence=3,
                                    api_version="9",
                                    node_types=self.node_types)
        report = installer.load_into(self.registry())
        self.assertIn("api_version", report["failed"]["physics"])

    def test_registry_with_packages_keeps_builtins(self):
        installer = self.installer()
        installer.install("physics")
        registry, report = registry_with_packages(self.registry, installer)
        self.assertTrue(registry.has("formula"))
        self.assertTrue(registry.has("physics.energy"))
        self.assertEqual(report["failed"], {})


if __name__ == "__main__":
    unittest.main()
