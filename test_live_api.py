
import asyncio
import os
import google.auth
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

async def test_live_connect(model_id):
    print(f"\n--- Testing Live Connect with: {model_id} ---")
    PROJECT_ID = os.environ.get("PROJECT_ID", "hackathons-461900")
    LOCATION = os.environ.get("LOCATION", "us-central1")
    credentials, _ = google.auth.default()
    
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION, credentials=credentials)
    
    config = types.LiveConnectConfig(
        response_modalities=["TEXT"],
    )
    
    try:
        async with client.aio.live.connect(model=model_id, config=config) as session:
            print(f"SUCCESS: Connected to {model_id} in Live mode!")
            return True
    except Exception as e:
        print(f"FAILED: {model_id} - {e}")
        return False

async def main():
    models_to_test = [
        "gemini-2.0-flash-001",
        "gemini-2.0-flash",
        "gemini-1.5-flash-002",
        "gemini-2.0-flash-lite-001",
    ]
    
    for m in models_to_test:
        await test_live_connect(m)

if __name__ == "__main__":
    asyncio.run(main())
