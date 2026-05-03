"""
Repository — слой доступа к БД.

Все запросы параметризованы (никаких f-строк в SQL).
Все обращения к Subjects/Partitions идут только через этот класс —
никакого `sqlite3.connect(db)` в других файлах.
"""

from __future__ import annotations
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, List, Optional


@dataclass(frozen=True)
class Subject:
    id: int
    name: str
    parent_name: str  # значение поля pra_subject


@dataclass(frozen=True)
class Partition:
    id: int
    subject_id: int
    name: str
    constracted: int          # 0=одиночный, 1=конструктор, 2=группа, 3=тест
    generation_params: dict   # распарсенный JSON или {}


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
}


class Repository:
    """Доступ к таблицам Subjects, Partitions, users."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path))
        try:
            yield conn
        finally:
            conn.close()

    # ---------- Subjects ----------

    def list_subjects(self) -> List[Subject]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, subject_name, pra_subject FROM Subjects"
            ).fetchall()
        return [Subject(r[0], r[1], r[2]) for r in rows]

    def get_subject_by_name(self, name: str) -> Optional[Subject]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, subject_name, pra_subject FROM Subjects "
                "WHERE subject_name = ?",
                (name,),
            ).fetchone()
        return Subject(*row) if row else None

    # ---------- Partitions ----------

    def list_partitions_for_subject(self, subject_id: int) -> List[Partition]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, subject_id, partition_name, constracted, "
                "       generation_parametrs "
                "FROM Partitions WHERE subject_id = ? ORDER BY id",
                (subject_id,),
            ).fetchall()
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

    def upsert_partition(
        self,
        subject_id: int,
        name: str,
        constracted: int,
        generation_params: dict | list | str,
    ) -> int:
        """
        Создать новый раздел или обновить существующий (по паре subject_id + name).
        Возвращает id раздела.

        generation_params: dict/list сериализуется в JSON; str записывается как есть.
        """
        if isinstance(generation_params, (dict, list)):
            raw = json.dumps(generation_params, ensure_ascii=False)
        else:
            raw = str(generation_params)

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
            else:
                cur = conn.execute(
                    "INSERT INTO Partitions "
                    "(subject_id, partition_name, constracted, generation_parametrs) "
                    "VALUES (?, ?, ?, ?)",
                    (subject_id, name, constracted, raw),
                )
                pid = cur.lastrowid
            conn.commit()
        return pid

    def delete_partition(self, partition_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM Partitions WHERE id = ?", (partition_id,)
            )
            conn.commit()

    # ---------- Карта constracted → kind редактора ----------

    EDITOR_KIND_BY_CONSTRACTED = {
        1: "fisic",
        2: "group",
        3: "test",
    }

    def editor_kind_for(self, partition: Partition) -> str | None:
        """
        Какой редактор использовать для редактирования раздела.
        None — раздел не редактируется через UI (например, одиночный генератор).
        """
        return self.EDITOR_KIND_BY_CONSTRACTED.get(partition.constracted)

    # ---------- Users (для авторизации) ----------

    def find_user(self, login: str, password: str) -> Optional[tuple]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT login, FIO, \"group\" FROM users "
                "WHERE login = ? AND password = ?",
                (login, password),
            ).fetchone()
