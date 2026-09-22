import uvicorn
from fastapi import FastAPI

from .routers import healthz_router

app = FastAPI()
server_instance = None

async def start_fastapi():
    global server_instance

    app.include_router(healthz_router)
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
    server_instance = uvicorn.Server(config)
    await server_instance.serve()


async def stop_fastapi():
    global server_instance
    if server_instance is not None:
        # Это штатный способ сказать Uvicorn: "Завершай работу корректно"
        server_instance.should_exit = True