from fastapi import APIRouter, HTTPException

from userbot import client


healthz_router = APIRouter(
    prefix='',
    tags=['healthz']
)


@healthz_router.get("/healtz")
async def health_check():
    """
    Проверяет жизнеспособность всего приложения:
    1. Жив ли Event Loop (мы ведь смогли выполнить этот код).
    2. Подключен ли бот к Telegram.
    """
    try:
        if not client.is_connected():
            raise HTTPException(status_code=503, detail="Telegram client disconnected")
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Health check failed: {str(e)}")

    return {"status": "ok", "telegram": "connected"}

