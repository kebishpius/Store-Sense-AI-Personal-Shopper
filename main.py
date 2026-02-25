"""
main.py — Store-Sense Launcher
==============================
Starts the FastAPI web server that serves the UI and relays
WebSocket connections to the Gemini Live API.

Usage
-----
  python main.py                # http://localhost:8000
  python main.py --port 3000    # http://localhost:3000
"""

import argparse
import uvicorn


def parse_args():
    parser = argparse.ArgumentParser(
        description="Store-Sense — AI Live Shopping Assistant",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to run the web server on (default: 8000).",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    print(f"[Store-Sense] Starting web server at http://localhost:{args.port}")
    print(f"[Store-Sense] Open this URL in your browser to begin.")
    uvicorn.run("server:app", host=args.host, port=args.port, reload=True)
