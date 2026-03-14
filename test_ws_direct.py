import asyncio
import websockets
import json

async def test_ws():
    uri = "ws://localhost:8001/ws"
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to WebSocket")
            # Send config
            await websocket.send(json.dumps({
                "type": "config",
                "store": "Test Store",
                "response_mode": "text"
            }))
            print("Config sent")
            
            # Wait for status
            resp = await websocket.recv()
            print(f"Received: {resp}")
            
            # Send hi
            await websocket.send(json.dumps({
                "type": "text_message",
                "text": "Hello Gemini"
            }))
            print("Message sent")
            
            # Wait for response
            while True:
                resp = await asyncio.wait_for(websocket.recv(), timeout=10)
                print(f"Received: {resp}")
                
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_ws())
