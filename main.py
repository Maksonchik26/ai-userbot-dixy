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
    """Основная функция запуска userbot"""
    logger.info("Запуск userbot...")

    # 1. ИНИЦИАЛИЗИРУЕМ ВСЕ ПЕРЕМЕННЫЕ ЗАРАНЕЕ!
    # Это критически важно, чтобы избежать NameError в блоке finally
    fastapi_task = None
    join_task = None
    client_started = False

    try:
        await db.connect()
        logger.info("Подключено к базе данных")

        if settings.STRING_SESSION:
            logger.info("Используется STRING_SESSION из переменных окружения")

            # Сохраняем задачу в переменную
            fastapi_task = asyncio.create_task(start_fastapi())

            await client.start()
            client_started = True  # Помечаем, что клиент успешно запущен
        else:
            raise Exception("STRING_SESSION не найден или не валиден")

        logger.info("Userbot запущен и готов к работе!")

        chat_manager = ChatManager()
        join_task = asyncio.create_task(chat_manager.add_new_chats())

        # Запускаем слушатель Telegram в фоне
        asyncio.create_task(client.run_until_disconnected())

        # Ждем ТОЛЬКО сигнала завершения от ОС
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        await shutdown_task

    except asyncio.CancelledError:
        logger.info("Основной процесс был отменен")
    except Exception as e:
        logger.error(f"Ошибка во время выполнения main: {e}", exc_info=True)
        raise  # Пробрасываем ошибку дальше
    finally:
        logger.info("Начало корректного завершения работы...")

        # 2. ШТАТНАЯ остановка FastAPI
        if fastapi_task is not None and not fastapi_task.done():
            await stop_fastapi()
            try:
                await asyncio.wait_for(fastapi_task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("FastAPI не завершилась за 5 сек, применяем принудительную отмену")
                fastapi_task.cancel()
                try:
                    await fastapi_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass
            logger.info("FastAPI сервер остановлен")

        # 3. Останавливаем фоновую задачу добавления чатов
        if join_task is not None and not join_task.done():
            join_task.cancel()
            try:
                await join_task
            except asyncio.CancelledError:
                pass
            logger.info("Фоновая задача ChatManager остановлена")

        # 4. ПРАВИЛЬНАЯ остановка Telethon (вызовет disconnect)
        if client_started:
            if client.is_connected():
                await client.disconnect()
                logger.info("Клиент Telegram корректно отключен")

        # 5. Закрываем БД
        try:
            await db.close()
            logger.info("Соединение с БД закрыто")
        except Exception as e:
            logger.error(f"Ошибка при закрытии БД: {e}")

        logger.info("Userbot успешно и безопасно остановлен")


if __name__ == '__main__':
    # 1. Создаем цикл событий вручную
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # 2. Регистрируем обработчики сигналов
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_sigterm)

    try:
        # 3. Запускаем главную асинхронную функцию
        loop.run_until_complete(main())
    except Exception as e:
        logger.error(f"Критическая ошибка на уровне event loop: {e}", exc_info=True)
    finally:
        # 4. ФИНАЛЬНАЯ ЗАЧИСТКА всех оставшихся задач перед закрытием loop
        # Это гарантирует отсутствие предупреждений "Task was destroyed but it is pending!"
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()

        if pending:
            try:
                # Даем задачам 2 секунды на завершение после cancel
                loop.run_until_complete(asyncio.wait(pending, timeout=2.0))
            except Exception:
                pass

        loop.close()
        logger.info("Event loop полностью закрыт. Процесс завершен.")