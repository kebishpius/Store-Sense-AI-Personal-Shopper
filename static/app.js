/* ═══════════════════════════════════════════════
   Store-Sense — Client-Side Application
   ═══════════════════════════════════════════════
   Manages:
     - WebSocket connection to FastAPI backend
     - Camera capture (30+ FPS local, 1 FPS sent to server)
     - Microphone capture & speaker playback via Web Audio API
     - Chat text messaging
     - UI state (response mode, mic toggle, product log)
*/

// ─── DOM refs ───────────────────────────────────
const statusBadge   = document.getElementById('status-badge');
const storeInput    = document.getElementById('store-name');
const cameraVideo   = document.getElementById('camera-video');
const captureCanvas = document.getElementById('capture-canvas');
const cameraOverlay = document.getElementById('camera-overlay');
const localFpsEl    = document.getElementById('local-fps');
const micBtn        = document.getElementById('mic-btn');
const micStatus     = document.getElementById('mic-status');
const chatMessages  = document.getElementById('chat-messages');
const chatInput     = document.getElementById('chat-input');
const sendBtn       = document.getElementById('send-btn');
const clearChatBtn  = document.getElementById('clear-chat');
const productLog    = document.getElementById('product-log');
const productEntries= document.getElementById('product-entries');
const closeLogBtn   = document.getElementById('close-log');
const modeButtons   = document.querySelectorAll('#response-mode .toggle-btn');

// ─── State ──────────────────────────────────────
let ws = null;
let cameraStream = null;
let frameInterval = null;
let micActive = false;
let audioContext = null;
let micProcessor = null;
let micSource = null;
let micStream = null;
let responseMode = 'both';
let isConnected = false;
let fpsCounter = 0;
let fpsDisplay = 0;

// Speaker playback
let spkContext = null;
let spkQueue = [];
let spkPlaying = false;

// ─── FPS counter ────────────────────────────────
setInterval(() => {
    fpsDisplay = fpsCounter;
    fpsCounter = 0;
    localFpsEl.textContent = `${fpsDisplay} FPS`;
}, 1000);


// ═══════════════════════════════════════════════
// Camera
// ═══════════════════════════════════════════════

cameraOverlay.addEventListener('click', startCamera);

async function startCamera() {
    try {
        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: {
                width: { ideal: 1280 },
                height: { ideal: 720 },
                frameRate: { ideal: 30, min: 24 },
            },
            audio: false,
        });
        cameraVideo.srcObject = cameraStream;
        cameraOverlay.classList.add('hidden');

        // Auto-connect WebSocket as soon as we have a stream
        connectWebSocket();

        // Set canvas to capture resolution
        captureCanvas.width = 640;
        captureCanvas.height = 480;

        // Simple FPS counter using requestAnimationFrame
        const countFps = () => {
            if (!cameraStream) return;
            fpsCounter++;
            requestAnimationFrame(countFps);
        };
        requestAnimationFrame(countFps);

        // Start sending 1 FPS to server
        startFrameSending();
    } catch (err) {
        console.error('Camera error:', err);
        addSystemMessage('Camera access denied or hardware error. You can still use text chat below!');
    }
}

function startFrameSending() {
    if (frameInterval) clearInterval(frameInterval);

    frameInterval = setInterval(() => {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;
        if (!cameraVideo.videoWidth) return;

        const ctx = captureCanvas.getContext('2d');
        ctx.drawImage(cameraVideo, 0, 0, captureCanvas.width, captureCanvas.height);

        // Convert to JPEG base64 (strip data URL prefix)
        const dataUrl = captureCanvas.toDataURL('image/jpeg', 0.85);
        const b64 = dataUrl.split(',')[1];

        ws.send(JSON.stringify({
            type: 'video_frame',
            data: b64,
        }));

        // Visual feedback for frame sending
        const sendStat = document.getElementById('send-fps');
        if (sendStat) {
            sendStat.style.color = 'var(--accent-cyan)';
            setTimeout(() => { sendStat.style.color = ''; }, 200);
        }
    }, 1000); // 1 FPS
}


// ═══════════════════════════════════════════════
// WebSocket
// ═══════════════════════════════════════════════

function connectWebSocket() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.onopen = () => {
        console.log('[ws] Connected');
        // Send initial config
        ws.send(JSON.stringify({
            type: 'config',
            store: storeInput.value.trim(),
            response_mode: responseMode,
        }));
    };

    ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        handleServerMessage(msg);
    };

    ws.onclose = () => {
        console.log('[ws] Disconnected');
        setConnectionStatus(false);
        isConnected = false;
    };

    ws.onerror = (err) => {
        console.error('[ws] Error:', err);
        setConnectionStatus(false);
    };
}

function handleServerMessage(msg) {
    switch (msg.type) {
        case 'status':
            if (msg.message === 'connected') {
                setConnectionStatus(true);
                isConnected = true;
                addSystemMessage('Connected to Gemini. Show products to the camera or type a message!');
            }
            break;

        case 'text':
            hideTypingIndicator();
            addAIMessage(msg.text);
            break;

        case 'audio':
            playAudioChunk(msg.data);
            break;

        case 'interrupted':
            clearAudioQueue();
            break;

        case 'tool_result':
            handleToolResult(msg);
            break;

        case 'error':
            addSystemMessage(`Error: ${msg.message}`);
            break;
    }
}

function setConnectionStatus(connected) {
    statusBadge.textContent = connected ? 'Connected' : 'Disconnected';
    statusBadge.classList.toggle('connected', connected);
}


// ═══════════════════════════════════════════════
// Audio — Microphone Capture
// ═══════════════════════════════════════════════

micBtn.addEventListener('click', toggleMic);

async function toggleMic() {
    if (micActive) {
        stopMic();
    } else {
        await startMic();
    }
}

async function startMic() {
    try {
        micStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: 16000,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
            }
        });

        audioContext = new AudioContext({ sampleRate: 16000 });
        micSource = audioContext.createMediaStreamSource(micStream);

        // Use ScriptProcessor for broad compatibility (AudioWorklet needs HTTPS)
        micProcessor = audioContext.createScriptProcessor(4096, 1, 1);
        micProcessor.onaudioprocess = (e) => {
            if (!ws || ws.readyState !== WebSocket.OPEN) return;

            const float32 = e.inputBuffer.getChannelData(0);
            // Convert float32 → int16
            const int16 = new Int16Array(float32.length);
            for (let i = 0; i < float32.length; i++) {
                const s = Math.max(-1, Math.min(1, float32[i]));
                int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
            }

            const b64 = arrayBufferToBase64(int16.buffer);
            ws.send(JSON.stringify({
                type: 'audio_chunk',
                data: b64,
            }));
        };

        micSource.connect(micProcessor);
        micProcessor.connect(audioContext.destination);

        micActive = true;
        micBtn.classList.add('active');
        micStatus.textContent = 'Listening...';
    } catch (err) {
        console.error('Mic error:', err);
        addSystemMessage('Microphone access denied.');
    }
}

function stopMic() {
    if (micProcessor) {
        micProcessor.disconnect();
        micProcessor = null;
    }
    if (micSource) {
        micSource.disconnect();
        micSource = null;
    }
    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
    if (micStream) {
        micStream.getTracks().forEach(t => t.stop());
        micStream = null;
    }
    micActive = false;
    micBtn.classList.remove('active');
    micStatus.textContent = 'Mic off';
}


// ═══════════════════════════════════════════════
// Audio — Speaker Playback
// ═══════════════════════════════════════════════

function getSpkContext() {
    if (!spkContext || spkContext.state === 'closed') {
        spkContext = new AudioContext({ sampleRate: 24000 });
    }
    return spkContext;
}

function playAudioChunk(b64Data) {
    const raw = base64ToArrayBuffer(b64Data);
    const int16 = new Int16Array(raw);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i++) {
        float32[i] = int16[i] / 32768.0;
    }

    spkQueue.push(float32);
    if (!spkPlaying) {
        drainSpkQueue();
    }
}

function drainSpkQueue() {
    if (spkQueue.length === 0) {
        spkPlaying = false;
        return;
    }
    spkPlaying = true;

    const ctx = getSpkContext();
    const samples = spkQueue.shift();
    const buffer = ctx.createBuffer(1, samples.length, 24000);
    buffer.copyToChannel(samples, 0);

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    source.onended = () => drainSpkQueue();
    source.start();
}

function clearAudioQueue() {
    spkQueue = [];
    spkPlaying = false;
}


// ═══════════════════════════════════════════════
// Chat
// ═══════════════════════════════════════════════

sendBtn.addEventListener('click', sendChatMessage);
chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendChatMessage();
    }
});

function sendChatMessage() {
    const text = chatInput.value.trim();
    if (!text) return;

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        if (!ws || ws.readyState === WebSocket.CLOSED) {
            console.log("[ui] WebSocket not open, attempting to connect before sending...");
            updateConnStatus(false, 'Connecting...');
            connectWebSocket();
            addSystemMessage('Connecting to AI... Please try again in a moment.');
        } else if (ws.readyState === WebSocket.CONNECTING) {
            addSystemMessage('Still connecting to AI... please wait a moment.');
        }
        return;
    }

    ws.send(JSON.stringify({
        type: 'text_message',
        text: text,
    }));

    addUserMessage(text);
    chatInput.value = '';
}

function addUserMessage(text) {
    const div = document.createElement('div');
    div.className = 'message user-msg';
    div.innerHTML = `<p>${escapeHtml(text)}</p>`;
    chatMessages.appendChild(div);
    scrollChat();
}

// Accumulator for streaming text
let aiMsgBuffer = '';
let aiMsgEl = null;

function addAIMessage(text) {
    // If there's an existing AI message being built, append to it
    if (aiMsgEl && aiMsgEl.parentElement) {
        aiMsgBuffer += text;
        aiMsgEl.innerHTML = `<p>${formatAIText(aiMsgBuffer)}</p>`;
    } else {
        aiMsgBuffer = text;
        aiMsgEl = document.createElement('div');
        aiMsgEl.className = 'message ai-msg';
        aiMsgEl.innerHTML = `<p>${formatAIText(aiMsgBuffer)}</p>`;
        chatMessages.appendChild(aiMsgEl);

        // After a pause, "finalize" this message so next text creates a new bubble
        clearTimeout(aiMsgEl._timer);
        aiMsgEl._timer = setTimeout(() => {
            aiMsgEl = null;
            aiMsgBuffer = '';
        }, 3000);
    }

    // Reset the timer on each new chunk
    if (aiMsgEl) {
        clearTimeout(aiMsgEl._timer);
        aiMsgEl._timer = setTimeout(() => {
            aiMsgEl = null;
            aiMsgBuffer = '';
        }, 3000);
    }

    scrollChat();
}

function addSystemMessage(text) {
    const div = document.createElement('div');
    div.className = 'message system-msg';
    div.innerHTML = `<p>${text}</p>`;
    chatMessages.appendChild(div);
    scrollChat();
}

function showTypingIndicator() {
    if (document.querySelector('.typing-indicator')) return;
    const div = document.createElement('div');
    div.className = 'typing-indicator';
    div.innerHTML = `
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
    `;
    chatMessages.appendChild(div);
    scrollChat();
}

function hideTypingIndicator() {
    const el = document.querySelector('.typing-indicator');
    if (el) el.remove();
}

function scrollChat() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

clearChatBtn.addEventListener('click', () => {
    chatMessages.innerHTML = '';
    addSystemMessage('Chat cleared.');
});


// ═══════════════════════════════════════════════
// Tool Results → Product Log
// ═══════════════════════════════════════════════

function handleToolResult(msg) {
    const { name, result } = msg;

    if (name === 'log_product' && result.status === 'saved') {
        // Add a chat notification
        const note = document.createElement('div');
        note.className = 'message tool-msg';
        note.innerHTML = `<p>Logged <strong>${escapeHtml(result.product)}</strong> at $${result.price.toFixed(2)} (${escapeHtml(result.store)})</p>`;
        chatMessages.appendChild(note);
        scrollChat();

        // Add to product log sidebar
        addProductCard(result);
        productLog.classList.add('open');
    }

    if (name === 'query_price_history' && result.found) {
        const note = document.createElement('div');
        note.className = 'message tool-msg';
        const cheapest = result.cheapest;
        if (cheapest) {
            note.innerHTML = `<p>Price check: cheapest was <strong>$${cheapest.price.toFixed(2)}</strong> at ${escapeHtml(cheapest.store)}</p>`;
        } else {
            note.innerHTML = `<p>No price history found.</p>`;
        }
        chatMessages.appendChild(note);
        scrollChat();
    }
}

function addProductCard(result) {
    const card = document.createElement('div');
    card.className = 'product-card';
    card.innerHTML = `
        <div class="product-name">${escapeHtml(result.product)}</div>
        <div class="product-price">$${result.price.toFixed(2)}</div>
        <div class="product-unit">$${result.unit_price.toFixed(3)}/${escapeHtml(result.unit)}</div>
        <div class="product-detail">
            ${escapeHtml(result.store)}${result.on_sale ? ' &middot; <span style="color:var(--accent-green)">ON SALE</span>' : ''}
        </div>
    `;
    productEntries.prepend(card);
}

closeLogBtn.addEventListener('click', () => {
    productLog.classList.remove('open');
});


// ═══════════════════════════════════════════════
// Response Mode Toggle
// ═══════════════════════════════════════════════

modeButtons.forEach(btn => {
    btn.addEventListener('click', () => {
        modeButtons.forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        responseMode = btn.dataset.mode;
        // Mode change takes effect on next session (can't change mid-session)
    });
});


// ═══════════════════════════════════════════════
// Utilities
// ═══════════════════════════════════════════════

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatAIText(text) {
    // Basic markdown-like formatting
    let html = escapeHtml(text);
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    html = html.replace(/\n/g, '<br>');
    return html;
}

function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
}

function base64ToArrayBuffer(base64) {
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
    }
    return bytes.buffer;
}
