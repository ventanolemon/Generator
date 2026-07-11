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
                cur = conn.execute(
                    "INSERT INTO Partitions "
                    "(subject_id, partition_name, constracted, generation_parametrs) "
                    "VALUES (?, ?, ?, ?)",
                    (subject_id, name, constracted, raw),
                )
                pid = cur.lastrowid
                created = True
            conn.commit()
        self._notify_partition_changed(pid, subject_id, name, constracted, raw,
                                       created=created)
        return pid

    def delete_partition(self, partition_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM Partitions WHERE id = ?", (partition_id,)
            )
            conn.commit()
        if self.sync_listener is not None:
            self.sync_listener.partition_deleted(partition_id)

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
