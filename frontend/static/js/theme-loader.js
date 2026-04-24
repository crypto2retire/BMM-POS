/**
 * BMM-POS Theme Loader
 * Include this script on every page, BEFORE the closing </body> tag.
 * It reads the user's theme + font size preferences and applies them.
 */
(function() {
    'use strict';

    // ── 1. Apply cached preferences IMMEDIATELY to prevent flash ──
    var cachedTheme = localStorage.getItem('bmm_theme') || 'dark';
    var cachedFontSize = localStorage.getItem('bmm_font_size') || 'medium';
    document.documentElement.setAttribute('data-theme', cachedTheme);
    document.documentElement.setAttribute('data-font-size', cachedFontSize);

    // ── 2. Once DOM is ready, fetch real preferences from API ──
    var token = sessionStorage.getItem('bmm_token');
    if (token) {
        fetch('/api/v1/auth/me', {
            headers: { 'Authorization': 'Bearer ' + token }
        })
        .then(function(res) {
            if (!res.ok) return null;
            return res.json();
        })
        .then(function(data) {
            if (!data) return;
            var theme = data.theme_preference || 'dark';
            var fontSize = data.font_size_preference || 'medium';

            // Update DOM
            document.documentElement.setAttribute('data-theme', theme);
            document.documentElement.setAttribute('data-font-size', fontSize);

            // Update cache for next page load (prevents flash)
            localStorage.setItem('bmm_theme', theme);
            localStorage.setItem('bmm_font_size', fontSize);
        })
        .catch(function() {
            // Silently fail — cached values are already applied
        });
    }

    // ── 3. Global helper functions for settings pages ──
    window.bmmSetTheme = function(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem('bmm_theme', theme);
        return fetch('/api/v1/auth/me/preferences', {
            method: 'PUT',
            headers: {
                'Authorization': 'Bearer ' + sessionStorage.getItem('bmm_token'),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ theme_preference: theme }),
        });
    };

    window.bmmSetFontSize = function(size) {
        document.documentElement.setAttribute('data-font-size', size);
        localStorage.setItem('bmm_font_size', size);
        return fetch('/api/v1/auth/me/preferences', {
            method: 'PUT',
            headers: {
                'Authorization': 'Bearer ' + sessionStorage.getItem('bmm_token'),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ font_size_preference: size }),
        });
    };

    // ── 4. Client-side error reporter ──
    (function() {
        var ENDPOINT = '/api/v1/errors/report';
        var lastReport = 0;
        var DEBOUNCE_MS = 5000;

        function sendReport(payload) {
            try {
                var now = Date.now();
                if (now - lastReport < DEBOUNCE_MS) return;
                lastReport = now;
                var body = JSON.stringify(payload);
                if (navigator.sendBeacon) {
                    navigator.sendBeacon(ENDPOINT, new Blob([body], { type: 'application/json' }));
                } else {
                    fetch(ENDPOINT, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: body,
                        keepalive: true
                    }).catch(function(){});
                }
            } catch (e) {}
        }

        window.addEventListener('error', function(event) {
            sendReport({
                message: (event.message || 'Unknown error').substring(0, 500),
                source: 'frontend',
                error_type: 'JavaScriptError',
                stack_trace: event.error && event.error.stack ? event.error.stack.substring(0, 4000) : null,
                url: event.filename || window.location.href,
                user_agent: navigator.userAgent
            });
        });

        window.addEventListener('unhandledrejection', function(event) {
            var reason = event.reason;
            var message = typeof reason === 'string' ? reason : (reason && reason.message ? reason.message : 'Unhandled promise rejection');
            var stack = reason && reason.stack ? reason.stack.substring(0, 4000) : null;
            sendReport({
                message: message.substring(0, 500),
                source: 'frontend',
                error_type: 'UnhandledPromiseRejection',
                stack_trace: stack,
                url: window.location.href,
                user_agent: navigator.userAgent
            });
        });
    })();
})();
