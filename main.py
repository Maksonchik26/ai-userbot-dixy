import asyncio
import signal

import httpx

from api.main import start_fastapi, stop_fastapi
from userbot import logger, db, client, ChatManager
from config import settings


shutdown_event = asyncio.Event()

def handle_sigterm():
    logger.info("Получен сигнал SIGTERM/SIGINT. Начинаем graceful shutdown...")
    shutdown_event.set()


async def simple_scheduler(minutes: int):
    await asyncio.sleep(60)
    while True:
        async with httpx.AsyncClient() as client:
            url = "http://0.0.0.0:8000/parse_all"
            response = await client.get(url)
            logger.info(f"Ответ от {url}: статус {response.status_code}")

        await asyncio.sleep(minutes * 60)


async def main():
    logger.info("🚀 Запуск userbot...")

    # 1. Инициализируем переменные
    fastapi_task = None
    join_task = None
    client_started = False

    try:
        # 2. БАЗА И API (Живут всегда, пока контейнер жив)
        await db.connect()
        logger.info("✅ Подключено к базе данных")

        if not settings.STRING_SESSION:
            raise Exception("STRING_SESSION не найден или не валиден")

        # ЗАПУСКАЕМ FASTAPI ПЕРВЫМ! Он будет жить и отвечать на healthcheck,
        # даже если Telegram будет подключаться 10 минут.
        fastapi_task = asyncio.create_task(start_fastapi())
        logger.info("✅ FastAPI запущен и готов отвечать на healthcheck")

        # 3. ИЗОЛИРОВАННЫЙ ЦИКЛ ПОДКЛЮЧЕНИЯ TELEGRAM
        # Если здесь ошибка, мы НЕ выходим из main() и НЕ вызываем finally.
        # Мы просто ждем и пробуем снова.
        while not shutdown_event.is_set():
            try:
                await client.start()
                client_started = True
                logger.info("✅ Клиент Telegram успешно подключен!")
                break  # Успех! Выходим из цикла попыток и идем дальше
            except Exception as e:
                logger.warning(f"⚠️ Сбой подключения Telegram: {e}. Повтор через 10 сек...")
                await asyncio.sleep(10)

        # Если во время бесконечных попыток пришел реальный сигнал на выключение
        if shutdown_event.is_set():
            logger.info("Запуск прерван сигналом остановки.")
            return

        # 4. ЗАПУСК ФОНОВЫХ ЗАДАЧ БОТА (только после успешного подключения)
        chat_manager = ChatManager()
        join_task = asyncio.create_task(chat_manager.add_new_chats())

        # Слушатель событий в фоне
        asyncio.create_task(client.run_until_disconnected())

        logger.info("🎉 Userbot полностью запущен и работает!")

        # 5. ЖДЕМ РЕАЛЬНОГО СИГНАЛА НА ВЫКЛЮЧЕНИЕ (SIGTERM от Docker)
        # Эта строка будет висеть вечно, пока Docker не скажет "стоп"
        await shutdown_event.wait()

    except asyncio.CancelledError:
        logger.info("Основной процесс был отменен")

    # МЫ УБРАЛИ except Exception: raise!
    # Теперь ошибки подключения Telegram не убивают весь процесс.

    finally:
        # 6. ГРЕЙСФУЛ ШАТДАУН
        # Сработает ТОЛЬКО когда сработает shutdown_event.wait() выше
        logger.info("🧹 Начало корректного завершения работы...")

        # А. Останавливаем FastAPI
        if fastapi_task is not None and not fastapi_task.done():
            await stop_fastapi()
            try:
                await asyncio.wait_for(fastapi_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                fastapi_task.cancel()
            logger.info("FastAPI сервер остановлен")

        # Б. Останавливаем задачи чатов
        if join_task is not None and not join_task.done():
            join_task.cancel()
            try:
                await join_task
            except asyncio.CancelledError:
                pass
            logger.info("Фоновая задача ChatManager остановлена")

        # В. Отключаем Telegram
        if client_started and client.is_connected():
            await client.disconnect()
            logger.info("Клиент Telegram корректно отключен")

        # Г. Закрываем БД
        try:
            await db.close()
            logger.info("Соединение с БД закрыто")
        except Exception as e:
            logger.error(f"Ошибка при закрытии БД: {e}")

        logger.info("✨ Userbot успешно и безопасно остановлен")


if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_sigterm)

    try:
        loop.run_until_complete(main())
    except Exception as e:
        logger.error(f"Критическая ошибка на уровне event loop: {e}", exc_info=True)
    finally:
        # Чистка "призрачных" задач
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            try:
                loop.run_until_complete(asyncio.wait(pending, timeout=2.0))
            except Exception:
                pass
        loop.close()
