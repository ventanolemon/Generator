"""
Обновление приложения: клиентская половина.

Серверная (`GenerationWeb/core/updates.py`) хранит и раздаёт подписанное.
Здесь — то, ради чего она вообще имеет смысл: проверка. Сервер входит в
модель угроз, поэтому ни одно его утверждение не принимается на веру.

## Порядок, и почему именно такой

    1. подпись манифеста          проверяется ДО того, как открыто соединение
    2. sequence > установленного  до скачивания: качать откат незачем
    3. скачивание в карантин      с ограничением по подписанному размеру
    4. sha256                     сверяется с подписанным
    5. распаковка в staged/       рядом, не поверх работающего
    6. переключение               два переименования плюс запись намерения
    7. запись состояния           только после успешного переключения

Пункты 1–2 стоят раньше сети намеренно: манифест приходит внутри ответа
`/updates/check`, и решать, стоит ли вообще качать, надо по подписанному
описанию, а не по тому, что скажет сервер потом.

## Почему установка не «поверх»

Распаковка поверх работающего дерева необратима: упало на середине — нет ни
старой версии, ни новой. Здесь новое дерево готовится рядом и целиком, а
переключение — это переименование каталогов: старое уезжает в `backup/`,
проверенное встаёт на его место. Оба переименования на одной файловой
системе, то есть настолько атомарны, насколько это вообще бывает с
каталогами.

Дыра между двумя переименованиями («старого уже нет, нового ещё нет»)
закрывается ЗАПИСЬЮ НАМЕРЕНИЯ до начала: обрыв питания посреди
переключения обнаруживается при следующем старте и доигрывается — вперёд,
если новое дерево готово, назад, если нет.

## Кто применяет

`apply_pending()` предназначен для ЗАПУСКАЮЩЕГО, а не для самого
приложения: подменять дерево, из которого уже импортирован работающий код,
нельзя. На Windows это просто не выйдет (файлы заняты), на Linux выйдет —
и это хуже: процесс останется со старыми открытыми файлами, а любой ленивый
импорт после подмены притащит в него новый код. Поэтому метод отказывается
трогать дерево, внутри которого сам находится.

## `mandatory` — сигнал, не команда

Сервер сообщает, что версия ниже минимально поддерживаемой. Что с этим
делать — решает приложение. Принуждать сервер не может и не должен: это был
бы ещё один способ навязать клиенту чужой выбор.
"""

from __future__ import annotations

import json
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Optional

from .fetch import Downloader, DownloadError, fetch_verified
from .keyring import Keyring
from .state import InstallState
from .trust import TrustError, canonical_manifest

# path, params (None у GET без параметров), method → JSON-ответ
Transport = Callable[[str, Optional[dict], str], dict]

# СОСТАВ подписанного манифеста релиза. Зеркало серверного
# `updates.SIGNED_FIELDS`: разойдётся состав — не сойдётся ни одна подпись.
SIGNED_FIELDS = ("version", "channel", "platform", "sequence",
                 "size_bytes", "sha256")
INT_FIELDS = ("sequence", "size_bytes")

# Резервные копии дерева: NNNN-версия. Номер впереди, чтобы порядок копий
# читался из имени и не зависел ни от разрешения mtime, ни от разбора semver.
_BACKUP_RE = re.compile(r"^(\d{4})-")


class UpdateError(RuntimeError):
    """Обновление не годится, не скачалось или не установилось."""


def release_manifest_bytes(manifest: dict) -> bytes:
    return canonical_manifest(manifest, SIGNED_FIELDS, INT_FIELDS)


class UpdateHome:
    """
    Раскладка управляемого каталога. Всё служебное — рядом с деревом
    приложения, но НЕ внутри него: иначе переключение дерева уносило бы с
    собой состояние, ключи и подготовленное обновление.
    """

    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def app(self) -> Path:
        return self.root / "app"

    @property
    def staged(self) -> Path:
        return self.root / "staged"

    @property
    def backup(self) -> Path:
        return self.root / "backup"

    @property
    def incoming(self) -> Path:
        return self.root / "incoming"

    @property
    def packages(self) -> Path:
        return self.root / "packages"

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    @property
    def keyring_path(self) -> Path:
        return self.root / "keyring.json"

    @property
    def intent_path(self) -> Path:
        return self.root / "apply.json"


def safe_extract(archive: Path, target: Path) -> None:
    """
    Распаковать zip, отказываясь от записи за пределы `target`.

    `zipfile` и сам обрезает `..` и ведущий слэш, но полагаться на это в
    канале доставки кода не стоит: проверка стоит шести строк, а
    неожиданность в поведении стандартной библиотеки стоила бы каталога с
    чужими файлами где-нибудь в `~/.ssh`.
    """
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    resolved_target = target.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            destination = (target / member).resolve()
            if destination != resolved_target and resolved_target not in \
                    destination.parents:
                raise UpdateError(
                    f"Архив пытается писать за пределы каталога установки: "
                    f"{member!r}. Такой артефакт не распаковывается.")
        zf.extractall(target)


class Updater:
    """
    Один экземпляр = один управляемый каталог.

    Транспорт инжектируем: боевой ходит по HTTP, тестовый отдаёт из памяти.
    """

    def __init__(self, home: UpdateHome, *,
                 base_url: str = "",
                 keyring: Optional[Keyring] = None,
                 state: Optional[InstallState] = None,
                 transport: Optional[Transport] = None,
                 downloader: Optional[Downloader] = None,
                 channel: str = "stable",
                 platform: str = "any"):
        self.home = home
        self.channel = channel
        self.platform = platform
        self._base_url = base_url
        self.keyring = keyring or Keyring(home.keyring_path)
        self.state = state or InstallState(home.state_path)
        self._transport = transport or self._http_transport()
        self._downloader = downloader

    def set_base_url(self, url: str) -> None:
        self._base_url = url or ""

    def has_server(self) -> bool:
        return bool(self._base_url.strip())

    # ---------- ротация ключей ----------

    def refresh_keys(self) -> Optional[dict]:
        """
        Догнать ротацию: забрать действующий набор и принять его, если он
        продолжает цепочку.

        Зовётся ПЕРЕД проверкой обновления, а не после: релиз может быть
        подписан уже новым ключом, и без свежего набора он выглядел бы
        подделкой. Ошибка здесь не фатальна для остального — набор мог просто
        не смениться; фатален отказ цепочки, и он выходит наружу.

        Возвращает принятый набор либо None, если нового нет.
        """
        resp = self._call("/updates/keys", None, "GET")
        if not resp.get("configured"):
            return None
        payload = resp.get("payload") or ""
        if not payload:
            return None
        accepted = self.keyring.accept(payload, resp.get("signature") or "")
        return accepted if accepted["sequence"] > 0 else None

    # ---------- проверка ----------

    def check(self) -> dict:
        """
        Спросить сервер и ПРОВЕРИТЬ ответ.

        Возвращает ответ сервера, дополненный полями:
          `verified`        — подпись сошлась доверенным ключом;
          `signing_key_id`  — отпечаток подошедшего ключа;
          `rejected`        — причина отказа, если ответ не годится.

        Отказ не бросается исключением: «сервер предлагает откат» — не
        ошибка связи, а нормальный ответ, который приложение показывает
        пользователю. Бросается только то, что мешает проверить вообще.
        """
        params = {"current_version": self.state.app_version(),
                  "current_sequence": self.state.app_sequence(),
                  "channel": self.channel, "platform": self.platform}
        resp = dict(self._call("/updates/check", params, "GET"))
        if not resp.get("update_available"):
            return resp

        manifest = dict(resp.get("manifest") or {})
        signature = resp.get("signature") or ""
        try:
            fingerprint = self.keyring.verify_manifest(
                release_manifest_bytes(manifest), signature)
        except TrustError as exc:
            resp["update_available"] = False
            resp["verified"] = False
            resp["rejected"] = str(exc)
            return resp

        sequence = int(manifest.get("sequence") or 0)
        installed = self.state.app_sequence()
        if sequence <= installed:
            # Подпись валидна — и именно поэтому одной подписи мало: старый
            # релиз с уже известной дырой подписан честно.
            resp["update_available"] = False
            resp["verified"] = True
            resp["rejected"] = (
                f"Предложен выпуск {sequence}, установлен {installed}. "
                f"Откат к ранее выпущенному не устанавливается: подпись у "
                f"него настоящая, дыры в нём — тоже.")
            return resp

        # Канал и платформа входят в подпись; сверяем, что нам предлагают то,
        # что мы просили. Иначе честно подписанную сборку для другой
        # платформы можно подсунуть как «обновление».
        if str(manifest.get("channel") or "") != self.channel or \
                str(manifest.get("platform") or "") != self.platform:
            resp["update_available"] = False
            resp["verified"] = True
            resp["rejected"] = (
                f"Манифест выпущен для {manifest.get('channel')}/"
                f"{manifest.get('platform')}, а запрашивали "
                f"{self.channel}/{self.platform}.")
            return resp

        resp["verified"] = True
        resp["signing_key_id"] = fingerprint
        return resp

    # ---------- подготовка ----------

    def stage(self, checked: dict) -> dict:
        """
        Скачать, сверить и распаковать проверенное обновление рядом.

        На вход — ответ `check()`, а не произвольный словарь: подпись уже
        проверена там, и повторять проверку здесь не «на всякий случай», а
        обязательно — между проверкой и установкой лежит сеть и диск.
        """
        if not checked.get("update_available"):
            raise UpdateError(checked.get("rejected")
                              or "Обновлять нечего.")
        manifest = dict(checked.get("manifest") or {})
        signature = checked.get("signature") or ""

        # Проверка ПОВТОРНО, перед тем как что-либо скачивать: `checked` мог
        # приехать откуда угодно, в том числе из кеша UI.
        fingerprint = self.keyring.verify_manifest(
            release_manifest_bytes(manifest), signature)

        sequence = int(manifest.get("sequence") or 0)
        if sequence <= self.state.app_sequence():
            raise UpdateError(
                f"Выпуск {sequence} не новее установленного "
                f"{self.state.app_sequence()}.")

        version = str(manifest.get("version") or "")
        quarantine = self.home.incoming / f"{version}.zip"
        try:
            archive = fetch_verified(
                str(checked.get("url") or ""),
                expected_size=int(manifest.get("size_bytes") or 0),
                expected_sha256=str(manifest.get("sha256") or ""),
                quarantine=quarantine, downloader=self._downloader)
        except DownloadError as exc:
            raise UpdateError(str(exc)) from exc

        staged = self.home.staged / version
        partial = self.home.staged / f".{version}.partial"
        try:
            _clear(partial)
            safe_extract(archive, partial)
            _clear(staged)
            partial.replace(staged)
        finally:
            # Карантин чистим всегда: сверенный архив уже распакован, а
            # несверенного здесь не бывает — fetch_verified его не оставляет.
            archive.unlink(missing_ok=True)
            _clear(partial)

        pending = {"version": version, "sequence": sequence,
                   "signing_key_id": fingerprint,
                   "staged_at": time.time(),
                   "path": str(staged)}
        self.state.set_pending(pending)
        return pending

    # ---------- переключение ----------

    def apply_pending(self, *, allow_self_replace: bool = False) -> Optional[dict]:
        """
        Применить подготовленное обновление. Возвращает применённое либо
        None, если применять нечего.

        Зовётся ЗАПУСКАЮЩИМ до импорта кода приложения. Подменять дерево, из
        которого уже импортирован работающий код, нельзя: на Windows не
        выйдет вовсе, на Linux выйдет — и процесс останется со старыми
        открытыми файлами, а следующий ленивый импорт притащит в него новый
        код. `allow_self_replace` существует только для тестов.
        """
        self.recover()
        pending = self.state.pending()
        if not pending:
            return None
        staged = Path(pending.get("path") or "")
        if not staged.is_dir():
            self.state.set_pending(None)
            raise UpdateError(
                f"Подготовленное обновление {pending.get('version')!r} "
                f"исчезло с диска ({staged}); подготовьте заново.")

        if not allow_self_replace and _contains(self.home.app, Path(__file__)):
            raise UpdateError(
                "Отказ подменять дерево, из которого выполняется этот код. "
                "Переключение делает запускающий, до импорта приложения.")

        backup = self._free_backup(str(pending.get("version") or "0"))
        intent = {"staged": str(staged), "app": str(self.home.app),
                  "backup": str(backup), "version": pending.get("version"),
                  "sequence": pending.get("sequence"),
                  "signing_key_id": pending.get("signing_key_id")}
        self._write_intent(intent)
        try:
            self._swap(intent)
        except OSError as exc:
            self._rollback(intent)
            raise UpdateError(
                f"Переключение не удалось, версия осталась прежней: "
                f"{exc}") from exc

        self._finish(intent)
        self._prune_backups()
        return pending

    def _free_backup(self, version: str) -> Path:
        """
        Имя для резервной копии: порядковый номер плюс версия.

        Номер, а не метка времени. Метки в секундах не хватает — два
        обновления подряд укладываются в одну секунду легко, а
        переименование каталога поверх существующего непустого падает
        (`Directory not empty`), то есть переключение срывалось бы ровно
        тогда, когда обновляются часто. Дробная часть спасала бы не везде:
        разрешение mtime зависит от файловой системы, и полагаться на неё в
        механизме, от которого зависит наличие у пользователя программы, не
        стоит.

        Номер заодно даёт точный порядок копий по ИМЕНИ — сортировать их по
        версии нельзя (`1.10` против `1.9`), а по mtime — то же самое
        разрешение.
        """
        self.home.backup.mkdir(parents=True, exist_ok=True)
        used = [int(m.group(1)) for m in
                (_BACKUP_RE.match(p.name) for p in self.home.backup.iterdir())
                if m]
        index = max(used) + 1 if used else 1
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", version) or "0"
        return self.home.backup / f"{index:04d}-{safe}"

    def _prune_backups(self, keep: int = 1) -> None:
        """
        Оставить последние копии, старые убрать.

        Иначе каждое обновление оставляет полное дерево предыдущей версии, и
        через год на диске лежит десяток сборок. Одной копии достаточно:
        откат нужен ровно к тому, что стояло до последнего переключения.
        """
        if not self.home.backup.is_dir():
            return
        backups = sorted((p for p in self.home.backup.iterdir()
                          if p.is_dir() and _BACKUP_RE.match(p.name)),
                         key=lambda p: p.name, reverse=True)
        for stale in backups[keep:]:
            shutil.rmtree(stale, ignore_errors=True)

    def recover(self) -> Optional[str]:
        """
        Доиграть прерванное переключение. Возвращает, что было сделано.

        Обрыв возможен ровно в одном месте — между «старое дерево уехало» и
        «новое встало». Запись намерения сделана ДО первого переименования,
        поэтому при следующем старте видно, что происходило, и однозначно
        видно, куда доигрывать: новое дерево на месте — вперёд, нет —
        назад.
        """
        if not self.home.intent_path.exists():
            return None
        try:
            intent = json.loads(
                self.home.intent_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.home.intent_path.unlink(missing_ok=True)
            return "намерение не прочиталось, отброшено"

        app = Path(intent.get("app") or "")
        staged = Path(intent.get("staged") or "")
        backup = Path(intent.get("backup") or "")

        if app.is_dir() and staged.is_dir():
            # Оба каталога на месте — переключение не начиналось. Намерение
            # отбрасываем, состояние НЕ трогаем: подготовленное так и
            # осталось подготовленным.
            self.home.intent_path.unlink(missing_ok=True)
            return "переключение не начиналось"
        if app.is_dir():
            # Дерево на месте, подготовленного больше нет — переключение
            # завершилось, не успев записать состояние. Дописываем.
            self._finish(intent)
            return "переключение уже завершено"
        if staged.is_dir():
            staged.replace(app)
            self._finish(intent)
            return "переключение доиграно вперёд"
        if backup.is_dir():
            backup.replace(app)
            self.home.intent_path.unlink(missing_ok=True)
            return "переключение откачено"
        self.home.intent_path.unlink(missing_ok=True)
        return "ни нового, ни старого дерева не осталось"

    # ---------- внутреннее ----------

    def _write_intent(self, intent: dict) -> None:
        self.home.root.mkdir(parents=True, exist_ok=True)
        tmp = self.home.intent_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(intent, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.home.intent_path)

    def _swap(self, intent: dict) -> None:
        app = Path(intent["app"])
        staged = Path(intent["staged"])
        backup = Path(intent["backup"])
        backup.parent.mkdir(parents=True, exist_ok=True)
        app.parent.mkdir(parents=True, exist_ok=True)
        if app.is_dir():
            app.replace(backup)
        staged.replace(app)

    def _rollback(self, intent: dict) -> None:
        app = Path(intent["app"])
        backup = Path(intent["backup"])
        if not app.is_dir() and backup.is_dir():
            backup.replace(app)
        self.home.intent_path.unlink(missing_ok=True)

    def _finish(self, intent: dict) -> None:
        self.state.set_app(version=str(intent.get("version") or ""),
                           sequence=int(intent.get("sequence") or 0),
                           signing_key_id=str(
                               intent.get("signing_key_id") or ""))
        self.state.set_pending(None)
        self.home.intent_path.unlink(missing_ok=True)

    # ---------- транспорт ----------

    def _call(self, path: str, params: Optional[dict], method: str) -> dict:
        try:
            return self._transport(path, params, method)
        except UpdateError:
            raise
        except (TrustError, ValueError):
            raise
        except Exception as exc:
            raise UpdateError(f"обновление: {exc}") from exc

    def _http_transport(self) -> Transport:
        def call(path: str, params: Optional[dict], method: str) -> dict:
            url = self._base_url.rstrip("/") + path
            body = None
            if method == "GET" and params:
                url += "?" + urllib.parse.urlencode(params)
            elif params is not None:
                body = json.dumps(params, ensure_ascii=False).encode()
            # Без заголовков идентичности: /updates/* намеренно открыты —
            # обновление безопасности должно доезжать и до того, у кого
            # протух токен.
            req = urllib.request.Request(
                url, data=body, method=method,
                headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read().decode()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = json.loads(exc.read().decode()).get("detail", "")
                except Exception:
                    pass
                raise UpdateError(
                    f"HTTP {exc.code}: {detail or exc.reason}") from exc
        return call


def _clear(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink(missing_ok=True)


def _contains(directory: Path, candidate: Path) -> bool:
    try:
        directory = directory.resolve()
        candidate = candidate.resolve()
    except OSError:                                  # pragma: no cover
        return False
    return directory == candidate or directory in candidate.parents
