import asyncpg
import json
from datetime import datetime
from typing import Optional, List, Dict
from config import DATABASE_PATH


class MessageDatabase:
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = db_path
        self.connection: Optional[asyncpg.Connection] = None

    async def connect(self):
        """Подключение к базе данных"""
        self.connection = await asyncpg.connect(self.db_path)
        await self.create_tables()

    async def close(self):
        """Закрытие соединения с базой данных"""
        if self.connection:
            await self.connection.close()

    async def create_tables(self):
        """Создание таблиц в базе данных"""
        # Таблица для сообщений
        await self.connection.execute('''
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
        await self.connection.execute('''
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

        # Индексы для быстрого поиска
        await self.connection.execute('''
            CREATE INDEX IF NOT EXISTS idx_messages_chat_id 
            ON messages(chat_id)
        ''')
        await self.connection.execute('''
            CREATE INDEX IF NOT EXISTS idx_messages_date 
            ON messages(date)
        ''')
        await self.connection.execute('''
            CREATE INDEX IF NOT EXISTS idx_messages_user_id 
            ON messages(user_id)
        ''')

        # Миграция: добавляем parsed_at, если колонки нет
        await self.connection.execute('''
          ALTER TABLE messages
          ADD COLUMN IF NOT EXISTS parsed_at TIMESTAMP
        ''')

    async def save_message(self, message_data: Dict):
        """Сохранение сообщения в базу данных"""
        try:
            row = await self.connection.fetchrow('''
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
        except Exception as e:
            print(f"Ошибка при сохранении сообщения: {e}")
            return None

    async def save_chat(self, chat_data: Dict):
        """Сохранение информации о чате"""
        try:
            await self.connection.execute('''
                INSERT INTO chats (
                    chat_id, chat_title, chat_type, participants_count,
                    last_activity, metadata
                ) VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (chat_id) DO UPDATE SET
                    chat_title = EXCLUDED.chat_title,
                    chat_type = EXCLUDED.chat_type,
                    participants_count = EXCLUDED.participants_count,
                    last_activity = EXCLUDED.last_activity,
                    metadata = EXCLUDED.metadata
            ''',
                chat_data.get('chat_id'),
                chat_data.get('chat_title'),
                chat_data.get('chat_type'),
                chat_data.get('participants_count'),
                datetime.now(),
                json.dumps(chat_data.get('metadata', {}))
            )
        except Exception as e:
            print(f"Ошибка при сохранении чата: {e}")

    async def get_messages_count(self, chat_id: Optional[int] = None) -> int:
        """Получение количества сохраненных сообщений"""
        if chat_id:
            return await self.connection.fetchval(
                'SELECT COUNT(*) FROM messages WHERE chat_id = $1', chat_id
            )
        else:
            return await self.connection.fetchval('SELECT COUNT(*) FROM messages')

    async def get_chats(self) -> List[Dict]:
        """Получение списка всех чатов"""
        rows = await self.connection.fetch('SELECT * FROM chats ORDER BY last_activity DESC')
        return [dict(row) for row in rows]

    async def get_max_message_id_from_chat(self, chat_id: int) -> int:
        """Получение ID последнего сообщения из чата"""
        last_message_id = await self.connection.fetchval("SELECT MAX(message_id) FROM messages WHERE chat_id = $1", chat_id)

        return last_message_id or 0
