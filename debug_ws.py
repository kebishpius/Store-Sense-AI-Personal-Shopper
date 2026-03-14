import asyncio
import websockets
import json

async def test_ws():
    uri = "ws://localhost:8001/ws"
    print(f"Connecting to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected!")
            # Send config
            config = {
                "type": "config",
                "store": "Test Store",
                "response_mode": "text"
            }
            await websocket.send(json.dumps(config))
            print(f"Sent config: {config}")

            # Wait for status
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                print(f"Received: {response}")
                
                # Try to send a message
                msg = {
                    "type": "text_message",
                    "text": "Hello, can you see me?"
                }
                await websocket.send(json.dumps(msg))
                print(f"Sent message: {msg}")
                
                # Wait for AI response
                while True:
                    response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    print(f"Ai Response: {response}")
                    
            except asyncio.TimeoutError:
                print("Timeout waiting for response.")
                
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    asyncio.run(test_ws())
