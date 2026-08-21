from fastapi import APIRouter, Response, Request
from fastapi.responses import JSONResponse

from userbot import parse_some_chats

parsing_router = APIRouter(
    prefix='',
    tags=['parsing']
)


@parsing_router.get("/parse_all")
async def parse_all_new_messages():
    await parse_some_chats()

    return JSONResponse({"message": "Parsing in progress",}, status_code=200)


# @parsing_router.get("/health")
# async def healthcheck():
#     try:
#         me = await tg_bot.get_me()  # Telegram возвращает данные о боте
#         return JSONResponse({"status": "ok", "bot": me.username})
#     except Exception as e:
#         return JSONResponse({"status": "error", "detail": str(e)}, status_code=503)