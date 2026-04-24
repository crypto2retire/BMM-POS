/* Admin nav badge — shows count of new errors next to Errors link */
(function() {
    const API_BASE = '/api/v1';
    function getToken() { return sessionStorage.getItem('bmm_token'); }

    async function updateBadge() {
        const token = getToken();
        if (!token) return;
        try {
            const r = await fetch(`${API_BASE}/admin/errors/summary`, {
                headers: { 'Authorization': 'Bearer ' + token }
            });
            if (!r.ok) return;
            const data = await r.json();
            const count = data.total_new || 0;
            const links = document.querySelectorAll('a[href="/admin/errors.html"]');
            links.forEach(link => {
                let badge = link.querySelector('.nav-badge');
                if (count > 0) {
                    if (!badge) {
                        badge = document.createElement('span');
                        badge.className = 'nav-badge';
                        badge.style.cssText = 'display:inline-block;margin-left:6px;padding:2px 7px;font-size:0.6rem;font-weight:700;background:var(--danger);color:#fff;border-radius:0;line-height:1;';
                        link.appendChild(badge);
                    }
                    badge.textContent = count > 99 ? '99+' : String(count);
                } else if (badge) {
                    badge.remove();
                }
            });
        } catch (e) {
            // silent fail
        }
    }

    updateBadge();
    setInterval(updateBadge, 30000);
})();
