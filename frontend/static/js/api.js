let _token = null;

(function () {
    try {
        _token = sessionStorage.getItem('bmm_token') || null;
    } catch (e) {
        _token = null;
    }
})();

function _persistToken() {
    try {
        if (_token) {
            sessionStorage.setItem('bmm_token', _token);
        } else {
            sessionStorage.removeItem('bmm_token');
        }
    } catch (e) {
        // Ignore storage errors
    }
}

function getToken() {
    return _token;
}

function clearToken() {
    _token = null;
    try {
        sessionStorage.removeItem('bmm_token');
        sessionStorage.removeItem('bmm_booth_mode');
        sessionStorage.removeItem('bmm_user');
    } catch (e) {}
    if (window.bmmAuth && typeof window.bmmAuth.resetCache === 'function') {
        window.bmmAuth.resetCache();
    }
}

function parseToken() {
    if (!_token) return null;
    try {
        const parts = _token.split('.');
        if (parts.length !== 3) return null;
        const payload = parts[1];
        const padded = payload + '='.repeat((4 - payload.length % 4) % 4);
        return JSON.parse(atob(padded));
    } catch (e) {
        return null;
    }
}

async function apiLogin(email, password) {
    const body = new URLSearchParams({ username: email, password: password });
    const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: body.toString(),
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Login failed' }));
        throw new Error(err.detail || 'Login failed');
    }

    const data = await res.json();
    _token = data.access_token;
    _persistToken();
    return parseToken();
}

async function apiFetch(method, url, body) {
    const token = getToken();
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = 'Bearer ' + token;

    const options = { method, headers };
    if (body !== undefined && body !== null) {
        options.body = JSON.stringify(body);
    }

    let res;
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000);
        options.signal = controller.signal;
        res = await fetch(url, options);
        clearTimeout(timeoutId);
    } catch (err) {
        if (err.name === 'AbortError') {
            throw new Error('Request timed out. Check your connection and try again.');
        }
        showOfflineBanner();
        throw new Error('Connection lost. Check your internet and try again.');
    }

    hideOfflineBanner();

    if (res.status === 401) {
        clearToken();
        window.location.href = '/vendor/login.html';
        return null;
    }

    if (res.status === 422) {
        const err = await res.json().catch(() => null);
        if (err && err.detail) {
            if (Array.isArray(err.detail)) {
                const msgs = err.detail.map(e => `${e.loc?.join('.')}: ${e.msg}`).join('; ');
                throw new Error(msgs);
            }
            throw new Error(err.detail);
        }
        throw new Error('Validation error');
    }

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `HTTP ${res.status}`);
    }

    if (res.status === 204) return null;
    return res.json();
}

function apiGet(url) {
    return apiFetch('GET', url, undefined);
}

function apiPost(url, body) {
    return apiFetch('POST', url, body);
}

function apiPut(url, body) {
    return apiFetch('PUT', url, body);
}

function apiDelete(url) {
    return apiFetch('DELETE', url, undefined);
}

async function apiFetchText(url) {
    const token = getToken();
    const headers = {};
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const res = await fetch(url, { method: 'GET', headers });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.text();
}

async function apiChat(message, imageBase64 = null, imageMimeType = null) {
    const body = { message };
    if (imageBase64) {
        body.image_base64 = imageBase64;
        body.image_mime_type = imageMimeType;
    }
    return await apiPost('/api/v1/assistant/chat', body);
}

function requireAuth() {
    const token = getToken();
    if (!token) {
        window.location.href = '/vendor/login.html';
        return false;
    }
    _token = token;
    return true;
}

function showAlert(containerId, message, type) {
    type = type || 'error';
    const el = document.getElementById(containerId);
    if (!el) return;
    var div = document.createElement('div');
    div.className = 'alert alert-' + (['error','success','info','warning'].indexOf(type) >= 0 ? type : 'error');
    div.setAttribute('aria-live', 'polite');
    div.setAttribute('role', type === 'error' ? 'alert' : 'status');
    div.textContent = message;
    el.innerHTML = '';
    el.appendChild(div);
    setTimeout(function () { el.innerHTML = ''; }, 5000);
}

function bmmDateValue(value) {
    if (!value) return null;
    if (value instanceof Date) {
        return isNaN(value.getTime()) ? null : value;
    }
    const date = new Date(value);
    return isNaN(date.getTime()) ? null : date;
}

function bmmFormatDate(value, options, locale) {
    const date = bmmDateValue(value);
    if (!date) return '';
    return date.toLocaleDateString(locale || undefined, options || undefined);
}

function bmmFormatTime(value, options, locale) {
    const date = bmmDateValue(value);
    if (!date) return '';
    return date.toLocaleTimeString(locale || undefined, options || undefined);
}

function bmmFormatDateTime(value, dateOptions, timeOptions, locale) {
    const date = bmmDateValue(value);
    if (!date) return '';
    const datePart = bmmFormatDate(date, dateOptions, locale);
    const timePart = bmmFormatTime(date, timeOptions, locale);
    return [datePart, timePart].filter(Boolean).join(' ');
}

window.bmmFormatDate = bmmFormatDate;
window.bmmFormatTime = bmmFormatTime;
window.bmmFormatDateTime = bmmFormatDateTime;

// ── Network status banner ────────────────────────────────────────
function showOfflineBanner() {
    if (document.getElementById('bmm-offline-banner')) return;
    var banner = document.createElement('div');
    banner.id = 'bmm-offline-banner';
    banner.setAttribute('role', 'alert');
    banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:10000;background:var(--danger,#e74c3c);color:#fff;text-align:center;padding:0.6rem 1rem;font-family:Roboto,sans-serif;font-size:0.85rem;font-weight:500;display:flex;align-items:center;justify-content:center;gap:0.75rem;';
    banner.innerHTML = '<span>⚠️ Connection lost</span><button onclick="location.reload()" style="background:rgba(255,255,255,0.2);border:1px solid rgba(255,255,255,0.4);color:#fff;padding:0.3rem 0.8rem;cursor:pointer;font-family:Roboto,sans-serif;font-size:0.8rem;font-weight:600">Retry</button>';
    document.body.appendChild(banner);
}

function hideOfflineBanner() {
    var el = document.getElementById('bmm-offline-banner');
    if (el) el.remove();
}

window.addEventListener('online', function() { hideOfflineBanner(); });
window.addEventListener('offline', function() { showOfflineBanner(); });

// ── Modal focus trapping ─────────────────────────────────────────
function trapFocus(modalEl) {
    if (!modalEl) return;
    var focusable = modalEl.querySelectorAll(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'
    );
    if (!focusable.length) return;
    var first = focusable[0];
    var last = focusable[focusable.length - 1];

    function handler(e) {
        if (e.key !== 'Tab') return;
        if (e.shiftKey) {
            if (document.activeElement === first) { e.preventDefault(); last.focus(); }
        } else {
            if (document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
    }
    modalEl.addEventListener('keydown', handler);
    first.focus();
    return function() { modalEl.removeEventListener('keydown', handler); };
}

// Auto-trap focus on elements with aria-modal="true" or class pos-modal-overlay
var _focusTrapObserver = new MutationObserver(function(mutations) {
    mutations.forEach(function(m) {
        m.addedNodes.forEach(function(node) {
            if (node.nodeType !== 1) return;
            var modal = null;
            if (node.getAttribute && node.getAttribute('aria-modal') === 'true') {
                modal = node;
            } else if (node.classList && (node.classList.contains('pos-modal-overlay') || node.classList.contains('modal-overlay'))) {
                var inner = node.querySelector('[aria-modal="true"], .pos-modal, .modal-box');
                if (inner) modal = inner;
            }
            if (modal) {
                setTimeout(function() { trapFocus(modal); }, 50);
            }
        });
    });
});
if (document.body) {
    _focusTrapObserver.observe(document.body, { childList: true, subtree: true });
} else {
    document.addEventListener('DOMContentLoaded', function() {
        _focusTrapObserver.observe(document.body, { childList: true, subtree: true });
    });
}

window.trapFocus = trapFocus;

// ── Loading skeleton helpers ───────────────────────────────────────
function skeletonRows(count, cls) {
    var html = '';
    for (var i = 0; i < count; i++) html += '<div class="skeleton skeleton-row"></div>';
    return html;
}
function skeletonCards(count, cls) {
    var html = '<div class="skeleton-grid">';
    for (var i = 0; i < count; i++) html += '<div class="skeleton skeleton-card"></div>';
    html += '</div>';
    return html;
}
function skeletonStats() {
    return '<div class="skeleton-stats">' +
        '<div class="skeleton skeleton-card"></div>'.repeat(4) +
        '</div>';
}
window.skeletonRows = skeletonRows;
window.skeletonCards = skeletonCards;
window.skeletonStats = skeletonStats;

// ── Skip to content link (accessibility) ──────────────────────────
(function() {
    var skip = document.createElement('a');
    skip.href = '#main-content';
    skip.className = 'skip-link';
    skip.textContent = 'Skip to content';
    skip.style.cssText = 'position:fixed;top:-100%;left:50%;transform:translateX(-50%);z-index:99999;background:var(--gold,#C9A96E);color:#38383B;padding:0.6rem 1.5rem;font-family:Roboto,sans-serif;font-size:0.9rem;font-weight:600;text-decoration:none;transition:top 0.15s;';
    skip.addEventListener('focus', function() { skip.style.top = '0'; });
    skip.addEventListener('blur', function() { skip.style.top = '-100%'; });
    document.body.prepend(skip);
})();
