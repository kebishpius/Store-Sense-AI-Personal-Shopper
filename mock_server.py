from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    print("[ws] Connected")
    try:
        await ws.send_json({"type": "status", "message": "connected"})
        await ws.send_json({"type": "text", "text": "MOCK SERVER ACTIVE"})
        while True:
            data = await ws.receive_text()
            print(f"[ws] Got: {len(data)} chars")
            await ws.send_json({"type": "text", "text": f"Echo: {len(data)} chars received"})
    except Exception as e:
        print(f"[ws] Error: {e}")
    finally:
        print("[ws] Disconnected")

@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
