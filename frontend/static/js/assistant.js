(function () {
    'use strict';

    // ── Inject styles ──────────────────────────────────────────────────────
    const style = document.createElement('style');
    style.textContent = `
    #bmm-assistant-btn {
        position: fixed;
        bottom: 80px;
        right: 16px;
        width: 56px;
        height: 56px;
        border-radius: 50%;
        background: #38383B;
        border: 1px solid #555558;
        color: #fff;
        font-size: 1.4rem;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: 0 4px 12px rgba(0,0,0,0.5);
        z-index: 200;
        transition: background 0.15s, transform 0.15s;
        line-height: 1;
    }
    #bmm-assistant-btn:hover { background: #4e4e54; transform: scale(1.06); }
    #bmm-assistant-btn.open { background: #555558; }

    #bmm-assistant-panel {
        position: fixed;
        z-index: 300;
        background: #44444A;
        border: 1px solid #555558;
        box-shadow: 0 8px 32px rgba(0,0,0,0.6);
        display: flex;
        flex-direction: column;
        transition: transform 0.3s ease, opacity 0.3s ease;
    }
    #bmm-assistant-panel.hidden {
        pointer-events: none;
        opacity: 0;
    }

    /* Mobile: full-width slide-up from bottom */
    @media (max-width: 767px) {
        #bmm-assistant-panel {
            bottom: 0; left: 0; right: 0;
            height: 72vh;
            max-height: 600px;
            border-bottom: none;
            transform: translateY(100%);
        }
        #bmm-assistant-panel.hidden { transform: translateY(100%); }
        #bmm-assistant-panel.visible { transform: translateY(0); opacity: 1; }
    }
    /* Desktop: right-side panel */
    @media (min-width: 768px) {
        #bmm-assistant-panel {
            bottom: 80px; right: 80px;
            width: 380px;
            height: 520px;
            transform: translateY(16px) scale(0.97);
        }
        #bmm-assistant-panel.hidden { transform: translateY(16px) scale(0.97); }
        #bmm-assistant-panel.visible { transform: translateY(0) scale(1); opacity: 1; }
    }

    #bmm-assistant-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0.875rem 1rem;
        border-bottom: 1px solid #555558;
        flex-shrink: 0;
        background: #3A3A3E;
    }
    #bmm-assistant-header h3 {
        font-family: 'EB Garamond', Georgia, serif;
        font-size: 1rem;
        font-weight: 500;
        color: #fff;
        margin: 0;
    }
    #bmm-assistant-header span { font-size: 0.7rem; color: #A8A6A1; margin-left: 0.4rem; }
    #bmm-assistant-close {
        background: none; border: none; color: #A8A6A1;
        font-size: 1.1rem; cursor: pointer;
        min-height: 36px; min-width: 36px;
        display: flex; align-items: center; justify-content: center;
        border-radius: 50%;
        transition: background 0.15s;
    }
    #bmm-assistant-close:hover { background: rgba(255,255,255,0.08); color: #fff; }

    #bmm-assistant-messages {
        flex: 1;
        overflow-y: auto;
        padding: 1rem;
        display: flex;
        flex-direction: column;
        gap: 0.6rem;
        scroll-behavior: smooth;
    }
    .bmm-msg {
        max-width: 86%;
        padding: 0.6rem 0.85rem;
        font-size: 0.875rem;
        line-height: 1.45;
        word-wrap: break-word;
        white-space: pre-wrap;
    }
    .bmm-msg-user {
        align-self: flex-end;
        background: #555558;
        color: #fff;
        border-radius: 14px 14px 2px 14px;
    }
    .bmm-msg-assistant {
        align-self: flex-start;
        background: #3A3A3E;
        color: #e8e8e6;
        border-radius: 14px 14px 14px 2px;
    }
    .bmm-msg-image {
        align-self: flex-end;
        max-width: 140px;
    }
    .bmm-msg-image img {
        width: 100%; border-radius: 10px;
        display: block; border: 1px solid #555558;
    }
    .bmm-typing {
        align-self: flex-start;
        background: #3A3A3E;
        border-radius: 14px 14px 14px 2px;
        padding: 0.6rem 1rem;
        display: flex; gap: 4px; align-items: center;
    }
    .bmm-typing span {
        width: 7px; height: 7px;
        border-radius: 50%;
        background: #A8A6A1;
        animation: bmm-bounce 1.2s infinite;
    }
    .bmm-typing span:nth-child(2) { animation-delay: 0.2s; }
    .bmm-typing span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes bmm-bounce {
        0%, 60%, 100% { transform: translateY(0); }
        30% { transform: translateY(-5px); }
    }
    .bmm-msg-error {
        align-self: center;
        color: #e07070;
        font-size: 0.8rem;
        font-style: italic;
    }

    #bmm-assistant-input-row {
        display: flex;
        gap: 0.4rem;
        padding: 0.75rem;
        border-top: 1px solid #555558;
        background: #3A3A3E;
        flex-shrink: 0;
        align-items: flex-end;
    }
    #bmm-assistant-input {
        flex: 1;
        background: #44444A;
        border: 1px solid #555558;
        color: #fff;
        font-family: 'Roboto', sans-serif;
        font-size: 15px;
        padding: 10px 12px;
        resize: none;
        outline: none;
        max-height: 100px;
        line-height: 1.4;
        border-radius: 0;
    }
    #bmm-assistant-input:focus { border-color: #A8A6A1; }
    #bmm-assistant-input::placeholder { color: #A8A6A1; }
    #bmm-assistant-send, #bmm-assistant-photo {
        background: #A8A6A1;
        border: none;
        color: #fff;
        font-size: 1rem;
        cursor: pointer;
        min-height: 44px;
        min-width: 44px;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.15s;
        flex-shrink: 0;
    }
    #bmm-assistant-send:hover { background: #8e8c87; }
    #bmm-assistant-photo { background: #4e4e54; }
    #bmm-assistant-photo:hover { background: #555558; }
    #bmm-assistant-photo input { display: none; }
    `;
    document.head.appendChild(style);

    // ── Build DOM ──────────────────────────────────────────────────────────
    const btn = document.createElement('button');
    btn.id = 'bmm-assistant-btn';
    btn.title = 'Bowenstreet Assistant';
    btn.textContent = '💬';
    document.body.appendChild(btn);

    const panel = document.createElement('div');
    panel.id = 'bmm-assistant-panel';
    panel.className = 'hidden';
    panel.innerHTML = `
        <div id="bmm-assistant-header">
            <div>
                <h3>Bowenstreet Assistant <span>AI</span></h3>
            </div>
            <button id="bmm-assistant-close" title="Close">✕</button>
        </div>
        <div id="bmm-assistant-messages">
            <div class="bmm-msg bmm-msg-assistant">Hi! I'm your Bowenstreet assistant. I can help you add items, write descriptions, understand your sales, or answer any questions about the system. What can I help you with?</div>
        </div>
        <div id="bmm-assistant-input-row">
            <button id="bmm-assistant-photo" title="Send a photo">
                📷
                <input type="file" accept="image/*" capture="environment">
            </button>
            <textarea id="bmm-assistant-input" placeholder="Ask anything…" rows="1"></textarea>
            <button id="bmm-assistant-send" title="Send">➤</button>
        </div>
    `;
    document.body.appendChild(panel);

    // ── State ──────────────────────────────────────────────────────────────
    let isOpen = false;
    let isBusy = false;

    // ── Helpers ────────────────────────────────────────────────────────────
    function openPanel() {
        isOpen = true;
        panel.classList.remove('hidden');
        void panel.offsetWidth;
        panel.classList.add('visible');
        btn.classList.add('open');
        btn.textContent = '✕';
        document.getElementById('bmm-assistant-input').focus();
    }

    function closePanel() {
        isOpen = false;
        panel.classList.remove('visible');
        panel.classList.add('hidden');
        btn.classList.remove('open');
        btn.textContent = '💬';
    }

    function scrollToBottom() {
        const msgs = document.getElementById('bmm-assistant-messages');
        msgs.scrollTop = msgs.scrollHeight;
    }

    function addMessage(text, type) {
        const msgs = document.getElementById('bmm-assistant-messages');
        const el = document.createElement('div');
        el.className = `bmm-msg bmm-msg-${type}`;
        el.textContent = text;
        msgs.appendChild(el);
        scrollToBottom();
        return el;
    }

    function addImagePreview(dataUrl) {
        const msgs = document.getElementById('bmm-assistant-messages');
        const el = document.createElement('div');
        el.className = 'bmm-msg bmm-msg-image';
        el.innerHTML = `<img src="${dataUrl}" alt="Photo">`;
        msgs.appendChild(el);
        scrollToBottom();
    }

    function showTyping() {
        const msgs = document.getElementById('bmm-assistant-messages');
        const el = document.createElement('div');
        el.id = 'bmm-typing-indicator';
        el.className = 'bmm-typing';
        el.innerHTML = '<span></span><span></span><span></span>';
        msgs.appendChild(el);
        scrollToBottom();
        return el;
    }

    function removeTyping() {
        const el = document.getElementById('bmm-typing-indicator');
        if (el) el.remove();
    }

    async function sendMessage(message, imageBase64 = null, imageMimeType = null) {
        if (isBusy || !message.trim()) return;
        isBusy = true;

        const input = document.getElementById('bmm-assistant-input');
        input.value = '';
        input.style.height = 'auto';

        addMessage(message, 'user');
        const typing = showTyping();

        const token = sessionStorage.getItem('bmm_token');
        const body = { message };
        if (imageBase64) {
            body.image_base64 = imageBase64;
            body.image_mime_type = imageMimeType;
        }

        try {
            const res = await fetch('/api/v1/assistant/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + token,
                },
                body: JSON.stringify(body),
            });

            removeTyping();

            if (res.status === 503) {
                addMessage('Assistant is not available right now.', 'error');
            } else if (!res.ok) {
                addMessage('Assistant is not available right now.', 'error');
            } else {
                const data = await res.json();
                addMessage(data.reply, 'assistant');
            }
        } catch (e) {
            removeTyping();
            addMessage('Assistant is not available right now.', 'error');
        }

        isBusy = false;
    }

    // ── Auto-resize textarea ───────────────────────────────────────────────
    function autoResize(ta) {
        ta.style.height = 'auto';
        ta.style.height = Math.min(ta.scrollHeight, 100) + 'px';
    }

    // ── Event listeners ────────────────────────────────────────────────────
    btn.addEventListener('click', () => {
        if (isOpen) closePanel();
        else openPanel();
    });

    document.getElementById('bmm-assistant-close').addEventListener('click', closePanel);

    document.getElementById('bmm-assistant-send').addEventListener('click', () => {
        const input = document.getElementById('bmm-assistant-input');
        sendMessage(input.value.trim());
    });

    document.getElementById('bmm-assistant-input').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            const input = document.getElementById('bmm-assistant-input');
            sendMessage(input.value.trim());
        }
    });

    document.getElementById('bmm-assistant-input').addEventListener('input', function () {
        autoResize(this);
    });

    const photoInput = document.querySelector('#bmm-assistant-photo input');
    photoInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
            const dataUrl = ev.target.result;
            const base64 = dataUrl.split(',')[1];
            const mime = file.type;
            addImagePreview(dataUrl);
            sendMessage('What is this item? Suggest a name, category, price range, and description.', base64, mime);
        };
        reader.readAsDataURL(file);
        photoInput.value = '';
    });

    // Close on backdrop tap (mobile)
    document.addEventListener('click', (e) => {
        if (isOpen && !panel.contains(e.target) && e.target !== btn) {
            closePanel();
        }
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && isOpen) closePanel();
    });
})();
