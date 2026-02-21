import asyncio
import cv2
import base64
import sys
from google import genai
from google.genai import types

# 1. Setup
PROJECT_ID = "hackathons-461900"
LOCATION = "us-central1"
client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

# Using the verified working model for Live API in this project
MODEL_ID = "gemini-live-2.5-flash-native-audio"

async def test_vision_audio():
    # Capture one frame
    print("--- Capturing test frame ---")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open camera.")
        return

    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        print("Failed to grab frame")
        return
    
    # Encode to JPEG (Base64 is for the payload)
    _, buffer = cv2.imencode('.jpg', frame)
    image_bytes = buffer.tobytes()

    print(f"--- Connecting to Gemini Live ({MODEL_ID}) ---")
    
    # Live session configuration
    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"]
    )

    try:
        async with client.aio.live.connect(model=MODEL_ID, config=live_config) as session:
            print("--- Sending Text + Image ---")
            
            # 1. Send the image as Realtime Input (media stream)
            await session.send_realtime_input(
                media=types.Blob(data=image_bytes, mime_type="image/jpeg")
            )
            
            # 2. Send the text prompt as a turn (Client Content)
            # This triggers the model to respond to the previous media + this text
            await session.send_client_content(
                turns=[
                    types.Content(
                        parts=[types.Part(text="Look at this image. What product is this? (Answer via audio)")]
                    )
                ],
                turn_complete=True
            )

            print("--- Waiting for Response ---")
            async for response in session.receive():
                # Check for audio data (success marker)
                if response.data:
                    print("Success! Received audio data from Gemini.")
                    break
                
                # Also check for text (sometimes model replies with text + audio)
                if response.text:
                    print(f"Success! Model says: {response.text}")
                    break
    except Exception as e:
        print(f"Error during test: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(test_vision_audio())
    except KeyboardInterrupt:
        pass
