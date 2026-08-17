"""
Bootstrap — единственное место, где соединяются ядро, БД и доменные модули.

Обязанности:
  1. Sync БД: гарантирует наличие subjects (Линал, Матан, Производные, Пределы,
     Английский, Физика, Кинематика, СCУАР, ОПВС) и записей в Partitions
     для всех code-only генераторов.
  2. Build registry: собирает GeneratorRegistry, регистрирует одиночные
     генераторы, фабрики физики/групп/тестов и интерактивные модули.

Этот модуль — единственное место в проекте, где явно указано,
к какому предмету относится каждый code-only генератор.
"""

from __future__ import annotations
import json
import warnings
from pathlib import Path
from typing import Callable, Optional

from core import (
    Capability, GeneratorRegistry, Repository, TaskGenerator,
    GroupGenerator, TestGenerator, WordStatsStore,
)
from core import partition_ids

from exercises.linal.generators import (
    Linal2DGenerator, Linal3DGenerator,
)
from exercises.matan.generators import (
    diff_generators, limits_generators,
)
from exercises.opvs.generators import (
    LogicCircuitGenerator, CCodeMistakesGenerator,
)
from exercises.fisic import FisicConstructorGenerator
from exercises.graph import GraphConstructorGenerator
from exercises.model_tasks import TASKS as MODEL_TASKS
from exercises.english.generators import english_generators_for_path


# Поставщик текущего user_id. Передаётся замыканием из main.py.
UserIdProvider = Callable[[], Optional[str]]


# ---------- Конфигурация: какой code-генератор к какому subject_id ----------

CODE_GENERATORS = [
    # ----- Линал (subject 1) -----
    (1, Linal2DGenerator()),
    (1, Linal3DGenerator()),

    # ----- Производные (subject 10) -----
    *[(10, g) for g in diff_generators()],

    # ----- Пределы (subject 8) -----
    *[(8, g) for g in limits_generators()],

    # ----- ОПВС (subject 11) -----
    (11, LogicCircuitGenerator(partition_id=70)),
    (11, CCodeMistakesGenerator(partition_id=71)),
]


# ---------- Sync БД ----------

def sync_database(repo: Repository, words_dir: Path) -> None:
    """
    Гарантировать существование всех subjects и code-only разделов в БД.
    Вызывать при старте приложения, перед build_registry.
    """
    # WAL — до первых записей: UI-поток и фоновый sync пишут в один файл.
    repo.ensure_wal_mode()

    repo.ensure_subject(1, "Линейная алгебра",       "Линейная алгебра")
    repo.ensure_subject(2, "Английский",             "Английский")
    repo.ensure_subject(3, "Физика",                 "Физика")
    repo.ensure_subject(8, "Пределы",                "Математический анализ")
    repo.ensure_subject(9, "Математический анализ",  "Математический анализ")
    repo.ensure_subject(10, "Производные",           "Математический анализ")
    repo.ensure_subject(11, "ОПВС",                  "ОПВС")

    # Таблица WordStats для межсессионной памяти словарного тренажёра.
    repo.ensure_word_stats_table()

    # Колонка role в users — источник роли сессии (гейтинг ролевых действий).
    repo.ensure_user_role_column()

    # Колонки hidden в Subjects/Partitions — локальное скрытие сущностей.
    repo.ensure_hidden_columns()

    # Колонка owner_user_id в Subjects — владелец предмета с сервера (sync).
    repo.ensure_owner_column()

    # Кэш выданных админом предметов — витрина преподавателя (subject_grants).
    repo.ensure_grants_tables()

    for subject_id, gen in CODE_GENERATORS:
        if gen.partition_id is None:
            continue
        repo.ensure_code_partition(
            partition_id=gen.partition_id,
            subject_id=subject_id,
            name=gen.name,
        )

    # Задания на моделях (exercises/model_tasks): разделы-графы, которые
    # поставляются вместе с приложением. Заводятся РЯДОМ со старыми
    # код-генераторами, а не вместо них: замена сменила бы содержимое уже
    # выданных домашних заданий и разошлась бы со статистикой попыток.
    for entry in MODEL_TASKS.values():
        repo.ensure_graph_partition(
            partition_id=entry["partition_id"],
            subject_id=entry["subject_id"],
            name=entry["title"],
            graph=entry["graph"],
        )

    _repair_physics_constructor(repo)

    # Английские словари. Номер выводится из ИМЕНИ файла (см.
    # core/partition_ids.py) — раньше он выводился из места файла в
    # отсортированном списке, и один и тот же номер означал разные словари
    # на сервере (20 файлов) и на десктопе (12).
    if words_dir.exists():
        from exercises.english.generators import _detect_kind
        _migrate_legacy_english_ids(repo, words_dir)
        for path in sorted(words_dir.glob("*.json")):
            repo.ensure_code_partition(
                partition_id=partition_ids.english_words_id(path.stem),
                subject_id=2,
                name=_english_display_name(path),
            )
            # Разбор транскрипции — ВТОРОЙ раздел того же файла, в своей
            # полосе номеров. Рядом со словарём, а не вместо него: это
            # другое упражнение на том же материале.
            if _detect_kind(path) == "words" and _has_transcriptions(path):
                repo.ensure_code_partition(
                    partition_id=partition_ids.english_transcription_id(
                        path.stem),
                    subject_id=2,
                    name=_english_transcription_name(path),
                )
        _drop_stale_english_partitions(repo, words_dir)


def _english_transcription_name(path: Path) -> str:
    """Имя раздела «выбери транскрипцию» для этого словаря."""
    return f"Английский: {path.stem} (транскрипция)"


def _has_transcriptions(path: Path) -> bool:
    """
    Есть ли в словаре хоть один термин с известной транскрипцией.

    Проверка не косметическая: раздел без единого термина показывал бы
    задание «здесь ничего нет», а раздел, которого нет, ничего не
    обещает. Пустых обещаний в списке у преподавателя быть не должно.
    """
    from exercises.english.generators import (
        WordsTrainerGenerator, _read_json_lenient,
    )
    from core import pronunciation
    try:
        data = _read_json_lenient(path)
        words = WordsTrainerGenerator._flatten_words(data)
    except Exception:                       # noqa: BLE001
        return False
    inline = pronunciation.inline_transcriptions(data)
    return any(pronunciation.transcription_of(t, inline) for t in words)


#: Настройка, которой поставочный раздел «конструктор» предмета Физика
#: не имел никогда. Второй закон Ньютона взят не как «какая-нибудь
#: задача», а как пример из документации самого конструктора
#: (`exercises/fisic/fisic_generater.py`): раздел из поставки обязан
#: показывать, что конструктор умеет, — иначе первое, что видит
#: преподаватель, это пустая форма.
_PHYSICS_CONSTRUCTOR_DEFAULT = {
    "condition": "Тело массой #m# движется с ускорением #a#. "
                 "Найдите действующую на него силу.",
    "result_letter": "F",
    "formula": "m * a",
    "dimension": "Н",
    "variables": {
        "m": {"min": 1, "max": 20, "kind": "natural", "dimension": "кг"},
        "a": {"min": 1, "max": 10, "kind": "natural", "dimension": "м/с^2"},
    },
}


def _repair_physics_constructor(repo: Repository) -> bool:
    """
    Починить поставочный раздел «конструктор» предмета Физика.

    В БД он лежит с `constracted = 0` — то есть заявляет, что его
    обслуживает КОД, — но код-генератора с его номером нет и не было.
    Клик по нему даёт `KeyError: Нет генератора для partition_id=2`.
    По имени и предмету это конструктор физики, то есть `constracted = 1`.

    Правка осторожная: трогаем только запись, которая ещё не настроена
    (пустые параметры). Настроенный раздел — уже работа преподавателя, и
    перезаписывать её нельзя, даже если `constracted` выглядит странно.
    """
    for part in repo.list_partitions_for_subject(3):
        if part.constracted != 0 or part.generation_params:
            continue
        if "конструктор" not in part.name.lower():
            continue
        repo.upsert_partition(
            subject_id=3,
            name=part.name,
            constracted=1,
            generation_params=_PHYSICS_CONSTRUCTOR_DEFAULT,
            partition_id=part.id,
        )
        return True
    return False


def english_partition_ids(words_dir: Path) -> dict[str, int]:
    """
    Номера разделов словарей: `имя файла → id`. Одна функция на sync и на
    сборку реестра — разойтись им нельзя, иначе раздел в БД снова окажется
    без генератора.
    """
    stems = [p.stem for p in sorted(words_dir.glob("*.json"))]
    return partition_ids.assign(stems, partition_ids.ENGLISH_WORDS)


def _migrate_legacy_english_ids(repo: Repository, words_dir: Path) -> None:
    """
    Перевести словари со старых позиционных номеров (1000+i) на выведенные
    из имени, сохранив ссылки на них.

    Опознаём по ИМЕНИ РАЗДЕЛА, а не по номеру: имя — единственное, что в
    старой схеме что-то значило. Номер значил только положение файла в
    каталоге в день запуска.
    """
    by_display = {
        _english_display_name(path): partition_ids.english_words_id(path.stem)
        for path in sorted(words_dir.glob("*.json"))
    }
    for part in repo.list_partitions_for_subject(2):
        if part.constracted != 0 or part.id not in partition_ids.LEGACY_ENGLISH:
            continue
        target = by_display.get(part.name)
        if target is not None and target != part.id:
            repo.renumber_partition(part.id, target)


def _drop_stale_english_partitions(repo: Repository, words_dir: Path) -> None:
    """
    Убрать разделы словарей, которым больше не соответствует ни один файл.

    Такие остаются от переименованных словарей и от синхронизации со старой
    схемой номеров. Открыть их нельзя — генератора нет, — но в списке у
    преподавателя они стоят наравне с рабочими: клик даёт «Нет генератора
    для partition_id=…». Удалять их безопаснее, чем оставлять: раздел без
    генератора не несёт ничего, кроме имени.
    """
    alive = set()
    for path in words_dir.glob("*.json"):
        alive.add(partition_ids.english_words_id(path.stem))
        alive.add(partition_ids.english_transcription_id(path.stem))
    for part in repo.list_partitions_for_subject(2):
        if part.constracted != 0 and part.constracted is not None:
            continue
        in_band = (part.id in partition_ids.LEGACY_ENGLISH
                   or part.id in partition_ids.ENGLISH_WORDS
                   or part.id in partition_ids.ENGLISH_TRANSCRIPTION)
        if in_band and part.id not in alive:
            repo.delete_partition(part.id)


def _english_display_name(path: Path) -> str:
    """Имя раздела для отображения в БД и UI."""
    from exercises.english.generators import _detect_kind
    kind = _detect_kind(path)
    if kind == "sentences":
        return f"Английский: {path.stem} (предложения)"
    return f"Английский: {path.stem}"


# ---------- Сборка реестра ----------

def build_registry(
    repo: Repository,
    words_dir: Path,
    *,
    stats_store: WordStatsStore | None = None,
    user_id_provider: UserIdProvider | None = None,
) -> GeneratorRegistry:
    registry = GeneratorRegistry()

    # 1. Code-only генераторы
    for _subject_id, gen in CODE_GENERATORS:
        if gen.partition_id is not None:
            registry.register(gen)

    # 2. Английские словари
    if words_dir.exists():
        from exercises.english.generators import (
            TranscriptionChoiceGenerator, _detect_kind,
        )
        for path in sorted(words_dir.glob("*.json")):
            pid = partition_ids.english_words_id(path.stem)
            display = _english_display_name(path)
            gen = english_generators_for_path(
                path, pid, name=display,
                stats_store=stats_store,
                user_id_provider=user_id_provider,
            )
            if gen is not None:
                registry.register(gen)
            if _detect_kind(path) == "words" and _has_transcriptions(path):
                registry.register(TranscriptionChoiceGenerator(
                    name=_english_transcription_name(path),
                    words_path=path,
                    partition_id=partition_ids.english_transcription_id(
                        path.stem),
                ))

    # 3. БД: фабрики для физики, групп, тестов
    for subj in repo.list_subjects():
        for part in repo.list_partitions_for_subject(subj.id):
            if registry.has(part.id):
                # Раздел с этим id уже занят генератором из шагов 1-2.
                #
                # Для code-only разделов (constracted=0) это НОРМА, а не
                # коллизия: их записи в БД создаёт sync_database из тех же
                # CODE_GENERATORS/словарей, что шаги 1-2 регистрируют в
                # реестре. Совпадение id — это одна и та же сущность, ветки
                # ниже для constracted=0 всё равно ничего не регистрируют,
                # терять нечего. Раньше предупреждение сыпалось на каждый
                # такой раздел — под 40 строк при каждом запуске, в которых
                # тонула настоящая проблема.
                #
                # Настоящая коллизия — конструкторный раздел (constracted
                # 1..4, создан пользователем), чей id занят кодовым
                # генератором. Такой раздел молча терялся бы —
                # предупреждаем явно, вместо тихого открытия не того
                # задания при клике (см. историю бага).
                if part.constracted != 0:
                    warnings.warn(
                        f"partition_id={part.id} раздела {part.name!r} "
                        f"(предмет {subj.name!r}) уже занят другим генератором "
                        f"в реестре — раздел не будет открываться. Номера "
                        f"полос кода перечислены в core/partition_ids.py; "
                        f"пользовательские разделы должны получать номер "
                        f"через upsert_partition без явного id.",
                        stacklevel=2,
                    )
                continue
            if part.constracted == 1:
                _register_fisic(registry, part)
            elif part.constracted == 2:
                _register_group(registry, repo, part)
            elif part.constracted == 3:
                _register_test(registry, repo, part)
            elif part.constracted == 4:
                _register_graph(registry, part)

    return registry


# ---------- Проверка связи «раздел ↔ генератор» ----------

def unserved_partitions(repo: Repository, registry: GeneratorRegistry,
                        ) -> list[tuple[int, str, str]]:
    """
    Разделы, которые нечем открыть: `(id, имя раздела, имя предмета)`.

    Номер раздела — единственное, что связывает запись в БД с кодом, и до
    сих пор за целостностью этой связи никто не следил. Проверять её надо
    на старте, а не в момент, когда преподаватель нажал «Сгенерировать» и
    получил `KeyError: Нет генератора для partition_id=2`.

    Так и нашёлся раздел «конструктор» предмета Физика: `constracted = 0`
    объявляет «меня обслуживает код», а кода с таким номером нет и не было.
    Проверяются только `constracted = 0`: у остальных генератор строится из
    самой записи БД и существовать обязан по построению.
    """
    problems: list[tuple[int, str, str]] = []
    for subj in repo.list_subjects():
        for part in repo.list_partitions_for_subject(subj.id):
            if part.constracted == 0 and not registry.has(part.id):
                problems.append((part.id, part.name, subj.name))
    return problems


def report_unserved_partitions(repo: Repository,
                               registry: GeneratorRegistry) -> list[str]:
    """
    То же, но текстом и через `warnings` — для вызова на старте.

    Возвращает готовые строки, чтобы вызывающий мог показать их человеку,
    а не только записать в консоль, которой у собранного приложения нет.
    """
    lines = [
        f"Раздел {pid} {name!r} (предмет {subject!r}) объявлен кодовым "
        f"(constracted=0), но генератора с таким номером нет — открыть его "
        f"нельзя."
        for pid, name, subject in unserved_partitions(repo, registry)
    ]
    for line in lines:
        warnings.warn(line, stacklevel=2)
    return lines


# ---------- Фабрики ----------

def _register_fisic(registry: GeneratorRegistry, part) -> None:
    """Раздел-конструктор физики. Конфиг передаётся как dict."""
    config_dict = part.generation_params
    # Если конфиг был не-JSON (хранится под "raw") — попытаемся распарсить.
    if "raw" in config_dict:
        try:
            config_dict = json.loads(config_dict["raw"])
        except (json.JSONDecodeError, TypeError):
            config_dict = {}

    def factory(_params: dict, _pid=part.id, _name=part.name, _cfg=config_dict):
        return FisicConstructorGenerator(
            partition_id=_pid, name=_name, config=_cfg
        )

    registry.register_factory(part.id, factory)


def _register_graph(registry: GeneratorRegistry, part) -> None:
    """Раздел-граф (constracted=4). Описание графа передаётся как dict/JSON."""
    config_dict = part.generation_params
    # Если конфиг хранится как сырая строка под "raw" — попытаемся распарсить.
    if "raw" in config_dict:
        try:
            config_dict = json.loads(config_dict["raw"])
        except (json.JSONDecodeError, TypeError):
            config_dict = {}

    def factory(_params: dict, _pid=part.id, _name=part.name, _cfg=config_dict):
        return GraphConstructorGenerator(
            partition_id=_pid, name=_name, config=_cfg
        )

    registry.register_factory(part.id, factory)


def _register_group(registry: GeneratorRegistry, repo: Repository, part) -> None:
    raw = part.generation_params

    def factory(_params: dict, _registry=registry, _repo=repo,
                _pid=part.id, _name=part.name, _raw=raw):
        items = _raw.get("data") if isinstance(_raw, dict) and "data" in _raw \
                else _raw if isinstance(_raw, list) else []
        child_ids: list[int] = []
        for it in items if isinstance(items, list) else []:
            if isinstance(it, dict) and "task_id" in it:
                child_ids.append(int(it["task_id"]))
            elif isinstance(it, int):
                child_ids.append(it)
        children: list[TaskGenerator] = []
        for cid in child_ids:
            if not _registry.has(cid):
                continue
            cpart = _repo.get_partition(cid)
            child = _registry.get(cid, cpart.generation_params if cpart else {})
            children.append(child)
        if not children:
            raise RuntimeError(
                f"Группа {_name!r} (#{_pid}): не удалось собрать детей."
            )
        return GroupGenerator(name=_name, children=children, partition_id=_pid)

    registry.register_factory(part.id, factory)


def _register_test(registry: GeneratorRegistry, repo: Repository, part) -> None:
    raw = part.generation_params

    def factory(_params: dict, _registry=registry, _repo=repo,
                _pid=part.id, _name=part.name, _raw=raw):
        items = _raw.get("data") if isinstance(_raw, dict) and "data" in _raw \
                else _raw if isinstance(_raw, list) else []

        pairs = []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            task_id = it.get("task_id")
            raw_count = it.get("task_cnt", it.get("count", 1))
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                count = 1
            if count <= 0:
                continue
            if task_id is None or not _registry.has(int(task_id)):
                continue
            cpart = _repo.get_partition(int(task_id))
            child = _registry.get(int(task_id),
                                  cpart.generation_params if cpart else {})
            if Capability.GROUPABLE not in child.capabilities:
                continue
            pairs.append((child, count))

        if not pairs:
            raise RuntimeError(
                f"Тест {_name!r} (#{_pid}): не удалось собрать заданий."
            )
        return TestGenerator(name=_name, items=pairs, partition_id=_pid)

    registry.register_factory(part.id, factory)
