import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
PROJECT_ID = os.environ.get("PROJECT_ID", "hackathons-461900")
LOCATION = os.environ.get("LOCATION", "us-central1")

print(f"Connecting to Vertex AI (Project: {PROJECT_ID}, Location: {LOCATION})...")

client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

image_path = "test_image.jpg"
if not os.path.exists(image_path):
    print(f"Error: {image_path} not found.")
    exit(1)

with open(image_path, "rb") as f:
    img_data = f.read()

prompt = (
    "Analyze this product image. Return ONLY valid JSON with exact keys: "
    "'product_name', 'brand', 'estimated_price', 'inventory_status'."
)

try:
    print("Preparing API call...")
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            types.Part.from_bytes(data=img_data, mime_type="image/jpeg"),
            types.Part.from_text(text=prompt)
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        )
    )
    print("API call completed.")
    print("\nVertex AI Response:")
    print(response.text)
    
    # Verify parsing
    data = json.loads(response.text)
    print("\nSuccessfully parsed JSON:")
    print(json.dumps(data, indent=2))
    
except Exception as e:
    print(f"\nError: {e}")
