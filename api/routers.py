from fastapi import APIRouter, HTTPException

from userbot import client


healthz_router = APIRouter(
    prefix='',
    tags=['healthz']
)


@healthz_router.get("/healthz")
async def health_check():
    try:
        # Пытаемся сделать реальный запрос.
        # Если сокет "зомби" или event loop завис, эта строка упадет с ошибкой или таймаутом.
        await client.get_me()
        return {"status": "ok", "telegram": "connected"}
    except Exception as e:
        # Любая ошибка здесь означает, что бот НЕ может работать
        raise HTTPException(status_code=503, detail=f"Telegram client unresponsive: {str(e)}")

