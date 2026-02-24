"""
live_session.py — Store-Sense Real-Time Engine  (v4 — Live Shopping Assistant)
==============================================================================
Streams webcam frames + microphone audio to the Gemini 2.5 Live API
and plays back the model's audio response in real time.

The model acts as a visual shopping companion that:
  * Reads product labels, shelf tags, and prices through the camera
  * Logs products + prices to Firestore via function calling
  * Queries price history across stores
  * Uses Google Search to find current deals and coupons
  * Provides nutritional analysis from visual label reading
  * Compares price-per-unit across visible products

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
from product_db import log_product, query_price_history

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
PROJECT_ID   = "hackathons-461900"
LOCATION     = "us-central1"
MODEL        = "gemini-live-2.5-flash-native-audio"

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
# System Prompt
# ─────────────────────────────────────────────

def _build_system_prompt(store_name: str = "") -> str:
    store_context = (
        f"The user is currently shopping at **{store_name}**. "
        f"Use this as the store name when logging products."
        if store_name
        else (
            "The user has not specified which store they are in. "
            "Ask them at the start of the conversation, or whenever you "
            "need to log a product. Once they tell you, remember it for "
            "the rest of the session."
        )
    )

    return f"""\
You are **Store-Sense**, a real-time AI personal shopping assistant. \
Your camera feed is your eyes — you can see products, shelf tags, \
price labels, and nutrition facts live. Be proactive, concise, and actionable.

## Store Context
{store_context}

## When you see a product with a price tag
1. **Read aloud** the product name, size, and shelf price you see.
2. **Calculate the unit price** (price per oz, per lb, or per count) \
from the tag if visible.
3. **Immediately call `log_product`** with the details to save it.
4. **Immediately call `query_price_history`** with the product name \
to check if the user has seen it cheaper at another store.
   - If a cheaper sighting exists, tell the user: \
"You saw this for $X.XX at [Store] on [date] — that's Y% cheaper!"
   - If this is the cheapest you've logged, say: "This is the best \
price I have on record for this item."

## Comparing products on the same shelf
- If the camera shows **multiple products** of the same category \
(e.g. two brands of peanut butter), compare their **unit prices** \
(price per oz or per lb).
- Proactively say which is the better value: \
"The store brand is $0.12/oz vs $0.18/oz for the name brand — \
you'd save about $1.92 on the bigger jar."

## Nutrition analysis
When you can see a **nutrition facts label**:
- **Added Sugars**: Warn if > 10 g per serving (> 20% DV). \
Suggest checking for a lower-sugar option.
- **Sodium**: Warn if > 600 mg per serving (> 26% DV). \
Note heart-health implications.
- **Protein & Fiber**: Highlight if notably high (positive).
- Adopt a supportive, health-conscious tone — never judgmental. \
Lead with one clear insight, offer the full breakdown only if asked.

## Using Google Search for deals
- When the user asks about deals, or when you notice a product seems \
overpriced, use **Google Search** to look up current promotions, \
coupons, or competing prices for that product.
- Report what you find concisely: "I found a $1.00 off coupon on \
[retailer].com" or "Amazon has this for $X.XX right now."

## General behaviour
- Keep spoken responses **under 30 seconds**. Offer to elaborate if needed.
- Be conversational and natural — you're a helpful friend shopping alongside.
- If the user asks "should I buy this?", synthesise price history, \
nutrition, and any deals you found into a clear recommendation.
- When uncertain about a product identity, ask the user to confirm \
before logging.
"""


# ─────────────────────────────────────────────
# Shared state
# ─────────────────────────────────────────────
_stop_event = asyncio.Event()


# ─────────────────────────────────────────────
# Tool declarations
# ─────────────────────────────────────────────

_LOG_PRODUCT_DECL = types.FunctionDeclaration(
    name="log_product",
    description=(
        "Save a product sighting to the database. Call this whenever you "
        "identify a product and its price from the camera feed."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "name": types.Schema(
                type=types.Type.STRING,
                description="Product name including brand and size, e.g. 'Chobani Greek Yogurt 32oz'.",
            ),
            "price": types.Schema(
                type=types.Type.NUMBER,
                description="Shelf price in dollars, e.g. 5.99.",
            ),
            "unit_price": types.Schema(
                type=types.Type.NUMBER,
                description="Price per unit (oz, lb, or count), e.g. 0.187.",
            ),
            "unit": types.Schema(
                type=types.Type.STRING,
                description="Unit for the unit price: 'oz', 'lb', 'count', 'ml', 'g', etc.",
            ),
            "store": types.Schema(
                type=types.Type.STRING,
                description="Name of the store, e.g. 'Walmart', 'Kroger'.",
            ),
            "category": types.Schema(
                type=types.Type.STRING,
                description="Product category, e.g. 'dairy', 'snacks', 'produce', 'beverages'.",
            ),
            "nutrition_score": types.Schema(
                type=types.Type.STRING,
                description="Your health/nutrition grade for this product: 'A', 'B+', 'C', etc.",
            ),
            "on_sale": types.Schema(
                type=types.Type.BOOLEAN,
                description="True if the product appears to be on sale or has a visible discount.",
            ),
        },
        required=["name", "price", "unit_price", "unit", "store"],
    ),
)

_QUERY_PRICE_HISTORY_DECL = types.FunctionDeclaration(
    name="query_price_history",
    description=(
        "Look up the price history for a product across all stores the user "
        "has visited. Returns all past sightings sorted by price."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "product_name": types.Schema(
                type=types.Type.STRING,
                description="Product name to look up, e.g. 'Chobani Greek Yogurt'.",
            ),
        },
        required=["product_name"],
    ),
)


# ─────────────────────────────────────────────
# Tool implementation dispatcher
# ─────────────────────────────────────────────

async def _execute_log_product(**kwargs) -> dict:
    """Bridge to product_db.log_product()."""
    print(f"[tool] log_product called | args={kwargs}")
    try:
        result = await log_product(**kwargs)
        return result
    except Exception as e:
        print(f"[tool] log_product error: {e}")
        return {"error": str(e), "status": "failed"}


async def _execute_query_price_history(**kwargs) -> dict:
    """Bridge to product_db.query_price_history()."""
    print(f"[tool] query_price_history called | args={kwargs}")
    try:
        result = await query_price_history(**kwargs)
        return result
    except Exception as e:
        print(f"[tool] query_price_history error: {e}")
        return {"error": str(e), "status": "failed"}


async def _dispatch_function_call(
    session, fc: types.FunctionCall
) -> None:
    """Execute a function the model requested and send the result back."""
    name = fc.name
    args = dict(fc.args) if fc.args else {}

    if name == "log_product":
        result = await _execute_log_product(**args)
    elif name == "query_price_history":
        result = await _execute_query_price_history(**args)
    else:
        result = {"error": f"Unknown function: {name}"}

    print(f"[tool] Returning {name} result to model: {json.dumps(result, indent=2, default=str)}")

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

async def run_live_session(store_name: str = "") -> None:
    """Open a Gemini Live session and multiplex camera + audio I/O."""

    loop   = asyncio.get_event_loop()
    client = genai.Client(
        vertexai=True,
        project=PROJECT_ID,
        location=LOCATION,
    )

    # ── Tool list: Google Search + custom function tools ─────────────────
    tools = [
        types.Tool(google_search=types.GoogleSearch()),
        types.Tool(function_declarations=[_LOG_PRODUCT_DECL, _QUERY_PRICE_HISTORY_DECL]),
    ]

    system_prompt = _build_system_prompt(store_name)

    live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text=system_prompt)]
        ),
        tools=tools,
    )

    print(f"[Store-Sense] Connecting to {MODEL} ...")
    print(f"[Store-Sense] Store : {store_name or '(will ask user)'}")
    print(f"[Store-Sense] Tools : Google Search + log_product + query_price_history")
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
