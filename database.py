import asyncpg
import json
from datetime import datetime
from typing import Optional, List, Dict

from asyncpg import UniqueViolationError

from config import DATABASE_PATH


class MessageDatabase:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.pool: asyncpg.Pool | None = None

    async def connect(self):
        """Создание пула соединений"""
        self.pool = await asyncpg.create_pool(
            self.db_path,
            min_size=5,    # Минимум соединений (держатся открытыми)
            max_size=20,   # Максимум соединений
            command_timeout=60
        )

        # Создаем таблицы через одно временное соединение из пула
        async with self.pool.acquire() as conn:
            await self.create_tables(conn)

    async def close(self):
        """Закрытие пула соединений"""
        if self.pool:
            await self.pool.close()

    async def create_tables(self, connection):
        """Создание таблиц в базе данных"""
        # Таблица для сообщений
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                message_id BIGINT NOT NULL,
                chat_id BIGINT NOT NULL,
                chat_title TEXT,
                chat_type TEXT,
                user_id BIGINT,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                message_text TEXT,
                date TIMESTAMP,
                is_reply INTEGER DEFAULT 0,
                reply_to_message_id BIGINT,
                has_media INTEGER DEFAULT 0,
                media_type TEXT,
                raw_data TEXT,
                parsed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                
                CONSTRAINT unique_chat_message UNIQUE (message_id, chat_id)
            )
        ''')

        # Таблица для чатов
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT UNIQUE NOT NULL,
                chat_title TEXT,
                chat_type TEXT,
                participants_count INTEGER,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_activity TIMESTAMP,
                metadata TEXT
            )
        ''')

        # Таблица для логирования вступлений в каналы
        await connection.execute('''
            CREATE TABLE IF NOT EXISTS chat_join_log (
                id SERIAL PRIMARY KEY,
                chat_entity TEXT NOT NULL,
                status TEXT NOT NULL,          -- 'success', 'flood_dead', 'permission_denied', 'linked_discussion'
                error_message TEXT,
                attempts_count INT DEFAULT 1,
                last_attempt_at TIMESTAMPTZ DEFAULT NOW(),
                created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(chat_entity)
)''')

        # Индексы для быстрого поиска
        await connection.execute('''
            CREATE INDEX IF NOT EXISTS idx_messages_chat_id 
            ON messages(chat_id)
        ''')
        await connection.execute('''
            CREATE INDEX IF NOT EXISTS idx_messages_date 
            ON messages(date)
        ''')
        await connection.execute('''
            CREATE INDEX IF NOT EXISTS idx_messages_user_id 
            ON messages(user_id)
        ''')

        # Миграция: добавляем parsed_at, если колонки нет
        await connection.execute('''
            ALTER TABLE messages ADD COLUMN IF NOT EXISTS parsed_at TIMESTAMP;
            ALTER TABLE messages DROP COLUMN IF EXISTS is_comment;
            ALTER TABLE messages DROP COLUMN IF EXISTS replies_count;
            ALTER TABLE messages DROP COLUMN IF EXISTS parent_message_id; 
            ALTER TABLE chats ADD COLUMN IF NOT EXISTS connecting_name TEXT DEFAULT NULL; 
        ''')

    async def save_message(self, message_data: Dict):
        """Сохранение сообщения в базу данных"""
        async with self.pool.acquire() as connection:
            try:
                row = await connection.fetchrow('''
                    INSERT INTO messages (
                        message_id, chat_id, chat_title, chat_type,
                        user_id, username, first_name, last_name,
                        message_text, date, is_reply, reply_to_message_id,
                        has_media, media_type, raw_data, parsed_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
                    RETURNING id
                ''',
                    message_data.get('message_id'),
                    message_data.get('chat_id'),
                    message_data.get('chat_title'),
                    message_data.get('chat_type'),
                    message_data.get('user_id'),
                    message_data.get('username'),
                    message_data.get('first_name'),
                    message_data.get('last_name'),
                    message_data.get('message_text'),
                    datetime.fromisoformat(message_data.get('date')).replace(tzinfo=None),
                    message_data.get('is_reply', 0),
                    message_data.get('reply_to_message_id'),
                    message_data.get('has_media', False),
                    message_data.get('media_type'),
                    json.dumps(message_data.get('raw_data', {})),
                    message_data.get('parsed_at'),
                )
                return row['id'] if row else None
            except UniqueViolationError as e:
                raise
            except Exception as e:
                print(f"Ошибка при сохранении сообщения: {e}")
                raise

    async def save_chat(self, chat_data: Dict):
        """Сохранение информации о чате"""
        async with self.pool.acquire() as connection:
            try:
                await connection.execute('''
                    INSERT INTO chats (
                        chat_id, chat_title, chat_type, participants_count,
                        last_activity, metadata, connecting_name
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7)
                ''',
                    chat_data.get('chat_id'),
                    chat_data.get('chat_title'),
                    chat_data.get('chat_type'),
                    chat_data.get('participants_count'),
                    datetime.now(),
                    json.dumps(chat_data.get('metadata', {})),
                    chat_data.get('connecting_name'),
                )
            except Exception as e:
                print(f"Ошибка при сохранении чата: {e}")

    async def get_messages_count(self, chat_id: Optional[int] = None) -> int:
        """Получение количества сохраненных сообщений"""
        async with self.pool.acquire() as connection:
            if chat_id:
                return await connection.fetchval(
                    'SELECT COUNT(*) FROM messages WHERE chat_id = $1', chat_id
                )
            else:
                return await connection.fetchval('SELECT COUNT(*) FROM messages')

    async def get_chats(self) -> List[Dict]:
        """Получение списка всех чатов"""
        async with self.pool.acquire() as connection:
            rows = await connection.fetch('SELECT * FROM chats ORDER BY last_activity DESC')
            return [dict(row) for row in rows]

    async def get_max_message_id_from_chat(self, chat_id: int) -> int:
        """Получение ID последнего сообщения из чата"""
        async with self.pool.acquire() as connection:
            last_message_id = await connection.fetchval(
                "SELECT MAX(message_id) FROM messages WHERE chat_id = $1 AND parent_message_id IS NULL",
                chat_id,
            )

            return last_message_id or 0

    async def get_recent_posts_with_replies(self, chat_id: int, since_date: datetime) -> List[Dict]:
        """
        Получает список постов за указанный период с их счетчиками комментариев.

        Args:
        chat_id: ID чата
        since_date: Дата, с которой нужно искать посты

    Returns:
        Список словарей: [{"message_id": 123, "replies_count": 5}, ...]
        """
        async with self.pool.acquire() as connection:
            query = """
                    SELECT message_id, replies_count FROM messages
                    WHERE chat_id = $1 AND date >= $2 AND parent_message_id IS NULL
                    """

            posts = await connection.fetch(query, chat_id, since_date)

            return [dict(row) for row in posts]


    async def update_message_replies_count(self, message_id: int, new_replies_count: int) -> None:
        """
            Обновляет количество комментариев под сообщением

            Args:
            message_id: ID сообщения-родителя (поста)
            new_replies_count: обновленное количество комментариев
        Returns:
            None
        """
        async with self.pool.acquire() as connection:
            query = "UPDATE messages SET replies_count = $1 WHERE message_id = $2"

            await connection.execute(query, new_replies_count, message_id)

    async def log_chat_attempt(self, chat_entity: str, status: str, error_message: str = None):
        """Запись результата попытки вступления в БД"""
        async with self.pool.acquire() as connection:
            await connection.execute('''
                                          INSERT INTO chat_join_log (chat_entity, status, error_message, attempts_count, last_attempt_at)
                                          VALUES ($1, $2, $3, 1, NOW()) ON CONFLICT (chat_entity) DO
                                          UPDATE SET
                                              status = EXCLUDED.status,
                                              error_message = EXCLUDED.error_message,
                                              attempts_count = chat_join_log.attempts_count + 1,
                                              last_attempt_at = NOW()
                                          ''', chat_entity, status, error_message)

    async def get_failed_chats(self) -> set:
        """Получение всех чатов, которые не удалось подключить (из БД)"""
        async with self.pool.acquire() as connection:
            rows = await connection.fetch('''
                                               SELECT chat_entity
                                               FROM chat_join_log
                                               WHERE status IN ('flood_dead', 'permission_denied', 'linked_discussion')
                                               ''')
            return {row['chat_entity'] for row in rows}
