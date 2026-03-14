import os
import asyncio
import google.auth
from google import genai
from google.genai import types

os.environ["GOOGLE_CLOUD_PROJECT"] = "hackathons-461900"
os.environ["GOOGLE_CLOUD_LOCATION"] = "us-central1"

async def debug():
    print("Pre-initialization...")
    try:
        credentials, project = google.auth.default()
        print(f"Auth OK: Project={project}")
        
        client = genai.Client(vertexai=True, project=project, location="us-central1", credentials=credentials)
        print("Client instance created")
        
        # Test a simple non-live call first
        print("Testing simple non-live generate_content...")
        response = client.models.generate_content(model="gemini-1.5-flash", contents="Hi")
        print(f"Non-live Response: {response.text}")
        
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(debug())
