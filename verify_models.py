
import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.environ.get("PROJECT_ID", "hackathons-461900")
LOCATION = os.environ.get("LOCATION", "us-central1")

client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

print(f"Testing connectivity to project {PROJECT_ID} in {LOCATION}...")

try:
    # Try to list models or just connect
    print("Available Gemini models:")
    for m in client.models.list():
        if "gemini" in m.name.lower():
            print(f" - {m.name}")
except Exception as e:
    print(f"Error listing models: {e}")

# Try to connect to gemini-2.0-flash
try:
    print("\nAttempting to connect to gemini-2.0-flash...")
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents="Hello"
    )
    print("Connect success!")
except Exception as e:
    print(f"Gemini 2.0 Flash failed: {e}")

# Try to connect to gemini-2.5-flash
try:
    print("\nAttempting to connect to gemini-2.5-flash...")
    # We can't easily test live.connect without a full async setup, 
    # but we can try a simple generate_content
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents="Hello"
    )
    print("Connect success!")
except Exception as e:
    print(f"Gemini 2.5 Flash failed: {e}")

try:
    print("\nAttempting to connect to gemini-2.0-flash-exp...")
    response = client.models.generate_content(
        model="gemini-2.0-flash-exp",
        contents="Hello"
    )
    print("Connect success!")
except Exception as e:
    print(f"Gemini 2.0 Flash Exp failed: {e}")
