# Store-Sense — AI Live Shopping Assistant

> A real-time, voice-first AI shopping companion that **sees products through your camera** and helps you shop smarter — all from your browser.

## What It Does

Point your camera at any product in a store and Store-Sense will:

- 👁️ **Read labels & prices** — Identifies products, reads shelf tags, and calculates unit prices visually
- 💬 **Talk naturally** — Full-duplex voice conversation with real-time interruption support
- ⌨️ **Text chat** — Type messages and get text responses alongside voice
- 💰 **Track prices** — Logs every product to Firestore with store, price, and date
- 📊 **Compare across stores** — "You saw this for $3.99 at Kroger last week — that's 15% cheaper than here"
- 🥗 **Analyze nutrition** — Reads nutrition labels and flags added sugars, sodium, highlights protein/fiber
- 🔍 **Find deals** — Uses Google Search to find current coupons, promotions, and competing prices
- ⚖️ **Compare value** — Automatically compares price-per-oz across similar products on the same shelf

## Architecture

```
Browser (camera 30+ FPS, mic, chat)
    ↕ WebSocket
FastAPI server.py (relay)
    ↕ Gemini SDK
Gemini Live API + Firestore
```

The browser captures camera at **30+ FPS** for a smooth local preview but only sends **1 frame/sec** to Gemini to stay within bandwidth limits. Audio streams in real-time at 16 kHz.

## UI Features

- **Camera panel** — 30+ FPS local preview, 1 FPS sent to Gemini
- **Chat panel** — text input with streaming AI responses
- **Mic toggle** — full-duplex audio with animated pulsing ring
- **Response mode** — voice only, voice+text, or text only
- **Store input** — set the current store name in the top bar
- **Product log sidebar** — slides in when products are logged via tool calls
- **Interruption support** — speak over the AI to interrupt mid-sentence

## Powered By

- **Gemini Live API** — Real-time multimodal conversation (vision + audio)
- **Google Search Grounding** — Live deal and price lookups
- **Cloud Firestore** — Persistent product & price database
- **FastAPI + WebSockets** — Real-time relay between browser and Gemini
- **Google Cloud (Vertex AI)** — Model hosting

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Authenticate with Google Cloud
gcloud auth application-default login

# 3. Start the web server
python main.py

# 4. Open in browser
# → http://localhost:8000
```

Then:

1. **Click the camera area** to enable your webcam
2. **Type a store name** (e.g. "Walmart") in the top bar
3. **Choose a response mode** — voice, voice+text, or text-only
4. **Type a message** or **click the mic button** to talk
5. **Point your camera** at a product — the AI will read prices, log them, and compare across stores

## Deployment to Google Cloud (Cloud Run)

Store-Sense is a unified FastAPI app—the **backend API** and the **frontend UI** are served together. Hosting it on Google Cloud Run deploys the entire application.

1. **Authenticate and set project**:

```bash
gcloud auth login
gcloud config set project hackathons-461900
```

2. **Enable APIs**:

```bash
gcloud services enable cloudbuild.googleapis.com run.googleapis.com containerregistry.googleapis.com
```

3. **Deploy (UI + Backend)**:

```bash
gcloud builds submit --config cloudbuild.yaml .
```

4. **Grant permissions**:
   Cloud Run uses the default compute service account which requires Vertex AI and Datastore permissions.

```bash
PROJECT_NUM=$(gcloud projects describe hackathons-461900 --format="value(projectNumber)")
gcloud projects add-iam-policy-binding hackathons-461900 \
    --member="serviceAccount:$PROJECT_NUM-compute@developer.gserviceaccount.com" \
    --role="roles/aiplatform.user"
gcloud projects add-iam-policy-binding hackathons-461900 \
    --member="serviceAccount:$PROJECT_NUM-compute@developer.gserviceaccount.com" \
    --role="roles/datastore.user"
```

## Project Structure

105:
| File | Purpose |
| ------------------- | ----------------------------------------------------------- |
| `main.py` | Entry point — launches FastAPI via uvicorn |
| `server.py` | FastAPI WebSocket relay between browser and Gemini Live API |
| `product_db.py` | Firestore database for product & price tracking |
| `static/index.html` | Single-page UI layout |
| `static/styles.css` | Dark glassmorphism theme |
| `static/app.js` | WebSocket, camera, mic/speaker, chat, product log logic |
| `live_session.py` | Standalone CLI session (legacy, pre-web-UI) |
| `vision_stream.py` | OpenCV webcam capture (legacy, pre-web-UI) |
| `audio_stream.py` | Sounddevice audio engine (legacy, pre-web-UI) |
