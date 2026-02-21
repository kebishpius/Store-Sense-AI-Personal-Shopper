"""
live_session.py — Store-Sense Real-Time Engine  (v3)
=====================================================
Streams webcam frames + microphone audio to the Gemini 2.5 Live API
and plays back the model's audio response in real time.

Advanced features
-----------------
  * Google Search Grounding  — lets the model verify prices, recalls, etc.
  * Function Calling         — check_nutrition(upc_code) tool bridge
  * Thinking Mode            — low-budget reasoning for complex shelf analysis
  * vision_stream module     — 720p capture, sharpening, 1 FPS base64 encode
  * audio_stream.AudioEngine — 16kHz mic, 24kHz speaker, interruption handling

Controls
--------
  Press  q  in the camera window (or Ctrl-C in the terminal) to quit.
"""

import asyncio
import json
import sys

from google import genai
from google.genai import types
from vision_stream import frame_stream
from audio_stream import AudioEngine, MIC_SAMPLE_RATE, SPK_SAMPLE_RATE

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
PROJECT_ID   = "hackathons-461900"
LOCATION     = "us-central1"
MODEL        = "gemini-live-2.5-flash-native-audio"

SYSTEM_PROMPT = """
You are Store-Sense, a health-conscious AI shopping assistant. \
Your camera feed is your eyes. Be proactive, concise, and actionable.

## Barcode / UPC visible
- Immediately call check_nutrition(upc_code) with the scanned code.
- While the result loads, verbally state the product's **brand name** and \
**net weight / volume** as you read them from the packaging.
- Example: "I see a 32-oz container of Chobani Greek Yogurt — looking up the nutrition now."

## Shelf tag / price label visible
- Read the unit price (price per ounce, per 100 g, or per unit) from the tag.
- Compare it to other visible sizes of the same product on the shelf. \
Identify which size offers the **best value per ounce**.
- **Competitive Price Check**: Automatically perform a Google Search for the \
'current retail price' of the identified product at major competitors \
(e.g., Amazon, Walmart, Target).
- **Price Logic Gate**: If the local shelf price is more than **10% higher** \
than a major online competitor, proactively interrupt the user and say: \
"Wait, this is cheaper online!" followed by the competitor's name and price.
- Example: "The 16-oz is $0.19/oz here, but it's $0.14/oz online at Amazon. \
Wait, this is cheaper online! Amazon has it for $2.99 while it's $3.50 here."

## Nutrition label visible
- Scan the label and immediately flag:
  - **Added Sugars**: warn if > 10 g per serving (> 20% DV). \
Suggest a lower-sugar alternative if one is visible.
  - **Sodium**: warn if > 600 mg per serving (> 26% DV). \
Label it "High Sodium" and note any heart-health implications.
- Adopt a supportive, health-conscious tone — never judgmental. \
Lead with one clear insight, then offer the full breakdown only if asked.

## General behaviour
- Use Google Search to verify current prices, recalls, or promotions.
- When you detect a barcode or UPC, call check_nutrition immediately.
- Keep spoken responses under 30 seconds; offer to elaborate if needed.
"""

# Audio settings
MIC_SAMPLE_RATE  = 16_000   # Hz — input to Gemini
SPK_SAMPLE_RATE  = 24_000   # Hz — output from Gemini
AUDIO_CHANNELS   = 1
MIC_CHUNK_FRAMES = 1024

# Camera settings
CAMERA_INDEX = 0
FRAME_WIDTH  = 640
FRAME_HEIGHT = 480
FPS_TARGET   = 1            # frames/sec sent to Gemini


# ─────────────────────────────────────────────
# Shared state
# ─────────────────────────────────────────────
_stop_event = asyncio.Event()


# ─────────────────────────────────────────────
# Tool declarations
# ─────────────────────────────────────────────

# check_nutrition function schema exposed to the model
_CHECK_NUTRITION_DECL = types.FunctionDeclaration(
    name="check_nutrition",
    description=(
        "Look up nutritional information for a product given its UPC / barcode. "
        "Returns calories, macros, ingredients, allergens, and health score."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "upc_code": types.Schema(
                type=types.Type.STRING,
                description="The Universal Product Code (UPC/EAN) of the scanned item.",
            )
        },
        required=["upc_code"],
    ),
)


# ─────────────────────────────────────────────
# Tool implementation
# ─────────────────────────────────────────────

def _execute_check_nutrition(upc_code: str) -> dict:
    """
    Real implementation would call the Open Food Facts API or a private DB.
    Stub returns structured placeholder data so the model can reason over it.
    Replace the body of this function with a real API call when ready.
    """
    print(f"[tool] check_nutrition called | upc_code={upc_code!r}")
    # TODO: replace with: requests.get(f"https://world.openfoodfacts.org/api/v0/product/{upc_code}.json")
    return {
        "upc_code": upc_code,
        "product_name": f"Product UPC-{upc_code}",
        "calories_per_serving": 150,
        "serving_size": "1 cup (240ml)",
        "macros": {
            "fat_g": 5,
            "carbohydrates_g": 22,
            "protein_g": 3,
            "sugar_g": 10,
            "fiber_g": 1,
            "sodium_mg": 200,
        },
        "allergens": ["milk", "soy"],
        "nutri_score": "C",
        "note": "Stub data — replace _execute_check_nutrition() with a live API call.",
    }


async def _dispatch_function_call(
    session, fc: types.FunctionCall
) -> None:
    """Execute a function the model requested and send the result back."""
    name = fc.name
    args = dict(fc.args) if fc.args else {}

    if name == "check_nutrition":
        result = _execute_check_nutrition(**args)
    else:
        result = {"error": f"Unknown function: {name}"}

    print(f"[tool] Returning {name} result to model: {json.dumps(result, indent=2)}")

    await session.send(
        input=types.LiveClientToolResponse(
            function_responses=[
                types.FunctionResponse(
                    name=name,
                    id=fc.id,
                    response={"output": result},
                )
            ]
        )
    )



# ─────────────────────────────────────────────
# Core Live Session coroutine
# ─────────────────────────────────────────────

async def run_live_session() -> None:
    """Open a Gemini Live session and multiplex camera + audio I/O."""

    loop   = asyncio.get_event_loop()
    client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=LOCATION,
    )

    # ── Tool list: Google Search + check_nutrition function ───────────────
    tools = [
        types.Tool(google_search=types.GoogleSearch()),          # Search Grounding
        types.Tool(function_declarations=[_CHECK_NUTRITION_DECL]),  # Function Calling
    ]

    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text=SYSTEM_PROMPT)]
        ),
        tools=tools,
    )

    print(f"[Store-Sense] Connecting to {MODEL} ...")
    print(f"[Store-Sense] Tools : Google Search Grounding + check_nutrition")
    print(f"[Store-Sense] Audio : mic={MIC_SAMPLE_RATE} Hz  speaker={SPK_SAMPLE_RATE} Hz")

    with AudioEngine(loop) as engine:
        async with client.aio.live.connect(model=MODEL, config=live_config) as session:
            print("[Store-Sense] Gemini Live session is ACTIVE. Speak or show items to the camera!")
            print("[Store-Sense] Interruption enabled — speak any time to cut the AI off.")

            async def _receive_loop():
                try:
                    async for response in session.receive():
                        if _stop_event.is_set():
                            break

                        server_content = getattr(response, "server_content", None)

                        if server_content and getattr(server_content, "interrupted", False):
                            engine.interrupt()

                        if response.data:
                            await engine.enqueue_playback(response.data)

                        if response.text:
                            print(f"[model] {response.text}")

                        if server_content:
                            model_turn = getattr(server_content, "model_turn", None)
                            if model_turn:
                                for part in (model_turn.parts or []):
                                    if part.function_call:
                                        await _dispatch_function_call(session, part.function_call)

                        tool_call = getattr(response, "tool_call", None)
                        if tool_call:
                            for fc in (tool_call.function_calls or []):
                                await _dispatch_function_call(session, fc)
                except Exception as e:
                    print(f"[error] in _receive_loop: {e}")
                    import traceback
                    traceback.print_exc()
                    _stop_event.set()

            async def _send_audio_loop():
                try:
                    while not _stop_event.is_set():
                        try:
                            chunk = await asyncio.wait_for(engine.mic_queue.get(), timeout=0.5)
                        except asyncio.TimeoutError:
                            continue
                        await session.send_realtime_input(audio=types.Blob(data=chunk, mime_type="audio/pcm"))
                except Exception as e:
                    print(f"[error] in _send_audio_loop: {e}")
                    _stop_event.set()

            async def _send_video_loop():
                try:
                    async for blob in frame_stream(
                        stop_event=_stop_event,
                        show_preview=True,
                        camera_index=CAMERA_INDEX,
                        fps=FPS_TARGET,
                    ):
                        if _stop_event.is_set():
                            break
                        await session.send_realtime_input(video=blob)
                except Exception as e:
                    print(f"[error] in _send_video_loop: {e}")
                    _stop_event.set()

            # ── Launch all tasks concurrently ────────────────────────────
            try:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(_receive_loop())
                    tg.create_task(_send_audio_loop())
                    tg.create_task(_send_video_loop())
            except* (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                _stop_event.set()
                print("[Store-Sense] Session ended.")


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    try:
        asyncio.run(run_live_session())
    except KeyboardInterrupt:
        print("\n[Store-Sense] Interrupted by user.")
