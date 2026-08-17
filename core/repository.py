"""
Repository — слой доступа к БД.

Все запросы параметризованы (никаких f-строк в SQL).
Все обращения к Subjects/Partitions идут только через этот класс —
никакого `sqlite3.connect(db)` в других файлах.
"""

from __future__ import annotations
import hashlib
import json
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional

from . import partition_ids


# Ключ бакета видимости для гостя (login = None). Пустая строка, а не NULL:
# user_login входит в первичный ключ, а NULL в SQLite не равен сам себе —
# на NULL-ключе PRIMARY KEY не защитил бы от дублей.
GUEST_VISIBILITY_KEY = ""


@dataclass(frozen=True)
class Subject:
    id: int
    name: str
    parent_name: str  # значение поля pra_subject
    hidden: bool = False      # скрыт ЛИЧНО у текущего зрителя (не синкается)
    # Владелец предмета с сервера (owner_user_id). None = встроенный/системный
    # предмет (сиды bootstrap), виден всем. Строка/число — сервер назначает;
    # на десктоп попадает через sync-pull. Access-control по нему — на СЕРВЕРЕ
    # (pull-scope), а не здесь (см. заметку в docs/ui_rework_plan.md).
    owner_user_id: str | None = None

    @property
    def is_builtin(self) -> bool:
        """Встроенный/системный предмет (без владельца) — общий для всех."""
        return self.owner_user_id is None


@dataclass(frozen=True)
class GrantsSnapshot:
    """
    Снимок выданных пользователю предметов (см. docs/subject_grants.md).

    Права раздаёт админ, живут они на сервере; это лишь локальный кэш, чтобы
    витрина офлайн была той же, что онлайн. ОТСУТСТВИЕ снимка (None вместо
    объекта) и пустой снимок — разные вещи: первое значит «мы ещё не знаем»
    и витрину не ограничивает, второе — осознанное «ничего не выдано».
    """

    subject_ids: frozenset[int] = frozenset()
    default_access: str = "all"        # "all" | "none"
    scope_version: int = 0

    @property
    def restricts(self) -> bool:
        """
        Ограничивает ли снимок витрину.

        При default_access="all" преподаватель без единой выдачи видит всё —
        это делает выкатку безопасной (никто не остаётся с пустым экраном,
        пока админ не прошёл по списку). Но как только ему выдали хоть один
        предмет, набор становится исчерпывающим: разграничение включается по
        мере раздачи. При default_access="none" ограничение действует всегда,
        включая пустой список — это и есть строгий режим.
        """
        return self.default_access == "none" or bool(self.subject_ids)

    def allows(self, subject_id: int) -> bool:
        return not self.restricts or subject_id in self.subject_ids


@dataclass(frozen=True)
class Partition:
    id: int
    subject_id: int
    name: str
    constracted: int          # 0=одиночный, 1=конструктор, 2=группа, 3=тест
    generation_params: dict   # распарсенный JSON или {}
    hidden: bool = False      # скрыт ЛИЧНО у текущего зрителя (не синкается)


# Какой view_kind использовать для каждого constracted:
#   0 — single  (StaticTaskView)
#   1 — table   (TableTaskView)
#   2 — table   (TableTaskView, но генератор — GroupGenerator)
#   3 — test    (TestExportView)
_VIEW_KIND_BY_CONSTRACTED = {
    0: "single",
    1: "table",
    2: "table",
    3: "test",
    4: "table",
}


class Repository:
    """Доступ к таблицам Subjects, Partitions, users."""

    def __init__(self, db_path: str | Path, *, sync_listener=None):
        self.db_path = Path(db_path)
        # Необязательный слушатель мутаций (утиный интерфейс: partition_changed/
        # partition_deleted) — превращает пользовательские правки разделов в
        # записи outbox синхронизации. None у тестов/офлайн-сборок. Ставится в
        # main.py ПОСЛЕ стартовых сидов, чтобы они не сыпались в очередь.
        self.sync_listener = sync_listener
        # Таблицы персональной видимости созданы в этом процессе (кэш, чтобы
        # не ходить в БД на каждую выборку). См. ensure_visibility_tables.
        self._visibility_ready = False
        # То же для таблиц кэша выдач (см. ensure_grants_tables).
        self._grants_ready = False

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        # foreign_keys — настройка соединения, не файла: без неё SQLite
        # разбирает объявленные REFERENCES, но не проверяет их.
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    def ensure_wal_mode(self) -> None:
        """
        Перевести файл БД в WAL. Идемпотентно, вызывать один раз на старте.

        На одном файле работают два писателя: UI-поток (правки разделов,
        попытки) и фоновый _SyncWorker (QThread), который ведёт outbox через
        SyncStore(DB_PATH) — ту же самую БД. В журнале по умолчанию (delete)
        читатель и писатель блокируют друг друга, и параллельный синк ловит
        SQLITE_BUSY «database is locked». В WAL читатели не ждут писателя.

        Режим хранится в самом файле, поэтому SyncStore его наследует.
        На сетевых ФС WAL не поддерживается — там остаёмся на delete.
        """
        try:
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.DatabaseError:
            pass

    # ---------- Скрытие (локальная видимость, D3) ----------
    #
    # Скрытие — ЛОКАЛЬНАЯ настройка витрины этой копии БД: sync-протокол её
    # не знает и не передаёт (скрытие ≠ удаление; tombstones — только про
    # настоящие удаления). Скрытая сущность остаётся в БД, генераторы по ней
    # продолжают работать.
    #
    # Настройка эта — ПЕРСОНАЛЬНАЯ, хранится в таблицах SubjectVisibility /
    # PartitionVisibility с ключом (логин, сущность). Раньше она жила
    # колонкой `hidden` прямо в Subjects/Partitions, то есть одной строкой на
    # весь файл БД: гость скрывал предмет — предмет пропадал и у всех
    # преподавателей, работающих на этой же машине. Колонки оставлены на
    # месте как legacy (их значения разово перенесены, см.
    # _migrate_legacy_hidden), но фильтрация по ним больше не идёт.
    #
    # Гость — не «никто»: у него свой бакет с ключом GUEST_VISIBILITY_KEY,
    # общий для всех гостевых сеансов машины. Его выбор так же переживает
    # перезапуск и так же не влияет на вошедших пользователей.

    def _visibility_key(self, user_login: str | None) -> str:
        """Ключ бакета видимости: логин пользователя или гостевой sentinel."""
        return GUEST_VISIBILITY_KEY if not user_login else user_login

    def ensure_visibility_tables(self) -> None:
        """
        Гарантировать таблицы персональной видимости. Идемпотентно; результат
        кэшируется на экземпляр, чтобы не открывать соединение на каждый
        list_subjects (он зовётся на каждую смену предмета).
        """
        if self._visibility_ready:
            return
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS SubjectVisibility ("
                "  user_login TEXT NOT NULL,"
                "  subject_id INTEGER NOT NULL,"
                "  hidden INTEGER NOT NULL DEFAULT 0,"
                "  PRIMARY KEY (user_login, subject_id))")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS PartitionVisibility ("
                "  user_login TEXT NOT NULL,"
                "  partition_id INTEGER NOT NULL,"
                "  hidden INTEGER NOT NULL DEFAULT 0,"
                "  PRIMARY KEY (user_login, partition_id))")
            conn.commit()
            self._migrate_legacy_hidden(conn)
        self._visibility_ready = True

    @staticmethod
    def _migrate_legacy_hidden(conn: sqlite3.Connection) -> None:
        """
        Разово перенести общий на файл флаг `hidden` в персональные таблицы.

        Кому отдать унаследованные скрытия — вопрос без верного ответа: кто
        именно их проставил, БД не помнит. Отдаём ГОСТЮ и обнуляем колонку.
        Это ровно тот сценарий, из-за которого настройку и разделяют: скрытое
        гостем перестаёт быть скрытым у преподавателей, а сам гость своих
        скрытий не теряет. Вошедший пользователь, если что-то скрывал раньше,
        увидит это снова — и скроет заново уже только у себя.

        Идемпотентно: после переноса колонка обнулена, переносить нечего.
        """
        for table, column, target, key in (
            ("Subjects", "subject_id", "SubjectVisibility", "id"),
            ("Partitions", "partition_id", "PartitionVisibility", "id"),
        ):
            cols = {r[1] for r in
                    conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if "hidden" not in cols:
                continue
            rows = [r[0] for r in conn.execute(
                f"SELECT {key} FROM {table} WHERE hidden = 1").fetchall()]
            if not rows:
                continue
            conn.executemany(
                f"INSERT OR IGNORE INTO {target} "
                f"(user_login, {column}, hidden) VALUES (?, ?, 1)",
                [(GUEST_VISIBILITY_KEY, r) for r in rows])
            conn.execute(f"UPDATE {table} SET hidden = 0 WHERE hidden = 1")
        conn.commit()

    def ensure_hidden_columns(self) -> None:
        """
        Гарантировать legacy-колонки hidden в Subjects и Partitions, а также
        таблицы персональной видимости. Идемпотентно.

        Колонки больше не читаются при выборках, но создаются по-прежнему:
        старые копии БД и внешние инструменты могут на них рассчитывать, а
        _migrate_legacy_hidden опирается на их наличие при переносе.
        """
        with self._connect() as conn:
            for table in ("Subjects", "Partitions"):
                cols = [r[1] for r in conn.execute(
                    f"PRAGMA table_info({table})").fetchall()]
                if "hidden" not in cols:
                    conn.execute(
                        f"ALTER TABLE {table} ADD COLUMN "
                        f"hidden INTEGER NOT NULL DEFAULT 0")
            conn.commit()
        self.ensure_visibility_tables()

    def ensure_owner_column(self) -> None:
        """
        Гарантировать колонку owner_user_id в Subjects. Идемпотентно. NULL =
        встроенный предмет (виден всем). Значение приходит с сервера через
        sync-pull; локально предметы не создаются, поэтому пишет её только
        синк. Access-control по владельцу — серверный pull-scope, не десктоп.
        """
        with self._connect() as conn:
            cols = [r[1] for r in
                    conn.execute("PRAGMA table_info(Subjects)").fetchall()]
            if "owner_user_id" not in cols:
                conn.execute(
                    "ALTER TABLE Subjects ADD COLUMN owner_user_id TEXT")
            conn.commit()

    def set_subject_owner(self, subject_id: int,
                          owner_user_id: str | None) -> None:
        """Проставить владельца предмета (используется синком/тестами)."""
        self.ensure_owner_column()
        with self._connect() as conn:
            conn.execute("UPDATE Subjects SET owner_user_id = ? WHERE id = ?",
                         (owner_user_id, subject_id))
            conn.commit()

    def set_subject_hidden(self, subject_id: int, hidden: bool, *,
                           user_login: str | None = None) -> None:
        """Скрыть/показать предмет ЛИЧНО у user_login (None — у гостя)."""
        self._set_hidden("SubjectVisibility", "subject_id", subject_id,
                         hidden, user_login)

    def set_partition_hidden(self, partition_id: int, hidden: bool, *,
                             user_login: str | None = None) -> None:
        """Скрыть/показать раздел ЛИЧНО у user_login (None — у гостя)."""
        self._set_hidden("PartitionVisibility", "partition_id", partition_id,
                         hidden, user_login)

    def _set_hidden(self, table: str, column: str, entity_id: int,
                    hidden: bool, user_login: str | None) -> None:
        self.ensure_visibility_tables()
        key = self._visibility_key(user_login)
        with self._connect() as conn:
            if hidden:
                conn.execute(
                    f"INSERT INTO {table} (user_login, {column}, hidden) "
                    f"VALUES (?, ?, 1) "
                    f"ON CONFLICT(user_login, {column}) DO UPDATE SET hidden = 1",
                    (key, entity_id))
            else:
                # Показать = убрать запись, а не хранить hidden=0: бакет
                # держит только осознанные скрытия, «показано» — умолчание.
                conn.execute(
                    f"DELETE FROM {table} WHERE user_login = ? AND {column} = ?",
                    (key, entity_id))
            conn.commit()

    # ---------- Выдачи предметов (кэш серверных прав) ----------
    #
    # Отдельное от скрытия измерение: выдача — «что мне позволено видеть»
    # (решает админ, истина на сервере), скрытие — «что я убрал с глаз»
    # (решаю я, истина локальна). Предмет показывается, когда выдан И не
    # скрыт. Отзыв выдачи не трогает персональные скрытия: вернут доступ —
    # вернётся и прежний выбор. Подробно: docs/subject_grants.md.

    def ensure_grants_tables(self) -> None:
        """Гарантировать таблицы кэша выдач. Идемпотентно, результат кэширован."""
        if self._grants_ready:
            return
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS SubjectGrants ("
                "  user_login TEXT NOT NULL,"
                "  subject_id INTEGER NOT NULL,"
                "  PRIMARY KEY (user_login, subject_id))")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS GrantsMeta ("
                "  user_login TEXT NOT NULL PRIMARY KEY,"
                "  scope_version INTEGER NOT NULL DEFAULT 0,"
                "  default_access TEXT NOT NULL DEFAULT 'all')")
            conn.commit()
        self._grants_ready = True

    def save_grants(self, user_login: str, subject_ids, *,
                    scope_version: int = 0,
                    default_access: str = "all") -> None:
        """
        Заменить снимок выдач пользователя целиком (не дельта).

        Сервер отдаёт полный набор, и заменять целиком — единственный способ
        отработать ОТЗЫВ: дельта-обновление не знает, что запись пропала.
        Одна транзакция, чтобы витрина не увидела снимок наполовину стёртым.
        """
        if not user_login:
            raise ValueError("выдачи ключуются логином; гостю их не хранят")
        if default_access not in ("all", "none"):
            raise ValueError(f"default_access: 'all'|'none', не {default_access!r}")
        self.ensure_grants_tables()
        ids = sorted({int(s) for s in subject_ids})
        with self._connect() as conn:
            conn.execute("DELETE FROM SubjectGrants WHERE user_login = ?",
                         (user_login,))
            conn.executemany(
                "INSERT INTO SubjectGrants (user_login, subject_id) VALUES (?, ?)",
                [(user_login, sid) for sid in ids])
            conn.execute(
                "INSERT INTO GrantsMeta (user_login, scope_version, default_access) "
                "VALUES (?, ?, ?) ON CONFLICT(user_login) DO UPDATE SET "
                "  scope_version = excluded.scope_version, "
                "  default_access = excluded.default_access",
                (user_login, int(scope_version), default_access))
            conn.commit()

    def get_grants(self, user_login: str | None) -> Optional[GrantsSnapshot]:
        """
        Снимок выдач пользователя или None, если снимка нет.

        None — не «ничего не выдано», а «мы ещё не спрашивали сервер»: в этом
        случае витрину не ограничивают (иначе отказ сети выглядел бы как
        отзыв прав). У гостя снимка нет по определению.
        """
        if not user_login:
            return None
        self.ensure_grants_tables()
        with self._connect() as conn:
            meta = conn.execute(
                "SELECT scope_version, default_access FROM GrantsMeta "
                "WHERE user_login = ?", (user_login,)).fetchone()
            if meta is None:
                return None
            ids = [r[0] for r in conn.execute(
                "SELECT subject_id FROM SubjectGrants WHERE user_login = ?",
                (user_login,)).fetchall()]
        return GrantsSnapshot(frozenset(ids), meta[1], int(meta[0]))

    def clear_grants(self, user_login: str) -> None:
        """Забыть снимок (разлогин/смена сервера) — витрина снова без ограничений."""
        if not user_login:
            return
        self.ensure_grants_tables()
        with self._connect() as conn:
            conn.execute("DELETE FROM SubjectGrants WHERE user_login = ?",
                         (user_login,))
            conn.execute("DELETE FROM GrantsMeta WHERE user_login = ?",
                         (user_login,))
            conn.commit()

    # ---------- Subjects ----------

    def list_subjects(self, include_hidden: bool = False,
                      owned_by: str | None = None, *,
                      user_login: str | None = None,
                      apply_grants: bool = False) -> List[Subject]:
        """
        Предметы. include_hidden — показывать скрытые.

        user_login — ЧЬЮ витрину собираем: скрытия персональны, у каждого
        аккаунта свой набор (None — гостевой бакет). На состав предметов в
        БД это не влияет, только на то, какие из них помечены hidden и
        отфильтрованы.

        apply_grants — применить выданные админом права (см.
        docs/subject_grants.md). Ограничение действует, ТОЛЬКО если для
        user_login есть локальный снимок выдач и снимок ограничивает; нет
        снимка — витрина полная, потому что «сервер ещё не ответил» не должно
        выглядеть как «права отозвали». Кого ограничивать (преподавателя, но
        не гостя и не админа) решает вызывающий, а не этот слой.

        Оговорка о природе фильтра: для встроенных предметов это UI-уровень,
        а не защита — bootstrap.sync_database пересоздаёт их из
        CODE_GENERATORS на каждом старте, что бы сервер ни отдал, а локальную
        БД её владелец правит как хочет. Честно withhold можно только
        серверный контент — это делает скоуп pull'а.

        owned_by — ЕСЛИ задан, вернуть только встроенные (owner IS NULL) +
        принадлежащие этому пользователю. По умолчанию (None) фильтра нет.
        Тоже удобство витрины, не access-control.
        """
        self.ensure_visibility_tables()
        grants = self.get_grants(user_login) if apply_grants else None
        with self._connect() as conn:
            # Интроспекция колонок: БД могла пройти миграцию частично (старые
            # копии, тестовые схемы), owner_user_id может отсутствовать.
            cols = {r[1] for r in
                    conn.execute("PRAGMA table_info(Subjects)").fetchall()}
            has_owner = "owner_user_id" in cols

            # Скрытость берём из персонального бакета: LEFT JOIN, потому что
            # у большинства предметов записи в нём нет — это и есть «видно».
            select = ("SELECT s.id, s.subject_name, s.pra_subject, "
                      "COALESCE(v.hidden, 0)" +
                      (", s.owner_user_id" if has_owner else ""))
            params: list = [self._visibility_key(user_login)]
            where = []
            if not include_hidden:
                where.append("COALESCE(v.hidden, 0) = 0")
            if has_owner and owned_by is not None:
                where.append("(s.owner_user_id IS NULL OR s.owner_user_id = ?)")
                params.append(owned_by)
            if grants is not None and grants.restricts:
                allowed = sorted(grants.subject_ids)
                if allowed:
                    placeholders = ", ".join("?" for _ in allowed)
                    where.append(f"s.id IN ({placeholders})")
                    params.extend(allowed)
                else:
                    # Строгий режим без единой выдачи: не видно ничего.
                    # «s.id IN ()» — синтаксическая ошибка в SQLite.
                    where.append("0 = 1")
            sql = (f"{select} FROM Subjects s "
                   f"LEFT JOIN SubjectVisibility v "
                   f"  ON v.subject_id = s.id AND v.user_login = ?")
            if where:
                sql += " WHERE " + " AND ".join(where)
            rows = conn.execute(sql, params).fetchall()

            return [Subject(r[0], r[1], r[2], bool(r[3]),
                            r[4] if has_owner else None)
                    for r in rows]

    def get_subject_by_name(self, name: str) -> Optional[Subject]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, subject_name, pra_subject FROM Subjects "
                "WHERE subject_name = ?",
                (name,),
            ).fetchone()
        return Subject(*row) if row else None

    def delete_subject(self, subject_id: int) -> None:
        """
        Необратимо удалить предмет ВМЕСТЕ с его разделами. Каждое удаление
        уходит в outbox синка tombstone'ом (слушатель). Встроенные предметы
        пересоздаются сидами при следующем запуске (bootstrap.sync_database)
        — для них уместнее скрытие; предупреждение — забота UI.
        """
        self.ensure_visibility_tables()
        with self._connect() as conn:
            partition_ids = [r[0] for r in conn.execute(
                "SELECT id FROM Partitions WHERE subject_id = ?",
                (subject_id,)).fetchall()]
            conn.execute("DELETE FROM Partitions WHERE subject_id = ?",
                         (subject_id,))
            conn.execute("DELETE FROM Subjects WHERE id = ?", (subject_id,))
            # Персональные скрытия удалённого — за ним же (см. delete_partition).
            conn.execute("DELETE FROM SubjectVisibility WHERE subject_id = ?",
                         (subject_id,))
            if partition_ids:
                conn.executemany(
                    "DELETE FROM PartitionVisibility WHERE partition_id = ?",
                    [(pid,) for pid in partition_ids])
            conn.commit()
        if self.sync_listener is not None:
            for pid in partition_ids:
                self.sync_listener.partition_deleted(pid)
            self.sync_listener.subject_deleted(subject_id)

    # ---------- Partitions ----------

    def list_partitions_for_subject(
        self, subject_id: int, include_hidden: bool = False, *,
        user_login: str | None = None,
    ) -> List[Partition]:
        """Разделы предмета. Скрытость — персональная (см. list_subjects)."""
        self.ensure_visibility_tables()
        sql = ("SELECT p.id, p.subject_id, p.partition_name, p.constracted, "
               "       p.generation_parametrs, COALESCE(v.hidden, 0) "
               "FROM Partitions p "
               "LEFT JOIN PartitionVisibility v "
               "  ON v.partition_id = p.id AND v.user_login = ? "
               "WHERE p.subject_id = ?")
        if not include_hidden:
            sql += " AND COALESCE(v.hidden, 0) = 0"
        sql += " ORDER BY p.id"
        with self._connect() as conn:
            rows = conn.execute(
                sql, (self._visibility_key(user_login), subject_id)).fetchall()
        return [self._row_to_partition(r) for r in rows]

    def get_partition(self, partition_id: int) -> Optional[Partition]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, subject_id, partition_name, constracted, "
                "       generation_parametrs "
                "FROM Partitions WHERE id = ?",
                (partition_id,),
            ).fetchone()
        return self._row_to_partition(row) if row else None

    def view_kind_for(self, partition: Partition) -> str:
        """Какое представление подобрать разделу."""
        return _VIEW_KIND_BY_CONSTRACTED.get(partition.constracted, "single")

    @staticmethod
    def _row_to_partition(row) -> Partition:
        params: dict = {}
        raw = row[4]
        if raw:
            try:
                parsed = json.loads(raw)
                # generation_parametrs может быть и dict, и list — нормализуем в dict
                if isinstance(parsed, dict):
                    params = parsed
                else:
                    params = {"data": parsed}
            except json.JSONDecodeError:
                # Не JSON — храним как сырую строку под ключом 'raw'
                params = {"raw": raw}
        return Partition(
            id=row[0],
            subject_id=row[1],
            name=row[2],
            constracted=row[3],
            generation_params=params,
            # 6-я колонка (hidden) есть только у выборок с ней.
            hidden=bool(row[5]) if len(row) > 5 else False,
        )

    # ---------- Запись разделов ----------

    def ensure_subject(
        self, subject_id: int, name: str, parent_name: str | None = None
    ) -> int:
        """
        Гарантировать наличие предмета. Если subject_id уже занят, просто
        возвращаем его. Если в БД есть запись с таким же name — используем её id.
        Иначе — вставляем новую с подобранным id (или указанным, если свободен).
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM Subjects WHERE id = ?", (subject_id,)
            ).fetchone()
            if row:
                return row[0]
            # Предмета с таким id нет — может, есть с таким именем?
            row = conn.execute(
                "SELECT id FROM Subjects WHERE subject_name = ?", (name,)
            ).fetchone()
            if row:
                return row[0]
            # Создаём
            parent = parent_name if parent_name is not None else name
            try:
                conn.execute(
                    "INSERT INTO Subjects (id, subject_name, pra_subject) "
                    "VALUES (?, ?, ?)",
                    (subject_id, name, parent),
                )
                conn.commit()
                return subject_id
            except sqlite3.IntegrityError:
                # На случай гонки — выберем новый id
                cur = conn.execute(
                    "INSERT INTO Subjects (subject_name, pra_subject) VALUES (?, ?)",
                    (name, parent),
                )
                conn.commit()
                return cur.lastrowid

    def ensure_code_partition(
        self,
        partition_id: int,
        subject_id: int,
        name: str,
    ) -> None:
        """
        Гарантировать наличие записи раздела для code-only генератора
        (constracted=0, без generation_params). Если такой id занят другой
        записью — обновим имя/subject. Если запись отсутствует — вставим.

        Используется при синхронизации БД с кодом при старте.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, partition_name, subject_id, constracted "
                "FROM Partitions WHERE id = ?", (partition_id,)
            ).fetchone()
            if row is None:
                # Нет такой записи — попробуем вставить с указанным id.
                try:
                    conn.execute(
                        "INSERT INTO Partitions "
                        "(id, subject_id, partition_name, constracted, "
                        " generation_parametrs) VALUES (?, ?, ?, 0, '')",
                        (partition_id, subject_id, name),
                    )
                    conn.commit()
                except sqlite3.IntegrityError:
                    # Имя занято для другого id — пропускаем
                    pass
                return
            # Запись есть. Не трогаем её, если у неё другой constracted —
            # это группа/тест/конструктор с тем же id, не наше дело.
            # Только обновляем имя и subject_id для code-генератора (constracted=0).
            if row[3] == 0 and (row[1] != name or row[2] != subject_id):
                conn.execute(
                    "UPDATE Partitions SET partition_name = ?, subject_id = ? "
                    "WHERE id = ?", (name, subject_id, partition_id)
                )
                conn.commit()

    def ensure_graph_partition(
        self,
        partition_id: int,
        subject_id: int,
        name: str,
        graph: dict,
    ) -> None:
        """
        Гарантировать наличие раздела-графа (constracted=4), принадлежащего
        продукту. Идемпотентно; граф обновляется при расхождении.

        Отдельный метод, а не `upsert_partition`, по той же причине, что и
        у `ensure_code_partition`: id здесь ЗАДАН, а не выдан базой. Эти
        разделы поставляются вместе с приложением, и их номера должны быть
        одинаковы на всех установках — иначе домашнее задание, выданное на
        одной, укажет на другой раздел на второй.

        Граф ОБНОВЛЯЕТСЯ при расхождении, в отличие от кода-генератора: он
        и есть содержимое задания, и правка в поставке обязана доехать.
        Правки пользователя тут не теряются — свои задания он заводит
        своими разделами, а не переписывает поставочные.
        """
        raw = json.dumps(graph, ensure_ascii=False)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT partition_name, subject_id, constracted, "
                "       generation_parametrs "
                "FROM Partitions WHERE id = ?", (partition_id,)
            ).fetchone()
            if row is None:
                try:
                    conn.execute(
                        "INSERT INTO Partitions "
                        "(id, subject_id, partition_name, constracted, "
                        " generation_parametrs) VALUES (?, ?, ?, 4, ?)",
                        (partition_id, subject_id, name, raw),
                    )
                    conn.commit()
                except sqlite3.IntegrityError:
                    pass
                return
            if (row[0], row[1], row[2], row[3]) == (name, subject_id, 4, raw):
                return
            conn.execute(
                "UPDATE Partitions SET partition_name = ?, subject_id = ?, "
                "constracted = 4, generation_parametrs = ? WHERE id = ?",
                (name, subject_id, raw, partition_id),
            )
            conn.commit()

    def upsert_partition(
        self,
        subject_id: int,
        name: str,
        constracted: int,
        generation_params: dict | list | str,
        partition_id: int | None = None,
    ) -> int:
        """
        Создать новый раздел или обновить существующий. Возвращает id раздела.

        generation_params: dict/list сериализуется в JSON; str записывается как есть.

        partition_id — явный id для НОВОЙ записи (игнорируется, если раздел с
        такой парой subject_id+name уже существует — тогда правится он, его id
        не меняется). Без явного id новая запись получает следующий свободный
        rowid SQLite — этого достаточно для разделов, создаваемых через UI
        (constracted 1/2/3/4 editors), но НЕ годится для сидов, которые нужно
        держать вне динамических диапазонов id (см. ensure_code_partition:
        английские словари получают id = 1000 + номер файла в отсортированном
        списке ЗАНОВО при каждом запуске — свободный id, подобранный сегодня,
        завтра может достаться словарю, если пользователь добавит файлов).
        Такие сиды обязаны запрашивать id явно, вне зарезервированных диапазонов.
        """
        if isinstance(generation_params, (dict, list)):
            raw = json.dumps(generation_params, ensure_ascii=False)
        else:
            raw = str(generation_params)

        created = False
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT id FROM Partitions WHERE subject_id = ? AND partition_name = ?",
                (subject_id, name),
            )
            existing = cur.fetchone()
            if existing:
                pid = existing[0]
                conn.execute(
                    "UPDATE Partitions SET constracted = ?, generation_parametrs = ? "
                    "WHERE id = ?",
                    (constracted, raw, pid),
                )
            elif partition_id is not None:
                conn.execute(
                    "INSERT INTO Partitions "
                    "(id, subject_id, partition_name, constracted, generation_parametrs) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (partition_id, subject_id, name, constracted, raw),
                )
                pid = partition_id
            else:
                # Не автоинкремент: он рано или поздно дорастает до полосы,
                # которой распоряжается код, и начинает раздавать занятые
                # номера. Разделы «Группа»/«Группа_2» получили 1017 и 1018
                # именно так — вплотную к словарям английского.
                taken = [r[0] for r in conn.execute("SELECT id FROM Partitions")]
                pid = partition_ids.next_dynamic_id(taken)
                conn.execute(
                    "INSERT INTO Partitions "
                    "(id, subject_id, partition_name, constracted, "
                    " generation_parametrs) VALUES (?, ?, ?, ?, ?)",
                    (pid, subject_id, name, constracted, raw),
                )
                created = True
            conn.commit()
        self._notify_partition_changed(pid, subject_id, name, constracted, raw,
                                       created=created)
        return pid

    def delete_partition(self, partition_id: int) -> None:
        self.ensure_visibility_tables()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM Partitions WHERE id = ?", (partition_id,)
            )
            # Чужие персональные скрытия этого раздела больше не на что
            # ссылаться: без уборки они достались бы новому разделу, если
            # id переиспользуется (а он переиспользуется — см. upsert).
            conn.execute(
                "DELETE FROM PartitionVisibility WHERE partition_id = ?",
                (partition_id,))
            conn.commit()
        if self.sync_listener is not None:
            self.sync_listener.partition_deleted(partition_id)

    def renumber_partition(self, old_id: int, new_id: int) -> bool:
        """
        Перенести раздел на другой номер ВМЕСТЕ СО ВСЕМИ ССЫЛКАМИ на него.

        Нужно ровно один раз — при переходе со старой позиционной схемы
        номеров английских словарей (`1000 + место файла в списке`) на
        выведенную из имени. Оставить старые номера нельзя: они означают
        разные словари на сервере и на десктопе.

        Переносится не только строка раздела: на номер ссылаются личные
        скрытия (`PartitionVisibility`), состав групп и тестов (`task_id`
        внутри `generation_parametrs` чужих разделов) и журнал версий
        синхронизации. Перенос строки без ссылок оставил бы группу,
        указывающую в пустоту, — это хуже исходного дефекта, потому что
        сломалось бы то, что раньше работало.

        Возвращает False, если переносить нечего или новый номер занят.
        """
        if old_id == new_id:
            return False
        self.ensure_visibility_tables()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM Partitions WHERE id = ?", (old_id,)).fetchone()
            if row is None:
                return False
            if conn.execute("SELECT id FROM Partitions WHERE id = ?",
                            (new_id,)).fetchone() is not None:
                return False

            conn.execute("UPDATE Partitions SET id = ? WHERE id = ?",
                         (new_id, old_id))
            conn.execute(
                "UPDATE OR REPLACE PartitionVisibility SET partition_id = ? "
                "WHERE partition_id = ?", (new_id, old_id))

            # Состав групп и тестов: список позиций с полем task_id.
            for pid, raw in conn.execute(
                    "SELECT id, generation_parametrs FROM Partitions "
                    "WHERE constracted IN (2, 3)").fetchall():
                patched = _retarget_members(raw, old_id, new_id)
                if patched is not None:
                    conn.execute(
                        "UPDATE Partitions SET generation_parametrs = ? "
                        "WHERE id = ?", (patched, pid))

            # Журнал синхронизации живёт в этом же файле, но заводится
            # отдельным модулем: таблицы может не быть вовсе.
            try:
                conn.execute(
                    "UPDATE OR REPLACE sync_versions SET entity_id = ? "
                    "WHERE kind = 'partition' AND entity_id = ?",
                    (new_id, old_id))
            except sqlite3.OperationalError:
                pass
            conn.commit()
        return True

    def _notify_partition_changed(self, pid, subject_id, name, constracted, raw,
                                  *, created: bool) -> None:
        """Отдать правку раздела слушателю синхронизации (если подключён)."""
        if self.sync_listener is None:
            return
        self.sync_listener.partition_changed(pid, {
            "subject_id": subject_id, "partition_name": name,
            "constracted": constracted, "generation_parametrs": raw,
        }, created=created)

    # ---------- Карта constracted → kind редактора ----------

    EDITOR_KIND_BY_CONSTRACTED = {
        1: "fisic",
        2: "group",
        3: "test",
        4: "graph",
    }

    def editor_kind_for(self, partition: Partition) -> str | None:
        """
        Какой редактор использовать для редактирования раздела.
        None — раздел не редактируется через UI (например, одиночный генератор).
        """
        return self.EDITOR_KIND_BY_CONSTRACTED.get(partition.constracted)

    # ---------- Users (для авторизации) ----------

    def ensure_user_role_column(self) -> None:
        """
        Гарантировать колонку role в users. Идемпотентно (ALTER только если
        колонки ещё нет). Существующие аккаунты десктопа — авторы заданий,
        поэтому дефолт 'teacher'; гость роли не имеет (сессия ставит
        'student'). Ролью гейтятся ролевые действия (кнопка контура и т.п.).
        """
        with self._connect() as conn:
            cols = [r[1] for r in
                    conn.execute("PRAGMA table_info(users)").fetchall()]
            if "role" not in cols:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN "
                    "role TEXT NOT NULL DEFAULT 'teacher'"
                )
                conn.commit()

    # -- Пароли: PBKDF2 + прозрачная миграция унаследованных plain-text --
    #
    # Формат хранения: "pbkdf2$<итерации>$<соль hex>$<хэш hex>" — сам себя
    # описывает и не пересекается с plain-text (в паролях '$'-префикс
    # 'pbkdf2$' практически исключён). Унаследованные строки сравниваются
    # как есть и ПРИ ПЕРВОМ УСПЕШНОМ ВХОДЕ переписываются хэшем.

    _PBKDF2_ITERATIONS = 200_000

    @classmethod
    def _hash_password(cls, password: str, *, salt: Optional[bytes] = None,
                       iterations: Optional[int] = None) -> str:
        salt = salt if salt is not None else secrets.token_bytes(16)
        iters = iterations or cls._PBKDF2_ITERATIONS
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iters)
        return f"pbkdf2${iters}${salt.hex()}${digest.hex()}"

    @staticmethod
    def _is_hashed(stored: str) -> bool:
        return isinstance(stored, str) and stored.startswith("pbkdf2$")

    @classmethod
    def _verify_password(cls, password: str, stored: str) -> bool:
        """Проверить пароль против хранимого значения (хэш ИЛИ legacy plain)."""
        if not cls._is_hashed(stored):
            # compare_digest по байтам: str-вариант не принимает не-ASCII
            # (кириллические пароли — обычное дело).
            return secrets.compare_digest(
                str(stored).encode("utf-8"), password.encode("utf-8"))
        try:
            _, iters, salt_hex, hash_hex = stored.split("$", 3)
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"),
                bytes.fromhex(salt_hex), int(iters))
            return secrets.compare_digest(digest.hex(), hash_hex)
        except (ValueError, TypeError):
            return False

    def find_user(self, login: str, password: str) -> Optional[tuple]:
        """
        Вернуть (login, FIO, group, role) или None. Пароль проверяется в
        Python (_verify_password): и PBKDF2-хэш, и унаследованный plain-text;
        успешный вход со старым plain прозрачно мигрирует запись на хэш.
        Если колонки role ещё нет (ensure_user_role_column не отработал —
        например, вне обычного старта) — роль 'teacher' по умолчанию.
        """
        with self._connect() as conn:
            try:
                row = conn.execute(
                    "SELECT login, FIO, \"group\", role, password FROM users "
                    "WHERE login = ?", (login,),
                ).fetchone()
            except sqlite3.OperationalError:
                base = conn.execute(
                    "SELECT login, FIO, \"group\", password FROM users "
                    "WHERE login = ?", (login,),
                ).fetchone()
                row = None if base is None else (
                    base[0], base[1], base[2], "teacher", base[3])
            if row is None or not self._verify_password(password, row[4]):
                return None
            if not self._is_hashed(row[4]):
                # Прозрачная миграция plain → PBKDF2 при первом входе.
                conn.execute(
                    "UPDATE users SET password = ? WHERE login = ?",
                    (self._hash_password(password), login),
                )
                conn.commit()
            return row[:4]

    def set_password(self, login: str, old_password: str,
                     new_password: str) -> bool:
        """
        Сменить пароль: старый обязан пройти проверку (хэш или legacy plain).
        Новый всегда пишется PBKDF2-хэшем. Возвращает успех.
        """
        if not new_password:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT password FROM users WHERE login = ?", (login,),
            ).fetchone()
            if row is None or not self._verify_password(old_password, row[0]):
                return False
            conn.execute(
                "UPDATE users SET password = ? WHERE login = ?",
                (self._hash_password(new_password), login),
            )
            conn.commit()
        return True

    def create_user(self, login: str, password: str, *, fio: str = "",
                    group: str = "", role: str = "teacher") -> bool:
        """
        Создать пользователя (экран регистрации, волна E2). Пароль сразу
        хэшируется. False — логин занят или пустые логин/пароль.
        """
        if not login.strip() or not password:
            return False
        with self._connect() as conn:
            taken = conn.execute(
                "SELECT 1 FROM users WHERE login = ?", (login,),
            ).fetchone()
            if taken:
                return False
            try:
                conn.execute(
                    "INSERT INTO users (login, password, FIO, \"group\", role) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (login.strip(), self._hash_password(password),
                     fio, group, role),
                )
            except sqlite3.OperationalError:
                # БД без колонки role (ensure не отработал) — без роли.
                conn.execute(
                    "INSERT INTO users (login, password, FIO, \"group\") "
                    "VALUES (?, ?, ?, ?)",
                    (login.strip(), self._hash_password(password), fio, group),
                )
            conn.commit()
        return True

    # ---------- WordStats (межсессионная статистика по словам) ----------

    def ensure_word_stats_table(self) -> None:
        """
        Гарантировать наличие таблицы WordStats. Идемпотентно.
        Ключ — (user_id, term); счётчики и timestamp последнего показа.
        """
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS WordStats ("
                "  user_id TEXT NOT NULL,"
                "  term TEXT NOT NULL,"
                "  times_shown INTEGER NOT NULL DEFAULT 0,"
                "  times_correct INTEGER NOT NULL DEFAULT 0,"
                "  times_wrong INTEGER NOT NULL DEFAULT 0,"
                "  last_seen REAL NOT NULL DEFAULT 0,"
                "  PRIMARY KEY (user_id, term)"
                ")"
            )
            conn.commit()

    def fetch_word_stats(
        self, user_id: str, terms: List[str]
    ) -> dict:
        """
        Прочитать статистику по списку слов для пользователя.
        Возвращает dict[term, WordStat]. Отсутствующие в БД пропускаются.
        """
        # Локальный импорт чтобы избежать циклической зависимости с core.__init__.
        from .word_stats import WordStat

        if not terms:
            return {}
        # SQLite ограничивает количество параметров в одном запросе (по умолчанию
        # ~999). Разбиваем на чанки, чтобы корректно работать на больших словарях.
        out: dict[str, WordStat] = {}
        chunk_size = 500
        with self._connect() as conn:
            for i in range(0, len(terms), chunk_size):
                chunk = terms[i:i + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT term, times_shown, times_correct, times_wrong, "
                    f"       last_seen "
                    f"FROM WordStats "
                    f"WHERE user_id = ? AND term IN ({placeholders})",
                    (user_id, *chunk),
                ).fetchall()
                for r in rows:
                    out[r[0]] = WordStat(
                        term=r[0],
                        times_shown=r[1],
                        times_correct=r[2],
                        times_wrong=r[3],
                        last_seen=r[4],
                    )
        return out

    def upsert_word_stat(
        self, user_id: str, term: str, correct: bool, now: float
    ) -> None:
        """
        Зафиксировать один показ: +1 к times_shown, +1 к correct/wrong,
        last_seen = now. Использует ON CONFLICT для атомарного UPSERT.
        """
        delta_correct = 1 if correct else 0
        delta_wrong = 0 if correct else 1
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO WordStats "
                "(user_id, term, times_shown, times_correct, times_wrong, last_seen) "
                "VALUES (?, ?, 1, ?, ?, ?) "
                "ON CONFLICT(user_id, term) DO UPDATE SET "
                "  times_shown = times_shown + 1, "
                "  times_correct = times_correct + ?, "
                "  times_wrong = times_wrong + ?, "
                "  last_seen = ?",
                (user_id, term, delta_correct, delta_wrong, now,
                 delta_correct, delta_wrong, now),
            )
            conn.commit()

    def fetch_all_word_stats(self, user_id: str) -> list:
        """
        Все слова, по которым у пользователя есть статистика.
        Возвращает list[WordStat], отсортированный по last_seen DESC.
        """
        from .word_stats import WordStat

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT term, times_shown, times_correct, times_wrong, last_seen "
                "FROM WordStats WHERE user_id = ? "
                "ORDER BY last_seen DESC",
                (user_id,),
            ).fetchall()
        return [
            WordStat(
                term=r[0],
                times_shown=r[1],
                times_correct=r[2],
                times_wrong=r[3],
                last_seen=r[4],
            )
            for r in rows
        ]


def _retarget_members(raw, old_id: int, new_id: int) -> str | None:
    """
    Заменить номер раздела в составе группы/теста. None — менять нечего.

    Состав хранится списком позиций `{"task_id": …, "task_name": …}`.
    Разбор терпимый: чужой формат (или мусор) возвращает None и остаётся
    нетронутым — перенумерация не повод переписывать то, чего мы не поняли.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    changed = False
    for item in data:
        if isinstance(item, dict) and item.get("task_id") == old_id:
            item["task_id"] = new_id
            changed = True
    return json.dumps(data, ensure_ascii=False) if changed else None
