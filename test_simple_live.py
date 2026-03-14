import os
import asyncio
import logging
import google.auth
from google import genai
from google.genai import types

# Set environment
os.environ["GOOGLE_CLOUD_PROJECT"] = "hackathons-461900"
os.environ["GOOGLE_CLOUD_LOCATION"] = "us-central1"

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION   = os.environ["GOOGLE_CLOUD_LOCATION"]
MODEL      = "gemini-2.0-flash"

async def test_live():
    print(f"Testing Gemini Live - Project: {PROJECT_ID}, Location: {LOCATION}, Model: {MODEL}")
    try:
        credentials, _ = google.auth.default()
        client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION, credentials=credentials)
        
        config = types.LiveConnectConfig(
            response_modalities=["TEXT"],
            system_instruction=types.Content(parts=[types.Part(text="You are a helpful assistant.")]),
        )
        
        print("Attempting to connect to Live API...")
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            print("Successfully CONNECTED to Live API!")
            await session.send(input="Hello, are you there?", end_of_turn=True)
            
            async for message in session:
                if message.text:
                    print(f"Gemini Response: {message.text}")
                    break
        print("Success!")
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_live())
