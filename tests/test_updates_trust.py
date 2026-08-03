"""
Корень доверия клиента: канонизация и цепочка ключей.

Канонизация проверяется ЗОЛОТЫМИ ВЕКТОРАМИ — точными байтами, а не
круговым прогоном «подписали-проверили». Круговой прогон сходится и тогда,
когда клиент разошёлся с сервером: обе стороны согласны сами с собой и не
согласны друг с другом, а выглядит это как «сервер подсовывает подделку».
Те же байты продублированы в серверных тестах (GenerationWeb,
core/test_canonical_contract.py) — изменение с любой стороны роняет тесты с
обеих, и разойтись молча нельзя.

Запуск: python -m unittest tests.test_updates_trust -v
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.updates.keyring import Keyring, KeyringError      # noqa: E402
from core.updates.packages import package_manifest_bytes    # noqa: E402
from core.updates.trust import (                            # noqa: E402
    TrustError, canonical_keyset, key_fingerprint,
)
from core.updates.updater import release_manifest_bytes     # noqa: E402

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey)
    HAS_CRYPTO = True
except ImportError:                                  # pragma: no cover
    HAS_CRYPTO = False


def keypair():
    key = Ed25519PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw)).decode()
    return key, pub


def sign(key, payload: bytes) -> str:
    return base64.b64encode(key.sign(payload)).decode()


def entry(pub: str, status: str = "active") -> dict:
    return {"id": key_fingerprint(pub), "public_key": pub, "status": status}


def keyset(sequence: int, keys: list) -> str:
    return canonical_keyset(sequence, keys)


class CanonicalGoldenTests(unittest.TestCase):
    """Точные байты. Меняются только вместе с серверными."""

    def test_release_manifest(self):
        got = release_manifest_bytes({
            "version": "1.4.0", "channel": "stable", "platform": "any",
            "sequence": 7, "size_bytes": 1024, "sha256": "ab" * 32})
        self.assertEqual(
            got,
            b'{"channel":"stable","platform":"any","sequence":7,'
            b'"sha256":"' + b"ab" * 32 + b'","size_bytes":1024,'
            b'"version":"1.4.0"}')

    def test_package_manifest_sorts_node_types(self):
        # Порядок списка не должен влиять: подписывающий и проверяющий
        # получают его из разных источников.
        first = package_manifest_bytes({
            "name": "physics", "version": "0.2.0", "sequence": 3,
            "size_bytes": 2048, "sha256": "cd" * 32, "api_version": "1",
            "node_types": ["physics.projectile", "physics.energy"]})
        second = package_manifest_bytes({
            "name": "physics", "version": "0.2.0", "sequence": 3,
            "size_bytes": 2048, "sha256": "cd" * 32, "api_version": "1",
            "node_types": ["physics.energy", "physics.projectile"]})
        self.assertEqual(first, second)
        self.assertEqual(
            first,
            b'{"api_version":"1","name":"physics",'
            b'"node_types":"physics.energy,physics.projectile","sequence":3,'
            b'"sha256":"' + b"cd" * 32 + b'","size_bytes":2048,'
            b'"version":"0.2.0"}')

    def test_keyset(self):
        self.assertEqual(
            canonical_keyset(2, [{"id": "bbb", "public_key": "K2",
                                  "status": "active"},
                                 {"id": "aaa", "public_key": "K1",
                                  "status": "revoked"}]),
            '{"keys":[{"id":"aaa","public_key":"K1","status":"revoked"},'
            '{"id":"bbb","public_key":"K2","status":"active"}],"sequence":2}')

    def test_int_and_str_forms_agree(self):
        # Сервер отдаёт числа, argparse — строки. Байты обязаны совпасть.
        as_int = release_manifest_bytes({
            "version": "1", "channel": "stable", "platform": "any",
            "sequence": 7, "size_bytes": 1024, "sha256": "x"})
        as_str = release_manifest_bytes({
            "version": "1", "channel": "stable", "platform": "any",
            "sequence": "7", "size_bytes": "1024", "sha256": "x"})
        self.assertEqual(as_int, as_str)


@unittest.skipUnless(HAS_CRYPTO, "нужна библиотека cryptography")
class EmptyKeyringTests(unittest.TestCase):
    """Сборка без ключа обязана отвергать всё, а не принимать всё."""

    def test_unconfigured_keyring_trusts_nothing(self):
        ring = Keyring(None, bundled={"payload": "", "signature": ""})
        self.assertFalse(ring.configured)
        self.assertEqual(ring.active_keys(), [])
        with self.assertRaisesRegex(TrustError, "нет ни одного доверенного"):
            ring.verify_manifest(b"whatever", "c2ln")

    def test_unconfigured_keyring_cannot_start_a_chain(self):
        # Иначе первый же ответ сервера назначил бы корень доверия — то есть
        # ключ брался бы у того же, кого он должен проверять.
        ring = Keyring(None, bundled={"payload": "", "signature": ""})
        key, pub = keypair()
        payload = keyset(1, [entry(pub)])
        with self.assertRaisesRegex(TrustError, "нет доверенного набора"):
            ring.accept(payload, sign(key, payload.encode()))

    def test_broken_bundled_keyset_fails_loudly(self):
        # Ошибка сборки должна падать на старте, а не превращаться потом в
        # «почему-то не обновляется».
        with self.assertRaises(KeyringError):
            Keyring(None, bundled={"payload": "не json", "signature": ""})


@unittest.skipUnless(HAS_CRYPTO, "нужна библиотека cryptography")
class KeyringChainTests(unittest.TestCase):
    def setUp(self):
        self.k1, self.pub1 = keypair()
        self.k2, self.pub2 = keypair()
        self.tmp = tempfile.mkdtemp()
        self.state = Path(self.tmp) / "keyring.json"
        self.bundled = {"payload": keyset(1, [entry(self.pub1)]),
                        "signature": ""}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ring(self) -> Keyring:
        return Keyring(self.state, bundled=self.bundled)

    def rotated(self, sequence: int = 2, revoke_old: bool = False,
                signer=None) -> tuple:
        keys = [entry(self.pub2),
                entry(self.pub1, "revoked" if revoke_old else "active")]
        payload = keyset(sequence, keys)
        return payload, sign(signer or self.k1, payload.encode())

    def test_bundled_set_is_the_root(self):
        ring = self.ring()
        self.assertTrue(ring.configured)
        self.assertEqual(ring.sequence(), 1)
        self.assertEqual(ring.active_keys(), [self.pub1])

    def test_accepts_set_signed_by_active_key(self):
        ring = self.ring()
        ring.accept(*self.rotated())
        self.assertEqual(ring.sequence(), 2)
        self.assertIn(self.pub2, ring.active_keys())

    def test_refuses_set_signed_by_outsider(self):
        stranger, _ = keypair()
        ring = self.ring()
        with self.assertRaises(TrustError):
            ring.accept(*self.rotated(signer=stranger))
        self.assertEqual(ring.sequence(), 1)

    def test_refuses_rollback_of_the_set(self):
        ring = self.ring()
        ring.accept(*self.rotated(sequence=5))
        payload = keyset(3, [entry(self.pub1)])
        with self.assertRaisesRegex(KeyringError, "sequence"):
            ring.accept(payload, sign(self.k1, payload.encode()))

    def test_same_sequence_is_not_an_error(self):
        # Клиент опрашивает набор при каждом старте: «ничего не изменилось»
        # обязано быть тихим, а не всплывать ошибкой.
        ring = self.ring()
        payload, signature = self.rotated()
        ring.accept(payload, signature)
        again = ring.accept(payload, signature)
        self.assertEqual(again["sequence"], 2)

    def test_refuses_set_without_active_keys(self):
        ring = self.ring()
        payload = keyset(2, [entry(self.pub1, "revoked")])
        with self.assertRaisesRegex(KeyringError, "активных"):
            ring.accept(payload, sign(self.k1, payload.encode()))

    def test_refuses_non_canonical_payload(self):
        # Подпись покрывает ТЕКСТ, а пользуемся мы РАЗБОРОМ: без этой сверки
        # можно подписать одно, а подсунуть на разбор другое.
        ring = self.ring()
        keys = [entry(self.pub2), entry(self.pub1)]
        payload = json.dumps({"sequence": 2, "keys": keys})   # не канон
        with self.assertRaisesRegex(KeyringError, "не канонизирован"):
            ring.accept(payload, sign(self.k1, payload.encode()))

    def test_revoked_key_stops_verifying(self):
        ring = self.ring()
        ring.accept(*self.rotated(revoke_old=True))
        self.assertEqual(ring.active_keys(), [self.pub2])
        manifest = b"anything"
        with self.assertRaises(TrustError):
            ring.verify_manifest(manifest, sign(self.k1, manifest))
        self.assertEqual(ring.verify_manifest(manifest, sign(self.k2, manifest)),
                         key_fingerprint(self.pub2))

    def test_rotation_does_not_invalidate_the_old_key(self):
        # Пока ключ не отозван явно, всё, что им подписано, остаётся
        # проверяемым — иначе ротация обесценивала бы уже выпущенное.
        ring = self.ring()
        ring.accept(*self.rotated())
        manifest = b"release"
        self.assertEqual(ring.verify_manifest(manifest, sign(self.k1, manifest)),
                         key_fingerprint(self.pub1))


@unittest.skipUnless(HAS_CRYPTO, "нужна библиотека cryptography")
class KeyringPersistenceTests(KeyringChainTests):
    def test_chain_survives_restart(self):
        self.ring().accept(*self.rotated())
        self.assertEqual(self.ring().sequence(), 2)

    def test_tampered_chain_falls_back_to_the_bundled_root(self):
        # Цепочка перепроигрывается от зашитого корня, поэтому подменённое
        # звено не проходит проверку и не становится доверенным.
        ring = self.ring()
        ring.accept(*self.rotated())
        stranger, stranger_pub = keypair()
        forged = keyset(3, [entry(stranger_pub)])
        self.state.write_text(json.dumps({"chain": [
            {"sequence": 3, "payload": forged,
             "signature": sign(stranger, forged.encode())}]}),
            encoding="utf-8")

        restarted = self.ring()
        self.assertEqual(restarted.sequence(), 1)
        self.assertEqual(restarted.active_keys(), [self.pub1])
        self.assertTrue(restarted.dropped)

    def test_truncated_chain_file_does_not_disarm_the_client(self):
        self.state.write_text("{\"chain\": [", encoding="utf-8")
        restarted = self.ring()
        self.assertTrue(restarted.configured)
        self.assertEqual(restarted.active_keys(), [self.pub1])

    def test_chain_stops_at_the_first_broken_link(self):
        # Хвост после несошедшегося звена доверия не наследует: он опирался
        # бы на то, что не проверилось.
        ring = self.ring()
        payload2, sig2 = self.rotated(sequence=2)
        ring.accept(payload2, sig2)
        payload3 = keyset(3, [entry(self.pub2)])
        stored = json.loads(self.state.read_text(encoding="utf-8"))
        stored["chain"] = [
            {"sequence": 2, "payload": payload2, "signature": "0" * 88},
            {"sequence": 3, "payload": payload3,
             "signature": sign(self.k2, payload3.encode())},
        ]
        self.state.write_text(json.dumps(stored), encoding="utf-8")
        self.assertEqual(self.ring().sequence(), 1)


if __name__ == "__main__":
    unittest.main()
