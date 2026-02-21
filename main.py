"""
main.py — Store-Sense Launcher
==============================
Initializes the environment and starts the real-time AI Personal Shopper.
"""

import asyncio
import sys
from live_session import run_live_session

async def main():
    print("[Store-Sense] Starting application...")
    try:
        await run_live_session()
    except Exception as e:
        print(f"[Store-Sense] Fatal error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Store-Sense] Exiting.")
