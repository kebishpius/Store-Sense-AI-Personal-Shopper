"""
server.py — Store-Sense Web Server
====================================
FastAPI application that:
  1. Serves the static frontend (HTML/CSS/JS)
  2. Exposes a WebSocket at /ws that relays between the browser
     and a Gemini Live API session

Each WebSocket connection gets its own Gemini Live session.
Video frames arrive from the browser at 1 FPS and are forwarded.
Audio and text are relayed bidirectionally.
"""

import asyncio
import base64
import json
import traceback

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from google import genai
from google.genai import types
from product_db import log_product, query_price_history

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
PROJECT_ID = "hackathons-461900"
LOCATION   = "us-central1"
MODEL      = "gemini-live-2.5-flash-native-audio"

MIC_SAMPLE_RATE = 16_000
SPK_SAMPLE_RATE = 24_000

app = FastAPI(title="Store-Sense")


# ─────────────────────────────────────────────
# System prompt builder
# ─────────────────────────────────────────────

def _build_system_prompt(store_name: str = "", response_mode: str = "voice") -> str:
    store_ctx = (
        f"The user is currently shopping at **{store_name}**. "
        f"Use this as the store name when logging products."
        if store_name
        else (
            "The user has not specified which store they are in yet. "
            "Ask them when you need to log a product."
        )
    )

    response_guidance = ""
    if response_mode == "text":
        response_guidance = (
            "\n\n## Response format\n"
            "Respond with TEXT only. Do not produce audio output. "
            "Keep responses concise and well-structured."
        )

    return f"""\
You are **Store-Sense**, a real-time AI personal shopping assistant. \
Your camera feed is your eyes — you can see products, shelf tags, \
price labels, and nutrition facts live. Be proactive, concise, and actionable.

## Store Context
{store_ctx}

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
- If the camera shows **multiple products** of the same category, \
compare their **unit prices** (price per oz or per lb).
- Proactively say which is the better value.

## Nutrition analysis
When you can see a **nutrition facts label**:
- **Added Sugars**: Warn if > 10 g per serving (> 20% DV).
- **Sodium**: Warn if > 600 mg per serving (> 26% DV).
- **Protein & Fiber**: Highlight if notably high (positive).
- Be supportive, never judgmental.

## Using Google Search for deals
- Use Google Search to look up current promotions, coupons, or \
competing prices when asked or when something seems overpriced.

## General behaviour
- Keep spoken responses **under 30 seconds**. Offer to elaborate if needed.
- Be conversational and natural.
- When uncertain about a product identity, ask the user to confirm.
{response_guidance}"""


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
                description="Product name including brand and size.",
            ),
            "price": types.Schema(
                type=types.Type.NUMBER,
                description="Shelf price in dollars.",
            ),
            "unit_price": types.Schema(
                type=types.Type.NUMBER,
                description="Price per unit (oz, lb, or count).",
            ),
            "unit": types.Schema(
                type=types.Type.STRING,
                description="Unit for the unit price: 'oz', 'lb', 'count', etc.",
            ),
            "store": types.Schema(
                type=types.Type.STRING,
                description="Name of the store.",
            ),
            "category": types.Schema(
                type=types.Type.STRING,
                description="Product category: 'dairy', 'snacks', 'produce', etc.",
            ),
            "nutrition_score": types.Schema(
                type=types.Type.STRING,
                description="Health/nutrition grade: 'A', 'B+', 'C', etc.",
            ),
            "on_sale": types.Schema(
                type=types.Type.BOOLEAN,
                description="True if the product appears to be on sale.",
            ),
        },
        required=["name", "price", "unit_price", "unit", "store"],
    ),
)

_QUERY_PRICE_HISTORY_DECL = types.FunctionDeclaration(
    name="query_price_history",
    description=(
        "Look up the price history for a product across all stores."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "product_name": types.Schema(
                type=types.Type.STRING,
                description="Product name to look up.",
            ),
        },
        required=["product_name"],
    ),
)


# ─────────────────────────────────────────────
# Tool dispatcher
# ─────────────────────────────────────────────

async def _dispatch_function_call(gemini_session, fc, client_ws: WebSocket):
    """Execute a tool call and return the result to both Gemini and the browser."""
    name = fc.name
    args = dict(fc.args) if fc.args else {}

    if name == "log_product":
        result = await log_product(**args)
    elif name == "query_price_history":
        result = await query_price_history(**args)
    else:
        result = {"error": f"Unknown function: {name}"}

    print(f"[tool] {name} -> {json.dumps(result, indent=2, default=str)}")

    # Send result back to Gemini
    await gemini_session.send(
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

    # Notify the browser about the tool result
    try:
        await client_ws.send_json({
            "type": "tool_result",
            "name": name,
            "result": result,
        })
    except Exception:
        pass


# ─────────────────────────────────────────────
# WebSocket endpoint
# ─────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    print("[ws] Client connected")

    stop_event = asyncio.Event()
    store_name = ""
    response_mode = "voice"  # "voice", "text", or "both"

    # Wait for initial config message
    try:
        init_msg = await asyncio.wait_for(ws.receive_json(), timeout=10)
        if init_msg.get("type") == "config":
            store_name = init_msg.get("store", "")
            response_mode = init_msg.get("response_mode", "voice")
            print(f"[ws] Config: store={store_name}, mode={response_mode}")
    except Exception as e:
        print(f"[ws] No config received, using defaults: {e}")

    # Build Gemini session config
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)

    response_modalities = []
    if response_mode in ("voice", "both"):
        response_modalities.append("AUDIO")
    if response_mode in ("text", "both"):
        response_modalities.append("TEXT")
    if not response_modalities:
        response_modalities = ["AUDIO"]

    tools = [
        types.Tool(google_search=types.GoogleSearch()),
        types.Tool(function_declarations=[_LOG_PRODUCT_DECL, _QUERY_PRICE_HISTORY_DECL]),
    ]

    live_config = types.LiveConnectConfig(
        response_modalities=response_modalities,
        system_instruction=types.Content(
            parts=[types.Part(text=_build_system_prompt(store_name, response_mode))]
        ),
        tools=tools,
    )

    print(f"[ws] Connecting to {MODEL} ...")

    try:
        async with client.aio.live.connect(model=MODEL, config=live_config) as session:
            print("[ws] Gemini session ACTIVE")
            await ws.send_json({"type": "status", "message": "connected"})

            # ── Receive from Gemini, forward to browser ──────────────
            async def _gemini_to_browser():
                try:
                    async for response in session.receive():
                        if stop_event.is_set():
                            break

                        server_content = getattr(response, "server_content", None)

                        # Handle interruption
                        if server_content and getattr(server_content, "interrupted", False):
                            await ws.send_json({"type": "interrupted"})

                        # Audio data
                        if response.data:
                            audio_b64 = base64.b64encode(response.data).decode("utf-8")
                            await ws.send_json({
                                "type": "audio",
                                "data": audio_b64,
                            })

                        # Text data
                        if response.text:
                            await ws.send_json({
                                "type": "text",
                                "text": response.text,
                            })

                        # Function calls
                        if server_content:
                            model_turn = getattr(server_content, "model_turn", None)
                            if model_turn:
                                for part in (model_turn.parts or []):
                                    if part.function_call:
                                        await _dispatch_function_call(session, part.function_call, ws)

                        tool_call = getattr(response, "tool_call", None)
                        if tool_call:
                            for fc in (tool_call.function_calls or []):
                                await _dispatch_function_call(session, fc, ws)

                except WebSocketDisconnect:
                    print("[ws] Client disconnected during receive")
                except Exception as e:
                    print(f"[ws] Gemini receive error: {e}")
                    traceback.print_exc()
                finally:
                    stop_event.set()

            # ── Receive from browser, forward to Gemini ──────────────
            async def _browser_to_gemini():
                try:
                    while not stop_event.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.receive_text(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue

                        msg = json.loads(raw)
                        msg_type = msg.get("type")

                        if msg_type == "video_frame":
                            # base64 JPEG from browser canvas
                            frame_data = base64.b64decode(msg["data"])
                            await session.send_realtime_input(
                                video=types.Blob(data=frame_data, mime_type="image/jpeg")
                            )

                        elif msg_type == "audio_chunk":
                            # base64 PCM int16 from browser mic
                            audio_data = base64.b64decode(msg["data"])
                            await session.send_realtime_input(
                                audio=types.Blob(data=audio_data, mime_type="audio/pcm")
                            )

                        elif msg_type == "text_message":
                            # Text input from chat
                            await session.send_client_content(
                                turns=[
                                    types.Content(
                                        parts=[types.Part(text=msg["text"])]
                                    )
                                ],
                                turn_complete=True,
                            )

                        elif msg_type == "config_update":
                            # Runtime config updates (store name only — modality
                            # can't change mid-session)
                            if "store" in msg:
                                store_name = msg["store"]
                                print(f"[ws] Store updated to: {store_name}")

                except WebSocketDisconnect:
                    print("[ws] Client disconnected during send")
                except Exception as e:
                    print(f"[ws] Browser receive error: {e}")
                    traceback.print_exc()
                finally:
                    stop_event.set()

            # Run both relay loops concurrently
            try:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(_gemini_to_browser())
                    tg.create_task(_browser_to_gemini())
            except* (WebSocketDisconnect, asyncio.CancelledError):
                pass

    except Exception as e:
        print(f"[ws] Gemini connection error: {e}")
        traceback.print_exc()
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass

    print("[ws] Session ended")


# ─────────────────────────────────────────────
# Static files & SPA fallback
# ─────────────────────────────────────────────

@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")

app.mount("/static", StaticFiles(directory="static"), name="static")
