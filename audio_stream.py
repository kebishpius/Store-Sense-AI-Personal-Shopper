"""
audio_stream.py — Store-Sense Native Audio Engine
==================================================
Handles all real-time audio I/O for the Live Shopping Assistant session:

  MIC  →  16 kHz mono int16 PCM  →  Gemini Live API
  Gemini Live API  →  24 kHz mono int16 PCM  →  Speaker

Key design choices
------------------
* Full-duplex at all times: mic capture NEVER pauses during playback.
  This is what lets Gemini's server-side VAD detect when you start
  speaking and raise the `interrupted` signal immediately.

* Interruption handling: when the server flags `interrupted=True`,
  the in-flight speaker queue is drained instantly (silence within
  one callback cycle ~21 ms at 24 kHz / 512 frames), so the AI
  stops mid-sentence and the mic keeps streaming without a gap.

* Thread-safe bridge: sounddevice callbacks run on a C audio thread.
  We use asyncio.run_coroutine_threadsafe to hand PCM chunks over
  to the asyncio event loop safely.

* PyAudio note: PyAudio has no pre-built wheel for Python 3.14.
  sounddevice is the modern equivalent (PortAudio under the hood,
  same wire format) and works identically for raw PCM streaming.
"""

import asyncio
import sys
from collections import deque

import numpy as np
import sounddevice as sd

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

MIC_SAMPLE_RATE  = 16_000   # Hz  — what Gemini Live expects for audio input
SPK_SAMPLE_RATE  = 24_000   # Hz  — what Gemini Live outputs
CHANNELS         = 1
MIC_BLOCKSIZE    = 512      # frames/callback  (~32 ms at 16 kHz)
SPK_BLOCKSIZE    = 512      # frames/callback  (~21 ms at 24 kHz)
DTYPE            = "int16"


# ─────────────────────────────────────────────
# AudioEngine
# ─────────────────────────────────────────────

class AudioEngine:
    """
    Full-duplex audio engine for the Gemini Live session.

    Usage::

        engine = AudioEngine(loop)
        engine.start()
        try:
            # send mic chunks to Gemini
            chunk = await engine.mic_queue.get()
            # receive model audio and queue it for playback
            await engine.enqueue_playback(pcm_bytes)
            # handle interruption (user started speaking)
            engine.interrupt()
        finally:
            engine.stop()

    Attributes
    ----------
    mic_queue : asyncio.Queue[bytes]
        16 kHz int16 PCM chunks ready to forward to session.send().
    is_model_speaking : bool
        True while there are pending audio chunks in the playback buffer.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop   = loop
        self.mic_queue: asyncio.Queue[bytes] = asyncio.Queue()

        # Speaker buffer — a deque of numpy arrays consumed by the output callback
        self._spk_buf: deque[np.ndarray] = deque()
        self._spk_lock = asyncio.Lock()

        # Streams
        self._in_stream:  sd.InputStream  | None = None
        self._out_stream: sd.OutputStream | None = None

        # State flag: True while we have audio queued for playback
        self.is_model_speaking = False

        # Interruption counter for logging
        self._interruption_count = 0

    # ── Mic callback (C audio thread) ────────────────────────────────────

    def _mic_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status,
    ) -> None:
        """Called by sounddevice on the audio thread for each mic block."""
        if status:
            print(f"[audio/mic] {status}", file=sys.stderr)
        # Copy because indata is a view into a reused buffer
        asyncio.run_coroutine_threadsafe(
            self.mic_queue.put(bytes(indata)),
            self._loop,
        )

    # ── Speaker callback (C audio thread) ────────────────────────────────

    def _spk_callback(
        self,
        outdata: np.ndarray,
        frames: int,
        time_info,
        status,
    ) -> None:
        """
        Called by sounddevice on the audio thread for each output block.

        Fills `outdata` from the playback deque.  Any shortage is zero-padded
        (silence) so the stream never underruns audibly.
        """
        if status:
            print(f"[audio/spk] {status}", file=sys.stderr)

        remaining = frames
        offset    = 0

        while remaining > 0 and self._spk_buf:
            chunk = self._spk_buf[0]
            take  = min(remaining, len(chunk))
            outdata[offset : offset + take, 0] = chunk[:take]
            offset    += take
            remaining -= take
            if take == len(chunk):
                self._spk_buf.popleft()
            else:
                self._spk_buf[0] = chunk[take:]

        if remaining > 0:
            # Underrun — pad with silence
            outdata[offset:, 0] = 0

        self.is_model_speaking = bool(self._spk_buf)

    # ── Public API ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Open both sounddevice streams."""
        self._in_stream = sd.InputStream(
            samplerate=MIC_SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=MIC_BLOCKSIZE,
            callback=self._mic_callback,
        )
        self._out_stream = sd.OutputStream(
            samplerate=SPK_SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=SPK_BLOCKSIZE,
            callback=self._spk_callback,
        )
        self._in_stream.start()
        self._out_stream.start()
        print(
            f"[audio] Streams open — mic {MIC_SAMPLE_RATE} Hz | "
            f"speaker {SPK_SAMPLE_RATE} Hz | block {MIC_BLOCKSIZE} frames"
        )

    def stop(self) -> None:
        """Close both sounddevice streams."""
        if self._in_stream:
            self._in_stream.stop()
            self._in_stream.close()
        if self._out_stream:
            self._out_stream.stop()
            self._out_stream.close()
        print("[audio] Streams closed.")

    async def enqueue_playback(self, pcm_bytes: bytes) -> None:
        """
        Append a raw int16 PCM chunk to the speaker playback buffer.
        Safe to call from the asyncio event loop.
        """
        arr = np.frombuffer(pcm_bytes, dtype=DTYPE)
        # The deque is only mutated from the event loop (here) and read from
        # the audio thread (callback).  For short appends this race is safe:
        # the callback will simply see the new item on the next cycle.
        self._spk_buf.append(arr)
        self.is_model_speaking = True

    def interrupt(self) -> None:
        """
        Handle an AI interruption event.

        Drains the entire speaker buffer so playback stops within one
        audio callback cycle (~21 ms).  The mic stream keeps running
        uninterrupted, so the user's speech continues to flow to Gemini.
        """
        pending = len(self._spk_buf)
        self._spk_buf.clear()
        self.is_model_speaking = False
        self._interruption_count += 1
        if pending:
            print(
                f"[audio] Interruption #{self._interruption_count} — "
                f"dropped {pending} buffered chunk(s). Listening..."
            )

    # ── Context manager support ───────────────────────────────────────────

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()
