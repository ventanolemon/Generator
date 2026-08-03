"""
Связка ключей выпуска: что клиент считает подлинным и как это меняется.

## Клиент несёт не ключ, а НАБОР

Зашить один публичный ключ проще, но означает, что смена ключа = обход всех
пользователей вручную. Вместо этого в сборку кладётся первый *набор*
(`bundled.BUNDLED_KEYSET`), а дальше клиент принимает новые наборы с
сервера — каждый обязан быть подписан ключом, активным в наборе, которому
клиент уже верит. Доверие переходит по цепочке, переустановка не нужна.

Заложить это надо в ПЕРВУЮ версию клиента: добавить потом — значит сначала
обойти всех, ради чего цепочка и затевалась.

## Пустая связка не доверяет ничему

Сборка без зашитого набора отвергает любое обновление и любой пакет. Это
единственное правильное поведение: «ключа нет, значит проверять нечем,
значит принимаем как есть» — ровно та дыра, ради закрытия которой всё
написано. В dev-сборках набор подставляется явно (`Keyring(..., bundled=…)`).

## Цепочка перепроверяется при каждой загрузке

На диске лежит не «последний принятый набор», а вся цепочка принятых
наборов. При загрузке она проигрывается от зашитого корня: каждое звено
проверяется подписью предыдущего. Испорченный или подменённый файл не
проходит проверку и отбрасывается — клиент откатывается к последнему
звену, которое сошлось, вплоть до зашитого набора.

Это не защита от того, кто имеет право писать в этот файл: у него есть
право писать и в `trust.py`. Это защита от порчи, от частичной записи и от
подстановки чужого файла состояния — то есть от того, что случается
гораздо чаще взлома.

## Чего связка НЕ делает

Не проверяет со-подпись новым ключом: сервер её требует при ротации, но
наружу не отдаёт — в ответе одна подпись. Со-подпись и не защищает клиента,
она защищает выпускающего от ротации на ключ, которого ни у кого нет.

Не спасает от КОМПРОМЕТАЦИИ ключа: укравший приватную часть подпишет
ротацию на свой ключ, и цепочка её примет — подпись валидна. От кражи
помогает только доставка набора вне канала: новая сборка.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .trust import TrustError, canonical_keyset, key_fingerprint, verify

KEY_STATUSES = ("active", "revoked")


class KeyringError(ValueError):
    """Набор ключей не годится: не разбирается, не по цепочке, откат."""


def parse_keyset(payload: str) -> tuple[int, list]:
    """
    Разобрать набор и убедиться, что его текст канонизирован.

    Проверка канонизации здесь обязательна и неочевидна: подпись покрывает
    ТЕКСТ, а пользуемся мы РАЗБОРОМ. Без сверки сервер мог бы прислать
    payload, чья подпись верна, но чей разбор содержит лишнее — дубли
    ключей, посторонние поля, — и клиент доверился бы разобранному виду.
    """
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        raise KeyringError(f"Набор ключей не разбирается: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
        raise KeyringError("Набор ключей повреждён.")

    sequence = int(data.get("sequence") or 0)
    keys = data["keys"]
    for key in keys:
        if not isinstance(key, dict):
            raise KeyringError("Набор ключей повреждён.")
        if key.get("status") not in KEY_STATUSES:
            raise KeyringError(
                f"status ключа: {'|'.join(KEY_STATUSES)}, "
                f"не {key.get('status')!r}.")
    if canonical_keyset(sequence, keys) != payload:
        raise KeyringError(
            "Набор ключей не канонизирован: подписан один текст, а разбор "
            "даёт другое содержимое — принимать нельзя.")
    return sequence, keys


def active_public_keys(keys: list) -> list[str]:
    return [str(k["public_key"]) for k in keys if k.get("status") == "active"]


class Keyring:
    """
    Связка одного клиента: зашитый набор + принятые с сервера, на диске.

    `state_path` — файл цепочки. Может отсутствовать: тогда действует
    только зашитый набор.
    """

    def __init__(self, state_path: Optional[Path] = None,
                 bundled: Optional[dict] = None):
        if bundled is None:
            from .bundled import BUNDLED_KEYSET
            bundled = BUNDLED_KEYSET
        self._state_path = Path(state_path) if state_path else None
        self._chain: list[dict] = []
        self._dropped: list[str] = []
        # Пустой набор — документированное «доверять некому»: клиент отвергнет
        # всё. А вот НЕПУСТОЙ, но битый — ошибка сборки, и падать надо здесь,
        # на старте, где это очевидно: иначе она проявится потом отказом
        # обновляться и будет выглядеть сбоем сети.
        payload = (bundled or {}).get("payload") or ""
        self._root = self._parsed(bundled or {}) if payload.strip() else None
        self._load()

    # ---------- состояние ----------

    @property
    def configured(self) -> bool:
        """Есть ли чем проверять. False — сборка без ключа: всё отвергается."""
        return bool(self.active_keys())

    @property
    def dropped(self) -> list[str]:
        """Звенья, отброшенные при загрузке, — для журнала и диагностики."""
        return list(self._dropped)

    def current(self) -> Optional[dict]:
        """Действующий набор: {'sequence', 'keys', 'payload', 'signature'}."""
        return self._chain[-1] if self._chain else self._root

    def sequence(self) -> int:
        current = self.current()
        return int(current["sequence"]) if current else 0

    def active_keys(self) -> list[str]:
        """
        Ключи, которыми СЕЙЧАС разрешено подписывать. Их несколько намеренно:
        ротация не должна обесценивать уже выпущенное, и релиз, подписанный
        вчерашним ключом, остаётся проверяемым, пока тот не отозван явно.
        """
        current = self.current()
        return active_public_keys(current["keys"]) if current else []

    def fingerprints(self) -> list[str]:
        return [key_fingerprint(k) for k in self.active_keys()]

    # ---------- проверка ----------

    def verify_manifest(self, manifest_bytes: bytes, signature: str) -> str:
        """
        Проверить подпись любым активным ключом. Возвращает отпечаток
        подошедшего — его записывают рядом с установленным, чтобы потом было
        видно, чем именно проверено.
        """
        keys = self.active_keys()
        if not keys:
            raise TrustError(
                "В сборке нет ни одного доверенного ключа выпуска — "
                "принимать обновления и пакеты нечем. Это не сбой связи: "
                "клиент собран без ключа.")
        for key in keys:
            try:
                verify(manifest_bytes, signature, key)
                return key_fingerprint(key)
            except TrustError:
                continue
        raise TrustError(
            "Подпись не соответствует ни одному доверенному ключу выпуска. "
            "Содержимое выпущено не тем, кому доверяет это приложение.")

    # ---------- ротация ----------

    def accept(self, payload: str, signature: str) -> dict:
        """
        Принять новый набор с сервера (`GET /updates/keys`).

        Три условия, каждое закрывает свой класс беды:

        1. **подпись действующим ключом** — цепочка доверия; набор,
           подписанный посторонним, был бы способом подменить ключ кому
           угодно;
        2. **строго больший `sequence`** — откат: иначе отозванный набор
           подсовывают обратно и воскрешают снятый ключ, а подпись при этом
           валидна и не помогает;
        3. **остался активный ключ** — набор без активных ключей навсегда
           лишил бы клиента возможности принять хоть что-нибудь, включая
           следующую ротацию.

        Идемпотентно: набор с тем же `sequence`, что уже действует, — не
        ошибка, а «нового нет».
        """
        sequence, keys = parse_keyset(payload)
        current = self.current()
        if current is None:
            raise TrustError(
                "В сборке нет доверенного набора ключей — принять новый "
                "не от чего: цепочке не на что опереться.")
        if sequence == int(current["sequence"]):
            return dict(current)
        if sequence < int(current["sequence"]):
            raise KeyringError(
                f"sequence {sequence} меньше действующего "
                f"{current['sequence']}: приняв его, клиент вернул бы к "
                f"жизни отозванный набор ключей.")
        if not active_public_keys(keys):
            raise KeyringError(
                "В наборе не осталось активных ключей — приняв его, клиент "
                "перестал бы принимать что-либо вообще.")

        self.verify_manifest(payload.encode("utf-8"), signature)

        entry = {"sequence": sequence, "keys": keys,
                 "payload": payload, "signature": signature}
        self._chain.append(entry)
        self._save()
        return dict(entry)

    # ---------- диск ----------

    @staticmethod
    def _parsed(entry: dict) -> dict:
        sequence, keys = parse_keyset(entry.get("payload") or "")
        return {"sequence": sequence, "keys": keys,
                "payload": entry.get("payload") or "",
                "signature": entry.get("signature") or ""}

    def _load(self) -> None:
        if self._state_path is None or not self._state_path.exists():
            return
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            stored = list(raw.get("chain") or [])
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            self._dropped.append(f"файл цепочки не читается: {exc}")
            return

        # Проигрываем цепочку от зашитого корня. Первое несошедшееся звено
        # обрывает её: дальше идти нельзя — доверие к хвосту опиралось бы на
        # звено, которое не проверилось.
        for entry in stored:
            try:
                self.accept_stored(entry)
            except (KeyringError, TrustError) as exc:
                self._dropped.append(
                    f"звено {entry.get('sequence')!r} отброшено: {exc}")
                break

    def accept_stored(self, entry: dict) -> None:
        """Проиграть одно звено сохранённой цепочки (без записи на диск)."""
        payload = entry.get("payload") or ""
        signature = entry.get("signature") or ""
        sequence, keys = parse_keyset(payload)
        current = self.current()
        if current is None or sequence <= int(current["sequence"]):
            raise KeyringError("звено не продолжает цепочку")
        if not active_public_keys(keys):
            raise KeyringError("в звене нет активных ключей")
        self.verify_manifest(payload.encode("utf-8"), signature)
        self._chain.append({"sequence": sequence, "keys": keys,
                            "payload": payload, "signature": signature})

    def _save(self) -> None:
        if self._state_path is None:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"chain": [{"sequence": e["sequence"], "payload": e["payload"],
                           "signature": e["signature"]} for e in self._chain]}
        # Через временный файл: обрыв записи оставил бы связку с обрезанным
        # JSON, то есть без единого доверенного ключа.
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self._state_path)
