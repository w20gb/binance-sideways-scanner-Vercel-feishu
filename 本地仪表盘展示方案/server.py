"""
server.py

FastAPI + WebSocket local dashboard service.
"""

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from sideways_engine import run_full_scan

SCAN_INTERVAL = 300


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(data_refresh_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for conn in self.active_connections:
            try:
                await conn.send_text(message)
            except Exception:
                pass


manager = ConnectionManager()
latest_data = None


async def data_refresh_loop():
    global latest_data
    while True:
        try:
            print(f"\n{'=' * 50}")
            print(f"[{datetime.now().strftime('%H:%M:%S')}] running full scan...")

            async def progress(message):
                await manager.broadcast(json.dumps({"type": "PROGRESS", "msg": message}))

            results = await run_full_scan(prog_callback=progress)
            latest_data = results
            await manager.broadcast(json.dumps({"type": "UPDATE", "data": results}))
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] scan complete, pushed to {len(manager.active_connections)} client(s)"
            )
        except Exception as exc:
            import traceback

            print(f"scan failed: {exc}")
            traceback.print_exc()

        await asyncio.sleep(SCAN_INTERVAL)




def read_html_with_fallback(html_path: str) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            with open(html_path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue

    with open(html_path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


@app.get("/")
async def index():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    return HTMLResponse(content=read_html_with_fallback(html_path))


@app.websocket("/ws")

async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    if latest_data:
        await websocket.send_text(json.dumps({"type": "UPDATE", "data": latest_data}))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
