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
})();
