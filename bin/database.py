import sqlite3
import hashlib


# Класс для работы с базой данных
class Database:
    # Инициализация свойств
    def __init__(self):
        self.filename = "resources/db.sqlite"
        self.check_db()

    # Метод для выполнения запросов
    def execute_query(self, query, is_fetch_one=True):
        connection = sqlite3.connect(self.filename)
        cursor = connection.cursor()

        cursor.execute(query)

        if is_fetch_one:
            result = cursor.fetchone()
        else:
            result = cursor.fetchall()

        connection.commit()
        connection.close()
        return result

    # Функция генерации хэш строки
    def get_sha256_hash(self, string):
        return hashlib.sha256(string.encode()).hexdigest()

    # Проверка и создание базы данных и таблиц
    def check_db(self):
        # Проверка и создание таблицы должностей
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL UNIQUE
            )
            """
        )
        # Проверяем наличие записей в таблице должностей
        if not self.execute_query("SELECT * FROM positions"):
            query = f"INSERT INTO positions (title) VALUES ('Администратор'), ('Преподаватель'), ('Обучащийся')"
            self.execute_query(query)

        # Проверка и создание таблицы пользователей
        self.execute_query(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT
                                      UNIQUE
                                      NOT NULL,
                login         TEXT    NOT NULL
                                      UNIQUE,
                password TEXT    NOT NULL,
                name      TEXT    NOT NULL,
                avatar        BLOB,
                position_id   INTEGER NOT NULL,
                FOREIGN KEY (
                    position_id
                )
                REFERENCES positions (id) 
            );
            """
        )

        # Проверяем наличие пользователя администратор
        if not self.execute_query("SELECT * FROM users WHERE login = 'admin'"):
            # Сохраняем хэшированный пароль администратора
            hashed_password = self.get_sha256_hash("admin")  # Укажите пароль администратора
            # Создаем пользователя администратором
            query = f"""INSERT INTO users (email, password, nickname, position_id) 
            VALUES('admin@mail.ru', '{hashed_password}', 'Admin', 1)"""
            self.execute_query(query)
