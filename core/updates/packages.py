"""
Пакеты узлов графа: клиентская половина.

Канал ОДНОСТОРОННИЙ — пакеты приезжают с сервера, наружу с десктопа не
публикуется ничего. И это тот же самый канал доставки кода, что и
обновление приложения, только мельче гранулярностью: тот же офлайновый
ключ, та же канонизация, та же защита от отката (`trust.py`). Своей схемы
доверия у пакетов нет намеренно — иначе их появление означало бы ещё один
способ выполнить чужой код на этой машине.

## Установка пакета — исполнение чужого кода. Точка.

Это надо сказать прямо, потому что дальше идут проверки, и легко решить,
будто они защищают от вредоносного пакета. Не защищают. Импортированный
модуль может сделать что угодно, и никакие `api_version` с `node_types`
этому не помешают.

Защищает ровно одно — **подпись**: пакет установится, только если выпущен
тем, кому доверяет эта сборка. Всё остальное здесь — защита от ОШИБКИ:

* `api_version` — от пакета, собранного под другой контракт `Node`/`Port`:
  он не «немного не подойдёт», он упадёт посреди генерации у всех, кто
  откроет граф;
* объявленные `node_types` против фактически зарегистрированных — от
  пересобранного не тем, чем подписывали;
* коллизия типов со встроенными и с другими пакетами — от неопределённости
  «чей код исполнится», которую иначе заметят через месяц по странным
  заданиям.

## Префикс обязателен

Типы пакета — `physics.projectile`, встроенные остаются без точки. Так
коллизия со встроенным типом невозможна по построению, и существующие
графы не надо мигрировать. Сервер это же проверяет на публикации, но
проверять обязан и клиент: сервер в модели угроз, а исполняем мы.

## Раскладка на диске

    home/packages/<name>/            установленный пакет
    home/packages/.staged/<name>/    распакованный, ещё не подключённый
    home/packages/.incoming/         карантин скачанного

Установка — тоже переименование, а не распаковка поверх: пакет, распакованный
наполовину, ломает реестр при следующем старте.
"""

from __future__ import annotations

import importlib.util
import sys
from typing import Callable, Iterable, Optional

from .fetch import Downloader, DownloadError, fetch_verified
from .keyring import Keyring
from .state import InstallState
from .trust import TrustError, canonical_manifest
from .updater import Transport, UpdateHome, _clear, safe_extract

# СОСТАВ подписанного манифеста пакета. Зеркало серверного
# `node_packages.SIGNED_FIELDS`. `node_types` входит НАМЕРЕННО: иначе кто
# угодно объявил бы, что его пакет предоставляет `formula`.
SIGNED_FIELDS = ("name", "version", "sequence", "size_bytes", "sha256",
                 "api_version", "node_types")
INT_FIELDS = ("sequence", "size_bytes")

# Версия контракта узлов, которую понимает ЭТА сборка. Пакет, собранный под
# другую, не подключается.
SUPPORTED_API_VERSIONS = ("1",)

# Пространство имён для загружаемых модулей: пакет `physics` становится
# `generator_node_packages.physics`, а не глобальным `physics`. Иначе первый
# же пакет с расхожим именем перехватил бы чужой импорт из site-packages.
MODULE_NAMESPACE = "generator_node_packages"

# Точка входа пакета: модуль обязан её предоставить.
ENTRY_POINT = "register"


class PackageError(RuntimeError):
    """Пакет не годится: подпись, откат, чужой контракт, коллизия типов."""


def package_manifest_bytes(manifest: dict) -> bytes:
    """
    Байты манифеста пакета. `node_types` нормализуется сортировкой и
    склейкой через запятую — ровно как на подписывающей стороне: список в
    JSON сериализуется по-разному в зависимости от порядка, и подпись
    «то сходится, то нет» была бы неотличима от подделки.
    """
    payload = dict(manifest)
    payload["node_types"] = ",".join(
        sorted(str(t) for t in (manifest.get("node_types") or [])))
    return canonical_manifest(payload, SIGNED_FIELDS, INT_FIELDS)


class PackageInstaller:
    """Один экземпляр = один управляемый каталог."""

    def __init__(self, home: UpdateHome, *,
                 keyring: Optional[Keyring] = None,
                 state: Optional[InstallState] = None,
                 transport: Optional[Transport] = None,
                 downloader: Optional[Downloader] = None,
                 call: Optional[Callable] = None):
        self.home = home
        self.keyring = keyring or Keyring(home.keyring_path)
        self.state = state or InstallState(home.state_path)
        self._transport = transport
        self._downloader = downloader
        self._call_impl = call

    # ---------- каталог ----------

    def catalog(self) -> dict:
        """
        Что вообще существует. Ответ дополняется тем, что установлено
        ЛОКАЛЬНО: серверное поле `installed` говорит про набор сервера — то
        есть про то, какие графы он готов исполнять, — и к этой машине
        отношения не имеет.
        """
        resp = dict(self._call("/packages", None, "GET"))
        local = self.state.packages()
        packages = []
        for entry in resp.get("packages") or []:
            item = dict(entry)
            here = local.get(item.get("name"))
            item["local_version"] = here.get("version") if here else None
            item["local_installed"] = here is not None
            item["supported"] = item.get("api_version") in \
                SUPPORTED_API_VERSIONS
            packages.append(item)
        return {"packages": packages}

    # ---------- установка ----------

    def install(self, name: str, version: Optional[str] = None) -> dict:
        """
        Скачать, проверить и подключить пакет.

        Порядок тот же, что у обновления приложения, и по тем же причинам:
        подпись — до сети, откат — до сети, хеш — до распаковки, распаковка
        — рядом, подключение — после переименования.
        """
        params = {"version": version} if version else None
        described = dict(self._call(
            f"/packages/{name}/manifest", params, "GET"))
        manifest = dict(described.get("manifest") or {})
        signature = described.get("signature") or ""

        # Имя сверяем ПЕРВЫМ: дальше по нему ищется установленная версия и
        # проверяется префикс типов, а делать это по чужому имени бессмысленно
        # — манифест другого пакета может быть подписан совершенно честно.
        pkg_name = str(manifest.get("name") or "")
        if pkg_name != name:
            raise PackageError(
                f"Запрашивали пакет {name!r}, а подписан манифест пакета "
                f"{pkg_name!r} — принимать нельзя.")

        fingerprint = self._verified(manifest, signature)
        declared = sorted(str(t) for t in (manifest.get("node_types") or []))

        quarantine = self.home.packages / ".incoming" / f"{name}.zip"
        try:
            archive = fetch_verified(
                str(described.get("url") or ""),
                expected_size=int(manifest.get("size_bytes") or 0),
                expected_sha256=str(manifest.get("sha256") or ""),
                quarantine=quarantine, downloader=self._downloader)
        except DownloadError as exc:
            raise PackageError(str(exc)) from exc

        staged = self.home.packages / ".staged" / name
        target = self.home.packages / name
        try:
            _clear(staged)
            safe_extract(archive, staged)
            _clear(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            staged.replace(target)
        finally:
            archive.unlink(missing_ok=True)
            _clear(staged)

        self.state.set_package(
            name, version=str(manifest.get("version") or ""),
            sequence=int(manifest.get("sequence") or 0),
            api_version=str(manifest.get("api_version") or ""),
            node_types=declared, signing_key_id=fingerprint)
        return {"name": name, "version": manifest.get("version"),
                "sequence": int(manifest.get("sequence") or 0),
                "node_types": declared, "signing_key_id": fingerprint}

    def uninstall(self, name: str) -> bool:
        """Убрать пакет с диска и из состояния. Графы, использующие его узлы,
        перестанут открываться — это честнее, чем исполнять их наполовину."""
        _clear(self.home.packages / name)
        return self.state.drop_package(name)

    def _verified(self, manifest: dict, signature: str) -> str:
        """Подпись, контракт, откат — до того, как что-либо скачано."""
        try:
            fingerprint = self.keyring.verify_manifest(
                package_manifest_bytes(manifest), signature)
        except TrustError as exc:
            raise PackageError(str(exc)) from exc

        api_version = str(manifest.get("api_version") or "")
        if api_version not in SUPPORTED_API_VERSIONS:
            raise PackageError(
                f"Пакет собран под api_version {api_version!r}, эта сборка "
                f"понимает {', '.join(SUPPORTED_API_VERSIONS)}. Подключать "
                f"код, рассчитанный на другой контракт узлов, — значит "
                f"получить падение посреди генерации.")

        name = str(manifest.get("name") or "")
        sequence = int(manifest.get("sequence") or 0)
        installed = self.state.package_sequence(name)
        if sequence <= installed:
            raise PackageError(
                f"Пакет {name}: предложен выпуск {sequence}, установлен "
                f"{installed}. Откат не устанавливается — подпись у старого "
                f"выпуска настоящая, дыры в нём тоже.")

        bad = [t for t in (manifest.get("node_types") or [])
               if not str(t).startswith(f"{name}.")]
        if bad:
            raise PackageError(
                f"Типы узлов пакета обязаны начинаться с «{name}.»; не "
                f"годятся: {', '.join(str(t) for t in bad)}. Без префикса "
                f"пакет перехватил бы встроенный тип.")
        return fingerprint

    # ---------- подключение в реестр ----------

    def load_into(self, registry, *, names: Optional[Iterable[str]] = None,
                  ) -> dict:
        """
        Подключить установленные пакеты к реестру узлов.

        Возвращает `{"loaded": {name: [типы]}, "failed": {name: причина}}`.
        Отказ ОДНОГО пакета не срывает загрузку остальных: приложение должно
        подниматься и с одним битым пакетом, иначе неудачная установка
        оставляет пользователя без программы.
        """
        loaded: dict[str, list] = {}
        failed: dict[str, str] = {}
        installed = self.state.packages()
        for name in sorted(names if names is not None else installed):
            entry = installed.get(name)
            if entry is None:
                failed[name] = "пакет не установлен"
                continue
            try:
                loaded[name] = self._load_one(registry, name, entry)
            except (PackageError, ImportError, AttributeError, OSError) as exc:
                failed[name] = str(exc)
        return {"loaded": loaded, "failed": failed}

    def _load_one(self, registry, name: str, entry: dict) -> list:
        if str(entry.get("api_version") or "") not in SUPPORTED_API_VERSIONS:
            raise PackageError(
                f"Пакет {name} собран под api_version "
                f"{entry.get('api_version')!r} — не подключается.")

        declared = set(entry.get("node_types") or [])
        clash = declared & set(registry.type_ids())
        if clash:
            # Тип уже занят — встроенным или другим пакетом. Два источника
            # одного type_id означают неопределённость, чей код исполнится.
            raise PackageError(
                f"Пакет {name} объявляет уже занятые типы: "
                f"{', '.join(sorted(clash))}.")

        module = self._import(name)
        register = getattr(module, ENTRY_POINT, None)
        if not callable(register):
            raise PackageError(
                f"Пакет {name} не предоставляет {ENTRY_POINT}(registry).")

        # Регистрируем в ЧЕРНОВОЙ реестр, а в рабочий переносим только когда
        # сошлось всё. Иначе пакет, объявивший одно и зарегистрировавший
        # другое, оставлял бы в рабочем реестре свои типы: подключить его мы
        # отказались, а узлы в палитре появились — и отвечать за них некому.
        scratch = type(registry)()
        register(scratch)
        added = set(scratch.type_ids())

        # Сверка объявленного с фактическим. От вредоносного пакета не
        # спасает — он уже исполнился, — но ловит пересборку не тем, чем
        # подписывали, а такое случается куда чаще.
        if added != declared:
            missing = sorted(declared - added)
            extra = sorted(added - declared)
            parts = []
            if extra:
                parts.append("лишние: " + ", ".join(extra))
            if missing:
                parts.append("не появились: " + ", ".join(missing))
            raise PackageError(
                f"Пакет {name} зарегистрировал не то, что объявлено в "
                f"подписанном манифесте ({'; '.join(parts)}).")

        for cls in scratch:
            registry.register(cls)
        return sorted(added)

    def _import(self, name: str):
        """
        Импортировать пакет из его каталога под namespaced-именем.

        Через `spec_from_file_location`, а не добавлением каталога в
        `sys.path`: путь в `sys.path` влияет на ВСЕ последующие импорты
        приложения, и пакет с файлом `json.py` рядом стал бы источником
        стандартной библиотеки.
        """
        root = self.home.packages / name
        init = root / name / "__init__.py"
        if not init.exists():
            raise PackageError(
                f"Пакет {name} не содержит {name}/__init__.py — "
                f"подключать нечего.")
        module_name = f"{MODULE_NAMESPACE}.{name}"
        existing = sys.modules.get(module_name)
        if existing is not None:
            return existing
        spec = importlib.util.spec_from_file_location(
            module_name, init, submodule_search_locations=[str(root / name)])
        if spec is None or spec.loader is None:
            raise PackageError(f"Пакет {name} не импортируется.")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(module_name, None)
            raise
        return module

    # ---------- транспорт ----------

    def _call(self, path: str, params: Optional[dict], method: str) -> dict:
        if self._call_impl is not None:
            return self._call_impl(path, params, method)
        if self._transport is None:
            raise PackageError("Адрес сервера не настроен.")
        try:
            return self._transport(path, params, method)
        except PackageError:
            raise
        except Exception as exc:
            raise PackageError(f"пакеты узлов: {exc}") from exc


def registry_with_packages(build_registry: Callable, installer:
                           PackageInstaller) -> tuple:
    """
    Собрать реестр со встроенными узлами и подключить к нему установленные
    пакеты. Возвращает `(registry, report)`.

    Отдельной функцией, а не внутри `build_default_registry`: встроенный
    реестр обязан собираться без всякого управляемого каталога — тесты,
    headless-режим и первый запуск до настройки сервера должны работать,
    ничего не зная про пакеты.
    """
    registry = build_registry()
    report = installer.load_into(registry)
    return registry, report


def load_installed(home=None, registry=None) -> dict:
    """
    Подключить установленные пакеты к общему реестру узлов при старте.

    Дополняем СУЩЕСТВУЮЩИЙ `DEFAULT_REGISTRY`, а не собираем новый, и это не
    лень: реестр-одиночка стоит умолчанием у исполнителя, документа,
    компилятора и палитры, причём часть из них берёт его ленивым импортом
    внутри функции. Подмена одиночки означала бы, что половина кода видит
    пакеты, а половина нет — и разница всплывала бы посреди генерации.

    Ничего не бросает: пакеты — дополнение, и приложение обязано подниматься
    без них. Что не подключилось и почему — в возвращённом отчёте, его дело
    показать в журнале.
    """
    from ..graph.nodes import DEFAULT_REGISTRY
    from .home import default_home
    try:
        installer = PackageInstaller(home or default_home())
        return installer.load_into(registry or DEFAULT_REGISTRY)
    except Exception as exc:                         # pragma: no cover
        return {"loaded": {}, "failed": {"*": str(exc)}}
