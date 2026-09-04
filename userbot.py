import asyncio
import logging
from datetime import datetime, date, timedelta, timezone

from asyncpg import UniqueViolationError
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User, Chat, Channel
from telethon.errors import FloodWaitError, ChatAdminRequiredError, UserAlreadyParticipantError
from telethon.tl.functions.messages import ImportChatInviteRequest
from config import (
    API_ID,
    API_HASH,
    SESSION_NAME,
    STRING_SESSION,
    LOG_LEVEL,
    LOG_FILE,
    PROXY_HOST,
    PROXY_PORT,
    PROXY_USERNAME,
    PROXY_PASSWORD,
    PROXY_SET,
    PROXY_TYPE,
    CHAT_ENTITIES,
    DAYS_BACK,
)
from database import MessageDatabase

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация базы данных
db = MessageDatabase()

# Создаем и устанавливаем цикл событий ПЕРЕД инициализацией клиента
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# Инициализация клиента Telegram
session_arg = StringSession(STRING_SESSION) if STRING_SESSION else SESSION_NAME

# Инициализация прокси, если передан в env
proxy = None
if PROXY_SET:
    proxy = {
        'proxy_type': PROXY_TYPE,
        'addr': PROXY_HOST,
        'port': PROXY_PORT,
        'username': PROXY_USERNAME,
        'password': PROXY_PASSWORD,
        'rdns': True
    }

# Инициализация клиента
client = TelegramClient(session_arg, API_ID, API_HASH, proxy=proxy)

# Флаг для отслеживания активного парсинга
parsing_active = {}


def get_chat_info(chat):
    """Получение информации о чате"""
    if isinstance(chat, User):
        return {
            'chat_id': chat.id,
            'chat_title': f"{chat.first_name or ''} {chat.last_name or ''}".strip() or chat.username or f"User {chat.id}",
            'chat_type': 'private',
            'participants_count': 1
        }
    elif isinstance(chat, (Chat, Channel)):
        return {
            'chat_id': chat.id,
            'chat_title': getattr(chat, 'title', None) or f"Chat {chat.id}",
            'chat_type': 'channel' if isinstance(chat, Channel) else 'group',
            'participants_count': getattr(chat, 'participants_count', None)
        }
    return {
        'chat_id': chat.id if hasattr(chat, 'id') else 0,
        'chat_title': 'Unknown',
        'chat_type': 'unknown',
        'participants_count': None
    }


def get_user_info(sender):
    """Получение информации о пользователе"""
    if not sender:
        return {
            'user_id': None,
            'username': None,
            'first_name': None,
            'last_name': None
        }
    
    return {
        'user_id': sender.id,
        'username': getattr(sender, 'username', None),
        'first_name': getattr(sender, 'first_name', None),
        'last_name': getattr(sender, 'last_name', None)
    }


def get_media_info(message):
    """Получение информации о медиа в сообщении"""
    if not message.media:
        return {
            'has_media': False,
            'media_type': None
        }
    
    media_type = type(message.media).__name__
    return {
        'has_media': True,
        'media_type': media_type
    }


async def process_message(
    message,
    chat,
    parsed_at: datetime | None = None,
    sender=None,
    parent_message_id: int | None = None,
    replies_count: int | None = None,
):
    """Обработка и сохранение сообщения"""
    try:
        # Получение информации о чате
        chat_info = get_chat_info(chat)
        
        # Получение информации о пользователе
        if sender is None:
            try:
                sender = await message.get_sender()
            except Exception as e:
                logger.debug(f"Не удалось получить информацию об отправителе: {e}")
                sender = None
        user_info = get_user_info(sender)
        
        # Получение информации о медиа
        media_info = get_media_info(message)
        
        # Проверка, является ли сообщение ответом
        is_reply = message.reply_to is not None
        reply_to_message_id = None
        if is_reply and hasattr(message.reply_to, 'reply_to_msg_id'):
            reply_to_message_id = message.reply_to.reply_to_msg_id
        
        # Подготовка данных для сохранения
        message_data = {
            'message_id': message.id,
            'chat_id': chat_info['chat_id'],
            'chat_title': chat_info['chat_title'],
            'chat_type': chat_info['chat_type'],
            'user_id': user_info['user_id'],
            'username': user_info['username'],
            'first_name': user_info['first_name'],
            'last_name': user_info['last_name'],
            'message_text': message.text or message.raw_text or '',
            'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
            'is_reply': 1 if is_reply else 0,
            'reply_to_message_id': reply_to_message_id,
            'has_media': 1 if media_info['has_media'] else 0,
            'media_type': media_info['media_type'],
            'raw_data': {
                'message_id': message.id,
                'date': message.date.isoformat() if message.date else None,
                'views': getattr(message, 'views', None),
                'forwards': getattr(message, 'forwards', None),
                'replies': getattr(message.replies, 'replies', None) if hasattr(message, 'replies') and message.replies else None,
            },
            'parsed_at': parsed_at,
            'replies_count': replies_count,
            'parent_message_id': parent_message_id,
        }

        # Если сообщение является комментарием
        if parent_message_id:
            try:
            # Сохранение сообщения
                await db.save_message(message_data)
            # Исключение на случай, если коммент уже в БД. пробрасываем наружу для обработки
            except UniqueViolationError as e:
                logger.info(f"Сообщение/комментарий уже в БД: {e}")
                raise
        else:
            await db.save_message(message_data)


        # Сохранение информации о чате
        chat_data = {
            **chat_info,
            'metadata': {
                'access_hash': getattr(chat, 'access_hash', None),
                'username': getattr(chat, 'username', None)
            }
        }
        await db.save_chat(chat_data)
        
        return True

    except UniqueViolationError as e:
        raise
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)
        return False


chat_entities = [item.strip() for item in CHAT_ENTITIES.split(",") if item.strip()]


async def sync_comments_for_recent_posts(chat, chat_id: int, parsed_at: datetime, days_back: int = 1):
    """
    Проверяет наличие новых комментариев к уже сохраненным в БД постам.
    """
    # 1. Получаем из БД ID постов и их текущий счетчик комментариев за последние N дней
    since_date = datetime.now() - timedelta(days=days_back)
    recent_posts = await db.get_recent_posts_with_replies(chat_id, since_date)

    if not recent_posts:
        logger.debug("Нет недавних постов для проверки комментариев.")
        return

    # Извлекаем ID постов и их счетчики из БД
    post_ids = [p['message_id'] for p in recent_posts]
    reply_counts_from_db = {p['message_id']: p['replies_count'] if p['replies_count'] else 0 for p in recent_posts}

    # 2. БАТЧЕВЫЙ ЗАПРОС: Получаем актуальное состояние всех постов ОДНИМ запросом
    try:
        messages = await client.get_messages(chat, ids=post_ids)
    except Exception as e:
        logger.error(f"Ошибка при батчевом получении постов для проверки комментов: {e}")
        return

    # 3. Последовательно проверяем каждый пост и забираем новые комментарии
    posts_with_new_comments = 0
    total_new_comments = 0

    for msg in messages:

        if not msg or getattr(msg, 'service', False):
            continue

        # Получаем ТЕКУЩИЙ счетчик из Telegram API
        current_reply_count = msg.replies.replies if msg.replies else 0

        # Берем счетчик из БД для этого конкретного поста
        db_reply_count = reply_counts_from_db.get(msg.id, 0)

        # СИНХРОНИЗАЦИЯ: Сравниваем счетчики
        if current_reply_count > db_reply_count:
            # Забираем новые комментарии ПОСЛЕДОВАТЕЛЬНО
            new_comments_count = await fetch_new_comments(msg, chat, parsed_at)
            total_new_comments += new_comments_count

            try:
                await db.update_message_replies_count(msg.id, current_reply_count)
                logger.info(
                    f"   └─ Пост {msg.id}: обнаружены новые комментарии! (было {db_reply_count}, стало {current_reply_count})")
                posts_with_new_comments += 1
            except Exception as e:
                logger.error(f"Ошибка при обновлении счетчика комментариев под сообщением: {e}")

    logger.info(
        f"Проверка завершена. Постов с новыми комментами: {posts_with_new_comments}, добавлено комментариев: {total_new_comments}")


async def fetch_new_comments(message, chat, parsed_at: datetime) -> int:
    """
    Забирает только новые комментарии к конкретному посту.
    Возвращает количество добавленных комментариев.
    """
    # Берем комментарии только за последние 24 часа

    comments_added = 0

    # try:
    async for comment in client.iter_messages(
        chat,
        reply_to=message.id,
    ):
        comment_sender = await comment.get_sender()

        try:
            success = await process_message(
                comment,
                chat,
                parsed_at=parsed_at,
                sender=comment_sender,
                parent_message_id=message.id,
            )
        except UniqueViolationError as e:
            logger.info(f"Все комментарии под сообщением с id={message.id} обработаны")
            return comments_added

        if success:
            comments_added += 1

    # except Exception as e:
    #     logger.warning(f"Не удалось забрать комментарии к посту {message.id}: {e}")

    return comments_added


async def parse_some_chats():
    parsed_at = datetime.now()

    for chat_entity in chat_entities:
        await parse_chat_history(chat_entity, parsed_at)


async def parse_chat_history(chat_entity, parsed_at: datetime, limit=None):
    """
    Парсинг истории сообщений из чата
    
    Args:
        chat_entity: Объект чата (может быть username, хэш из ссылки-приглашения)
        limit: Максимальное количество сообщений для парсинга (None = все)
    """
    chat_id = None
    chat_title = "Unknown"
    try:
        # Обработка хэшей ссылок-приглашений
        if "@" not in chat_entity:
            try:
                chat = await client.get_entity(chat_entity)
            except ValueError as e:
                # TODO ПОДУМАТЬ КАК КОРРЕКТНЕЕ ОБРАБАТЫВАТЬ ЭТО
                invite_hash = chat_entity.rsplit("/", 1)[-1]
                result = await client(ImportChatInviteRequest(invite_hash))
                chat = result.chats[0]
                logger.info(f"Успешное присоединение к чату {chat.title} по ссылке-приглашению: {e}")
            except Exception as e:
                logger.error(f"Ошибка при подключении к группе по хэшу из ссылки-приглашения {chat_entity}: {e}")
        else:  # Если передано имя группы/чата @...
            try:
                # Получение информации о чате
                if isinstance(chat_entity, (int, str)):
                    chat = await client.get_entity(chat_entity)
                else:
                    chat = chat_entity
            except ValueError as e:
                logger.error(f"Группа не найдена: {chat_entity}. Ошибка: {e}")
                raise ValueError(f"Группа '{chat_entity}' не найдена. Проверьте username или ID, или убедитесь, что у вас есть доступ к группе.")
            except Exception as e:
                logger.error(f"Ошибка при получении информации о группе {chat_entity}: {e}")
                raise

        chat_info = get_chat_info(chat)
        chat_id = chat_info['chat_id']
        chat_title = chat_info['chat_title']

        # Проверка, не идет ли уже парсинг этого чата
        if chat_id in parsing_active and parsing_active[chat_id]:
            logger.warning(f"Парсинг чата {chat_title} уже выполняется")
            return False

        parsing_active[chat_id] = True
        logger.info(f"Начало парсинга истории чата: {chat_title} (ID: {chat_id})")

        total_parsed = 0
        errors_count = 0
        last_message_id: int = await db.get_max_message_id_from_chat(chat_id)

        try:
            # ============================
            # ФАЗА 1: Парсинг НОВЫХ постов
            # ============================
            async for message in client.iter_messages(
                chat,
                limit=limit,
                offset_date=date.today() - timedelta(days=7),
                offset_id=last_message_id,
                reverse=True  # Сначала старые сообщения
            ):
                try:
                    # Пропускаем служебные сообщения
                    if message.action:
                        continue

                    try:
                        sender = await message.get_sender()
                    except Exception as e:
                        logger.debug(f"Не удалось получить отправителя для сообщения {message.id}: {e}")
                        sender = None

                    success = await process_message(message, chat, parsed_at, sender)

                    if success:
                        total_parsed += 1
                        if total_parsed % 100 == 0:
                            logger.info(f"Обработано сообщений из {chat_title}: {total_parsed}")
                    else:
                        errors_count += 1

                    # Небольшая задержка, чтобы не получить FloodWait
                    if total_parsed % 50 == 0:
                        await asyncio.sleep(1)

                except FloodWaitError as e:
                    logger.warning(f"FloodWait: ожидание {e.seconds} секунд...")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    errors_count += 1
                    logger.error(f"Ошибка при обработке сообщения {message.id}: {e}")
                    continue

            # ========================================================
            # ФАЗА 2: Мониторинг комментариев к УЖЕ СОХРАНЕННЫМ постам
            # ========================================================
            logger.info(f"Фаза 2: Проверка новых комментариев к недавним постам в {chat_title}...")
            await sync_comments_for_recent_posts(chat, chat_id, parsed_at, days_back=DAYS_BACK)

            logger.info(f"Парсинг завершен: {chat_title}. Обработано новых постов: {total_parsed}")
            return True

        except ChatAdminRequiredError:
            logger.error(f"Нет доступа к истории чата {chat_title}. Убедитесь, что бот добавлен в группу и имеет права.")
            return False
        except Exception as e:
            logger.error(f"Ошибка при парсинге чата {chat_title}: {e}", exc_info=True)
            return False
        finally:
            parsing_active[chat_id] = False
        
    except Exception as e:
        logger.error(f"Критическая ошибка при парсинге чата: {e}", exc_info=True)
        if chat_id:
            parsing_active[chat_id] = False
        return False


@client.on(events.NewMessage(incoming=True))
async def handler(event):
    """Обработчик новых сообщений"""
    try:
        parsed_at = datetime.now()
        message = event.message
        message_text = message.text or ""
        chat_id = event.chat_id
        
        # Логируем ВСЕ входящие сообщения для отладки
        logger.info(f"📨 ВХОДЯЩЕЕ сообщение: '{message_text[:100]}' | chat_id: {chat_id} | is_private: {event.is_private}")
        
        # Пропускаем служебные сообщения
        if message.action:
            return
        
        # Пропускаем команды (они обрабатываются отдельными обработчиками)
        # НО НЕ БЛОКИРУЕМ их - пусть специальные обработчики сработают
        if message_text.startswith('/'):
            logger.info(f"⚡ Обнаружена команда в общем обработчике: '{message_text}' - пропускаем для специальных обработчиков")
            return
        
        chat = await event.get_chat()
        sender = await event.get_sender()
        await process_message(message, chat, parsed_at, sender)
        
        chat_info = get_chat_info(chat)
        user_info = get_user_info(sender)
        logger.debug(f"Сохранено сообщение: {chat_info['chat_title']} - {user_info['username'] or user_info['first_name'] or 'Unknown'}")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке сообщения: {e}", exc_info=True)


@client.on(events.MessageEdited)
async def handler_edited(event):
    """Обработчик отредактированных сообщений"""
    try:
        parsed_at = datetime.now()

        message = event.message
        chat = await event.get_chat()
        sender = await event.get_sender()
        
        await process_message(message, chat, parsed_at, sender)
        logger.debug(f"Отредактировано сообщение в чате {event.chat_id}")
    except Exception as e:
        logger.error(f"Ошибка при обработке отредактированного сообщения: {e}", exc_info=True)


# Обработчик команды /parse - используем более гибкий паттерн
@client.on(events.NewMessage(pattern=r'^/parse'))
async def parse_command_handler(event):
    """Обработчик команды /parse для парсинга истории чата"""
    try:
        # Логируем СРАЗУ при срабатывании обработчика
        message_text = event.message.text or ""
        chat_id = event.chat_id
        
        logger.info(f"🎯 ОБРАБОТЧИК /parse СРАБОТАЛ! Сообщение: '{message_text}' | chat_id: {chat_id}")
        
        # Получаем информацию о себе для проверки Saved Messages
        me = await client.get_me()
        is_saved_messages = (chat_id == me.id)
        
        logger.info(f"🔍 Детали: is_private: {event.is_private} | is_saved: {is_saved_messages} | my_id: {me.id}")
        
        # Команда работает в личных сообщениях (включая Saved Messages)
        # Saved Messages имеет chat_id равный вашему user_id
        if not event.is_private and not is_saved_messages:
            logger.warning(f"⚠️ Сообщение не из личного чата. Chat ID: {chat_id}, My ID: {me.id}")
            return
        
        # Получаем аргументы команды - парсим вручную из текста сообщения
        # Формат: /parse @username или /parse @username limit=1000
        parts = message_text.split(None, 1)  # Разделяем по пробелам, максимум 2 части
        if len(parts) < 2 and message_text != "/parse_all":
            await event.respond(
                "❌ Неверный формат команды. Используйте: `/parse @username`, или `/parse @username limit=1000`, или `/parse_all`")
            return

        args = parts[1].strip()  # Все что после /parse
        
        # Парсим аргументы: /parse @username или /parse @username limit=1000
        args_parts = args.split()
        chat_identifier = args_parts[0]
        limit = None
        
        logger.info(f"📋 Парсинг аргументов: chat_identifier='{chat_identifier}', остальное='{args_parts[1:] if len(args_parts) > 1 else []}'")
        
        # Поиск параметра limit
        for part in args_parts[1:]:
            if part.startswith('limit='):
                try:
                    limit = int(part.split('=')[1])
                    logger.info(f"📊 Установлен лимит: {limit}")
                except ValueError:
                    logger.warning(f"⚠️ Неверный формат limit: {part}")
                    pass
        
        await event.respond(f"🔄 Начинаю парсинг чата: {chat_identifier}\n⏳ Это может занять некоторое время...")
        
        # Запускаем парсинг в фоне
        try:
            success = await parse_chat_history(chat_identifier, limit=limit)
            
            if success:
                count = await db.get_messages_count()  # Получаем общее количество
                await event.respond(
                    f"✅ Парсинг завершен!\n"
                    f"📊 Всего сообщений в базе: {count}\n"
                    f"💾 Используйте /stats для детальной статистики"
                )
            else:
                await event.respond(
                    "❌ Ошибка при парсинге.\n"
                    "Возможные причины:\n"
                    "• Группа приватная и вы не участник\n"
                    "• Неправильный username или ID\n"
                    "• Нет доступа к истории сообщений\n\n"
                    "Проверьте логи для подробностей."
                )
        except ValueError as e:
            # Ошибка при получении entity (группа не найдена)
            await event.respond(
                f"❌ Группа не найдена: {chat_identifier}\n\n"
                "Проверьте:\n"
                "• Правильность username (например: @groupname)\n"
                "• Правильность ID группы\n"
                "• Доступ к группе (для приватных групп нужно быть участником)"
            )
        except Exception as e:
            error_msg = str(e)
            if "username" in error_msg.lower() or "not found" in error_msg.lower():
                await event.respond(
                    f"❌ Группа не найдена или нет доступа.\n"
                    f"Ошибка: {error_msg}\n\n"
                    "Для приватных групп нужно быть участником."
                )
            else:
                await event.respond(f"❌ Ошибка: {error_msg}\nПроверьте логи для подробностей.")
            
    except Exception as e:
        logger.error(f"Ошибка в команде /parse: {e}", exc_info=True)
        await event.respond(f"❌ Критическая ошибка: {str(e)}")


@client.on(events.NewMessage(pattern=r'^/stats$', incoming=True, from_users=None))
async def stats_command_handler(event):
    """Обработчик команды /stats для получения статистики"""
    try:
        if not event.is_private:
            return
        
        total_messages = await db.get_messages_count()
        chats = await db.get_chats()
        
        stats_text = f"📊 **Статистика парсера**\n\n"
        stats_text += f"Всего сообщений: {total_messages}\n"
        stats_text += f"Всего чатов: {len(chats)}\n\n"
        stats_text += "**Топ чатов:**\n"
        
        # Получаем статистику по чатам
        for chat in chats[:10]:
            chat_messages = await db.get_messages_count(chat['chat_id'])
            stats_text += f"• {chat['chat_title']}: {chat_messages} сообщений\n"
        
        await event.respond(stats_text)
        
    except Exception as e:
        logger.error(f"Ошибка в команде /stats: {e}", exc_info=True)
        await event.respond(f"❌ Ошибка: {str(e)}")


@client.on(events.NewMessage(pattern=r'^/help$'))
async def help_command_handler(event):
    """Обработчик команды /help"""
    try:
        chat_id = event.chat_id
        me = await client.get_me()
        is_saved_messages = (chat_id == me.id)
        
        logger.info(f"🔍 ОБРАБОТЧИК /help: chat_id: {chat_id} | is_private: {event.is_private} | is_saved: {is_saved_messages}")
        
        if not event.is_private and not is_saved_messages:
            return
        
        help_text = """
🤖 **Команды userbot:**

`/parse @username` - Начать парсинг истории чата
`/parse @username limit=1000` - Парсинг с ограничением количества
`/stats` - Показать статистику
`/help` - Показать эту справку

**Примеры:**
`/parse @mygroup`
`/parse @support_group limit=5000`

**Примечание:** Бот должен быть добавлен в группу для парсинга.
        """
        
        await event.respond(help_text)
        
    except Exception as e:
        logger.error(f"Ошибка в команде /help: {e}", exc_info=True)
