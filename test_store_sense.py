"""
test_store_sense.py — Store-Sense Integration Smoke Test
========================================================
Connects to the Gemini Live API, sends a single camera frame,
and verifies the model responds with audio or text.
"""

import asyncio
import cv2
import sys
from google import genai
from google.genai import types

# ─────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────
PROJECT_ID = "hackathons-461900"
LOCATION   = "us-central1"
MODEL_ID   = "gemini-live-2.5-flash-native-audio"

client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)


async def test_vision_response():
    """Send a camera frame + text prompt and verify the model responds."""
    print("--- Capturing test frame ---")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open camera.")
        return False

    ret, frame = cap.read()
    cap.release()

    if not ret:
        print("Failed to grab frame")
        return False

    # Encode to JPEG
    _, buffer = cv2.imencode('.jpg', frame)
    image_bytes = buffer.tobytes()

    print(f"--- Connecting to Gemini Live ({MODEL_ID}) ---")

    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text=(
                "You are Store-Sense, a live shopping assistant. "
                "Describe any products you see in the image and their prices. "
                "Keep the response very short."
            ))]
        ),
        tools=[
            types.Tool(google_search=types.GoogleSearch()),
        ],
    )

    success = False
    try:
        async with client.aio.live.connect(model=MODEL_ID, config=live_config) as session:
            print("--- Sending image ---")
            await session.send_realtime_input(
                media=types.Blob(data=image_bytes, mime_type="image/jpeg")
            )

            print("--- Sending text prompt ---")
            await session.send_client_content(
                turns=[
                    types.Content(
                        parts=[types.Part(text=(
                            "What product is this? What's the price? "
                            "If you can see a nutrition label, give it a quick health grade."
                        ))]
                    )
                ],
                turn_complete=True
            )

            print("--- Waiting for response ---")
            async for response in session.receive():
                if response.data:
                    print(f"[PASS] Received audio data ({len(response.data)} bytes)")
                    success = True
                    break
                if response.text:
                    print(f"[PASS] Model says: {response.text}")
                    success = True
                    break
    except Exception as e:
        print(f"[FAIL] Error during test: {e}")
        return False

    return success


async def test_product_db():
    """Test the product database module with mock operations."""
    print("\n--- Testing product_db module ---")
    try:
        from product_db import _normalize_name, _product_id

        # Test name normalisation
        assert _normalize_name("Chobani Greek Yogurt 32oz") == "chobani greek yogurt"
        assert _normalize_name("  TIDE Pods 42-Count ") == "tide pods"
        assert _normalize_name("Coca-Cola 12-pack 12 fl oz") == "cocacola"
        print("[PASS] Name normalisation: PASSED")

        # Test deterministic IDs
        id1 = _product_id("Chobani Greek Yogurt 32oz")
        id2 = _product_id("chobani greek yogurt")
        assert id1 == id2, f"IDs should match: {id1} != {id2}"
        print("[PASS] Deterministic product IDs: PASSED")

        print("[PASS] product_db unit tests: ALL PASSED")
        return True
    except Exception as e:
        print(f"[FAIL] product_db test failed: {e}")
        return False


if __name__ == "__main__":
    results = {}

    # Always run DB unit tests (no cloud needed)
    results["product_db"] = asyncio.run(test_product_db())

    # Run vision test if --live flag is passed
    if "--live" in sys.argv:
        results["vision"] = asyncio.run(test_vision_response())
    else:
        print("\n--- Skipping live API test (pass --live to enable) ---")

    # Summary
    print("\n" + "=" * 40)
    print("TEST SUMMARY")
    print("=" * 40)
    for name, passed in results.items():
        status = "[PASS] PASS" if passed else "[FAIL] FAIL"
        print(f"  {name}: {status}")

    all_passed = all(results.values())
    sys.exit(0 if all_passed else 1)
