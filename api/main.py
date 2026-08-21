import uvicorn
from fastapi import FastAPI

from .routers import parsing_router


async def start_fastapi():
    app = FastAPI()

    app.include_router(parsing_router)
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()