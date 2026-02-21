"""
vision_stream.py — Store-Sense Vision Module
=============================================
Provides a self-contained async generator that captures webcam frames,
sharpens them for small-text legibility, encodes them to base64 JPEG,
and yields ready-to-send Blob objects at a target 1 FPS.

Design goals
------------
* 720p native capture  — enough resolution to read barcodes & nutrition facts
* 1 FPS send rate      — preserves Live API bandwidth budget
* Sharpening pass      — raises contrast on fine text before encoding
* Plug-and-play        — drop into any async caller via `async for blob in frame_stream()`

Integration with live_session.py
---------------------------------
Replace the inline _send_video_loop body with::

    from vision_stream import frame_stream
    async for blob in frame_stream():
        if _stop_event.is_set():
            break
        await session.send(
            input=types.LiveClientRealtimeInput(media_chunks=[blob])
        )
"""

import asyncio
import base64
import sys
import time
from typing import AsyncGenerator

import cv2
import numpy as np
from google.genai import types

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

# Capture resolution — 720p gives Gemini enough detail to read small text.
# Falls back gracefully if the webcam doesn't support it.
CAPTURE_WIDTH  = 1280
CAPTURE_HEIGHT = 720

# Resolution forwarded to Gemini — can be the same as capture or smaller.
# 1280x720 is the sweet-spot: clear text, reasonable JPEG size (~35-60 KB/frame).
SEND_WIDTH  = 1280
SEND_HEIGHT = 720

CAMERA_INDEX  = 0
FPS_TARGET    = 1          # frames per second delivered to Gemini
JPEG_QUALITY  = 85         # 85 keeps barcodes crisp without overshooting bandwidth

# Unsharp-mask parameters used to make fine text pop before encoding
_SHARPEN_AMOUNT   = 1.5    # blend factor (1.0 = original, >1 = sharper)
_SHARPEN_BLUR_PX  = 0      # GaussianBlur kernel size (0 = auto from sigma)
_SHARPEN_SIGMA    = 1.0    # blur sigma for the unsharp mask


# ─────────────────────────────────────────────
# Image processing helpers
# ─────────────────────────────────────────────

def _sharpen(frame: np.ndarray) -> np.ndarray:
    """Apply an unsharp mask to help Gemini read fine text and barcodes."""
    blurred = cv2.GaussianBlur(
        frame,
        (_SHARPEN_BLUR_PX, _SHARPEN_BLUR_PX),
        _SHARPEN_SIGMA,
    )
    return cv2.addWeighted(frame, _SHARPEN_AMOUNT, blurred, -(_SHARPEN_AMOUNT - 1), 0)


def _resize(frame: np.ndarray, width: int, height: int) -> np.ndarray:
    """Resize frame to target dimensions using INTER_AREA (best for downscale)."""
    if frame.shape[1] == width and frame.shape[0] == height:
        return frame
    interp = cv2.INTER_AREA if frame.shape[1] > width else cv2.INTER_LINEAR
    return cv2.resize(frame, (width, height), interpolation=interp)


def encode_frame(frame: np.ndarray) -> bytes:
    """
    Downsample → sharpen → JPEG encode → base64.

    Returns raw base64-encoded bytes ready for types.Blob(data=...).
    """
    resized   = _resize(frame, SEND_WIDTH, SEND_HEIGHT)
    sharpened = _sharpen(resized)
    ok, buf   = cv2.imencode(".jpg", sharpened, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise RuntimeError("cv2.imencode failed — cannot encode frame.")
    return base64.b64encode(buf).decode("utf-8")


# ─────────────────────────────────────────────
# Camera context manager
# ─────────────────────────────────────────────

class WebcamCapture:
    """Thin wrapper around cv2.VideoCapture with 720p defaults and a context manager."""

    def __init__(self, index: int = CAMERA_INDEX):
        self._index = index
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> "WebcamCapture":
        cap = cv2.VideoCapture(self._index)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  CAPTURE_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
        # Try to set camera buffer to 1 frame to reduce latency
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            raise RuntimeError(
                f"[vision_stream] Cannot open camera at index {self._index}."
            )
        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(
            f"[vision_stream] Camera opened: {actual_w}x{actual_h} "
            f"(requested {CAPTURE_WIDTH}x{CAPTURE_HEIGHT})"
        )
        self._cap = cap
        return self

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._cap is None:
            raise RuntimeError("Camera is not open.")
        return self._cap.read()

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *_):
        self.release()


# ─────────────────────────────────────────────
# Async frame generator
# ─────────────────────────────────────────────

async def frame_stream(
    stop_event: asyncio.Event | None = None,
    show_preview: bool = True,
    camera_index: int = CAMERA_INDEX,
    fps: float = FPS_TARGET,
) -> AsyncGenerator[types.Blob, None]:
    """
    Async generator that yields one ``types.Blob`` per frame at ``fps`` rate.

    Parameters
    ----------
    stop_event   : asyncio.Event — set this to stop the generator externally.
    show_preview : bool          — whether to show an OpenCV preview window.
    camera_index : int           — webcam device index.
    fps          : float         — target frames per second to yield.

    Yields
    ------
    types.Blob with mime_type="image/jpeg" ready to pass directly to
    ``session.send(input=types.LiveClientRealtimeInput(media_chunks=[blob]))``.

    Example
    -------
    ::

        from vision_stream import frame_stream

        async for blob in frame_stream(stop_event=_stop_event):
            await session.send(
                input=types.LiveClientRealtimeInput(media_chunks=[blob])
            )
    """
    frame_interval = 1.0 / fps
    loop = asyncio.get_event_loop()

    with WebcamCapture(camera_index) as cam:
        print(f"[vision_stream] Streaming at {fps} FPS → Gemini "
              f"({SEND_WIDTH}x{SEND_HEIGHT}, JPEG q={JPEG_QUALITY})")

        while True:
            # Respect an external stop signal
            if stop_event is not None and stop_event.is_set():
                break

            t0 = loop.time()

            # Read frame off the thread pool so the event loop stays free
            ret, frame = await loop.run_in_executor(None, cam.read)
            if not ret or frame is None:
                print("[vision_stream] Failed to grab frame — stopping.", file=sys.stderr)
                break

            # --- Optional preview window with quit key ---
            if show_preview:
                preview = _resize(frame.copy(), SEND_WIDTH, SEND_HEIGHT)
                cv2.putText(
                    preview,
                    f"Store-Sense  |  {SEND_WIDTH}x{SEND_HEIGHT}  |  {fps:.0f} FPS to Gemini",
                    (12, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 127), 2,
                )
                cv2.imshow("Store-Sense — Vision Stream", preview)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    if stop_event is not None:
                        stop_event.set()
                    break

            # Encode and yield
            try:
                b64_bytes = encode_frame(frame)
                yield types.Blob(
                    data=base64.b64decode(b64_bytes),
                    mime_type="image/jpeg",
                )
            except Exception as exc:
                print(f"[vision_stream] Encode error: {exc}", file=sys.stderr)

            # Pace to FPS_TARGET
            elapsed = loop.time() - t0
            sleep_for = frame_interval - elapsed
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    cv2.destroyAllWindows()
    print("[vision_stream] Stream stopped.")


# ─────────────────────────────────────────────
# Standalone smoke-test
# ─────────────────────────────────────────────

async def _smoke_test(n_frames: int = 5) -> None:
    """Capture n_frames, print their size, and exit — no Gemini session needed."""
    stop = asyncio.Event()
    count = 0
    async for blob in frame_stream(stop_event=stop, show_preview=True):
        size_kb = len(blob.data) / 1024
        print(f"[smoke_test] Frame {count + 1}/{n_frames} — {size_kb:.1f} KB")
        count += 1
        if count >= n_frames:
            stop.set()
            break
    print("[smoke_test] Done.")


if __name__ == "__main__":
    asyncio.run(_smoke_test())
