(function () {
    'use strict';

    window.initPublicAssistant = function (pageContext) {
        if (document.getElementById('bmm-pub-assistant-btn')) return;

        var PAGE_CONTEXT = pageContext || '';

        var style = document.createElement('style');
        style.id = 'bmm-pub-assistant-styles';
        style.textContent = [
            '#bmm-pub-assistant-btn {',
            '    position:fixed; bottom:20px; right:16px;',
            '    width:56px; height:56px; border-radius:50%;',
            '    background:#38383B; border:1px solid #555558; color:#fff;',
            '    font-size:1.4rem; cursor:pointer; display:flex;',
            '    align-items:center; justify-content:center;',
            '    box-shadow:0 4px 12px rgba(0,0,0,0.5); z-index:200;',
            '    transition:background 0.15s, transform 0.15s; line-height:1;',
            '}',
            '#bmm-pub-assistant-btn:hover { background:#4e4e54; transform:scale(1.06); }',
            '#bmm-pub-assistant-btn.open { background:#555558; }',
            '#bmm-pub-assistant-panel {',
            '    position:fixed; z-index:300; background:#44444A;',
            '    border:1px solid #555558; box-shadow:0 8px 32px rgba(0,0,0,0.6);',
            '    display:flex; flex-direction:column; overflow:hidden;',
            '    bottom:0; right:0; width:100%; height:85vh; max-height:85vh;',
            '    border-radius:16px 16px 0 0;',
            '    transition:transform 0.3s ease, opacity 0.2s ease;',
            '}',
            '@media(min-width:600px){',
            '  #bmm-pub-assistant-panel {',
            '    bottom:88px; right:16px; width:380px; height:520px; max-height:520px;',
            '    border-radius:12px;',
            '  }',
            '}',
            '#bmm-pub-assistant-panel.hidden { display:none!important; }',
            '#bmm-pub-assistant-header {',
            '    display:flex; align-items:center; justify-content:space-between;',
            '    padding:0.75rem 1rem; background:#3a3a3e; border-bottom:1px solid #555558;',
            '    flex-shrink:0;',
            '}',
            '#bmm-pub-assistant-header h3 {',
            '    margin:0; font-size:0.95rem; color:#C9A96E;',
            '    font-family:"EB Garamond","Playfair Display",Georgia,serif;',
            '    font-weight:500;',
            '}',
            '#bmm-pub-assistant-header h3 span {',
            '    font-size:0.6rem; background:rgba(201,169,110,0.18);',
            '    color:#C9A96E; padding:1px 6px; border-radius:4px;',
            '    vertical-align:middle; margin-left:4px; letter-spacing:0.08em;',
            '}',
            '#bmm-pub-assistant-close {',
            '    background:none; border:none; color:#aaa; font-size:1.1rem;',
            '    cursor:pointer; padding:4px;',
            '}',
            '#bmm-pub-assistant-close:hover { color:#fff; }',
            '#bmm-pub-assistant-messages {',
            '    flex:1; overflow-y:auto; padding:1rem;',
            '    display:flex; flex-direction:column; gap:0.75rem;',
            '}',
            '.bmm-pub-msg {',
            '    max-width:85%; padding:0.6rem 0.85rem;',
            '    font-size:0.85rem; line-height:1.5;',
            '    font-family:"Roboto",Arial,sans-serif;',
            '}',
            '.bmm-pub-msg-user {',
            '    align-self:flex-end; background:#555558; color:#F0EDE8;',
            '    border-radius:12px 12px 2px 12px;',
            '}',
            '.bmm-pub-msg-assistant {',
            '    align-self:flex-start; background:#3a3a3e; color:#F0EDE8;',
            '    border-radius:12px 12px 12px 2px; border:1px solid #4a4a4d;',
            '}',
            '.bmm-pub-item-link, .bmm-pub-link {',
            '    color:#C9A96E; text-decoration:underline;',
            '    text-decoration-color:rgba(201,169,110,0.4);',
            '    cursor:pointer; transition:color 0.15s;',
            '}',
            '.bmm-pub-item-link:hover, .bmm-pub-link:hover {',
            '    color:#e0c080; text-decoration-color:rgba(224,192,128,0.6);',
            '}',
            '#bmm-pub-chips {',
            '    padding:0.5rem 1rem; display:flex; gap:0.4rem; flex-wrap:wrap;',
            '    border-top:1px solid #4a4a4d; flex-shrink:0;',
            '}',
            '.bmm-pub-chip {',
            '    background:#3a3a3e; color:#C5C3BE; border:1px solid #555558;',
            '    padding:0.3rem 0.7rem; font-size:0.75rem; cursor:pointer;',
            '    border-radius:999px; white-space:nowrap;',
            '    font-family:"Roboto",Arial,sans-serif;',
            '}',
            '.bmm-pub-chip:hover { background:#4e4e54; color:#fff; }',
            '#bmm-pub-input-row {',
            '    display:flex; gap:0.4rem; padding:0.5rem 0.75rem;',
            '    border-top:1px solid #555558; background:#3a3a3e; flex-shrink:0;',
            '}',
            '#bmm-pub-input {',
            '    flex:1; background:#38383B; border:1px solid #555558;',
            '    color:#F0EDE8; padding:0.5rem 0.75rem; font-size:0.85rem;',
            '    resize:none; outline:none; min-height:36px; max-height:80px;',
            '    border-radius:8px; font-family:"Roboto",Arial,sans-serif;',
            '}',
            '#bmm-pub-input::placeholder { color:#777; }',
            '#bmm-pub-send {',
            '    background:#A8A6A1; border:none; color:#1e1e20;',
            '    width:36px; height:36px; border-radius:8px; cursor:pointer;',
            '    font-size:1rem; display:flex; align-items:center; justify-content:center;',
            '}',
            '#bmm-pub-send:hover { background:#8e8c87; }',
            '.bmm-pub-typing { display:flex; gap:4px; align-self:flex-start; padding:0.6rem 0.85rem; }',
            '.bmm-pub-typing span {',
            '    width:7px; height:7px; border-radius:50%; background:#777;',
            '    animation:bmmPubBounce 1.2s infinite;',
            '}',
            '.bmm-pub-typing span:nth-child(2) { animation-delay:0.2s; }',
            '.bmm-pub-typing span:nth-child(3) { animation-delay:0.4s; }',
            '@keyframes bmmPubBounce {',
            '    0%,80%,100% { transform:translateY(0); }',
            '    40% { transform:translateY(-6px); }',
            '}',
        ].join('\n');
        document.head.appendChild(style);

        var btn = document.createElement('button');
        btn.id = 'bmm-pub-assistant-btn';
        btn.title = 'Chat with us';
        btn.textContent = '\uD83D\uDCAC';
        document.body.appendChild(btn);

        var panel = document.createElement('div');
        panel.id = 'bmm-pub-assistant-panel';
        panel.className = 'hidden';
        panel.innerHTML =
            '<div id="bmm-pub-assistant-header">' +
                '<div><h3>Bowenstreet Market <span>AI</span></h3></div>' +
                '<button id="bmm-pub-assistant-close" title="Close">\u2715</button>' +
            '</div>' +
            '<div id="bmm-pub-assistant-messages">' +
                '<div class="bmm-pub-msg bmm-pub-msg-assistant">Hi! Welcome to Bowenstreet Market \uD83D\uDC4B I can help you find items, explore vendor booths, check store hours, or browse upcoming classes. What are you looking for?</div>' +
            '</div>' +
            '<div id="bmm-pub-chips">' +
                '<button class="bmm-pub-chip" data-msg="What are your store hours?">Store hours</button>' +
                '<button class="bmm-pub-chip" data-msg="Show me what items you have">Browse items</button>' +
                '<button class="bmm-pub-chip" data-msg="Show me vendor booths">Vendor booths</button>' +
                '<button class="bmm-pub-chip" data-msg="What classes are coming up?">Classes</button>' +
            '</div>' +
            '<div id="bmm-pub-input-row">' +
                '<textarea id="bmm-pub-input" rows="1" placeholder="Ask me anything\u2026"></textarea>' +
                '<button id="bmm-pub-send" title="Send">\u2794</button>' +
            '</div>';
        document.body.appendChild(panel);

        var isOpen = false;

        function openPanel() {
            panel.classList.remove('hidden');
            isOpen = true;
            btn.classList.add('open');
            scrollToBottom();
        }

        function closePanel() {
            panel.classList.add('hidden');
            isOpen = false;
            btn.classList.remove('open');
        }

        function scrollToBottom() {
            var msgs = document.getElementById('bmm-pub-assistant-messages');
            setTimeout(function () { msgs.scrollTop = msgs.scrollHeight; }, 50);
        }

        function addMessage(text, type) {
            var msgs = document.getElementById('bmm-pub-assistant-messages');
            var el = document.createElement('div');
            el.className = 'bmm-pub-msg bmm-pub-msg-' + type;
            if (type === 'assistant') {
                el.innerHTML = formatReply(text);
            } else {
                el.textContent = text;
            }
            msgs.appendChild(el);
            scrollToBottom();
            return el;
        }

        function formatReply(text) {
            var d = document.createElement('div');
            d.textContent = text;
            var escaped = d.innerHTML;
            escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
            escaped = escaped.replace(/~~(.*?)~~/g, '<s>$1</s>');
            escaped = escaped.replace(/\[([^\]]+)\]\(\/shop\?item=(\d+)\)/g,
                '<a href="/shop/index.html?item=$2" class="bmm-pub-item-link" data-item-id="$2">$1</a>');
            escaped = escaped.replace(/\[([^\]]+)\]\((\/[^\)]+)\)/g,
                '<a href="$2" class="bmm-pub-link">$1</a>');
            escaped = escaped.replace(/\n- /g, '\n\u2022 ');
            escaped = escaped.replace(/\n/g, '<br>');
            return escaped;
        }

        function showTyping() {
            var msgs = document.getElementById('bmm-pub-assistant-messages');
            var el = document.createElement('div');
            el.id = 'bmm-pub-typing';
            el.className = 'bmm-pub-typing';
            el.innerHTML = '<span></span><span></span><span></span>';
            msgs.appendChild(el);
            scrollToBottom();
            return el;
        }

        function removeTyping() {
            var el = document.getElementById('bmm-pub-typing');
            if (el) el.remove();
        }

        async function sendMessage(text) {
            if (!text || !text.trim()) return;
            addMessage(text, 'user');
            var typing = showTyping();

            try {
                var resp = await fetch('/api/v1/storefront/assistant/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message: text,
                        page_context: PAGE_CONTEXT
                    })
                });
                var data = await resp.json();
                removeTyping();
                if (resp.ok) {
                    addMessage(data.reply, 'assistant');
                } else {
                    addMessage(data.detail || 'Sorry, something went wrong. Please try again.', 'assistant');
                }
            } catch (e) {
                removeTyping();
                addMessage('I\'m having trouble connecting. Please check your connection and try again.', 'assistant');
            }
        }

        btn.addEventListener('click', function () {
            if (isOpen) closePanel();
            else openPanel();
        });

        document.getElementById('bmm-pub-assistant-close').addEventListener('click', closePanel);

        document.getElementById('bmm-pub-send').addEventListener('click', function () {
            var input = document.getElementById('bmm-pub-input');
            var msg = input.value.trim();
            if (msg) {
                input.value = '';
                input.style.height = 'auto';
                sendMessage(msg);
            }
        });

        document.getElementById('bmm-pub-input').addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                document.getElementById('bmm-pub-send').click();
            }
        });

        document.getElementById('bmm-pub-input').addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 80) + 'px';
        });

        document.getElementById('bmm-pub-chips').addEventListener('click', function (e) {
            var chip = e.target.closest('.bmm-pub-chip');
            if (!chip) return;
            sendMessage(chip.dataset.msg);
        });

        document.addEventListener('click', function (e) {
            if (isOpen && !panel.contains(e.target) && e.target !== btn) closePanel();
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && isOpen) closePanel();
        });
    };
})();
