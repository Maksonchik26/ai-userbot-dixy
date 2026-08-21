import asyncio

from api.main import start_fastapi
from userbot import logger, db, client
from config import (
    SESSION_NAME,
    STRING_SESSION,
)


async def main():
    """Основная функция запуска userbot"""
    logger.info("Запуск userbot...")

    # Подключение к базе данных
    await db.connect()
    logger.info("Подключено к базе данных")

    # Подключение к Telegram
    import os
    if STRING_SESSION:
        logger.info("Используется STRING_SESSION из переменных окружения")

        asyncio.create_task(start_fastapi())
        await client.start()
    else:
        # Проверяем наличие файла сессии
        session_file = f"{SESSION_NAME}.session"
        if not os.path.exists(session_file):
            logger.warning(f"Файл сессии {session_file} не найден!")
            logger.warning("Userbot требует авторизацию. Запустите локально один раз для создания сессии.")
            logger.warning("Или используйте переменные окружения PHONE и PHONE_CODE для авторизации.")

            # Попытка авторизации через переменные окружения
            phone = os.getenv('PHONE')
            phone_code = os.getenv('PHONE_CODE')

            if phone and phone_code:
                logger.info(f"Попытка авторизации через переменные окружения для {phone}")
                try:
                    await client.start(phone=phone, code_callback=lambda: phone_code)
                    logger.info("Авторизация успешна через переменные окружения!")
                except Exception as e:
                    logger.error(f"Ошибка авторизации через переменные окружения: {e}")
                    logger.error("Загрузите файл сессии или авторизуйтесь локально")
                    raise
            else:
                logger.error("Файл сессии не найден и переменные окружения PHONE/PHONE_CODE не указаны")
                logger.error(
                    "Запустите userbot локально один раз для создания сессии, затем загрузите файл на сервер или укажите STRING_SESSION")
                raise FileNotFoundError(
                    f"Файл сессии {session_file} не найден. Загрузите его на сервер или авторизуйтесь локально.")
        else:
            asyncio.create_task(start_fastapi())
            await client.start()

    logger.info("Userbot запущен и готов к работе!")

    # Получение информации о себе
    me = await client.get_me()
    logger.info(f"Вошли как: {me.first_name} {me.last_name or ''} (@{me.username or 'без username'})")
    logger.info(f"ID аккаунта: {me.id}")

    # Статистика
    messages_count = await db.get_messages_count()
    logger.info(f"Всего сообщений в базе: {messages_count}")

    # Информация о командах
    logger.info("Доступные команды (в личных сообщениях):")
    logger.info("  /parse @username - парсинг истории чата")
    logger.info("  /stats - статистика")
    logger.info("  /help - справка")

    # Запуск в режиме ожидания
    await client.run_until_disconnected()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановка userbot...")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
    finally:
        asyncio.run(db.close())