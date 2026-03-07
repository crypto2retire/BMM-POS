let _token = null;

(function () {
    try {
        _token = sessionStorage.getItem("__bmm_token") || null;
    } catch (e) {}
})();

function _persistToken() {
    try {
        if (_token) {
            sessionStorage.setItem("__bmm_token", _token);
        } else {
            sessionStorage.removeItem("__bmm_token");
        }
    } catch (e) {}
}

function getToken() {
    return _token;
}

function clearToken() {
    _token = null;
    try {
        sessionStorage.removeItem("__bmm_token");
    } catch (e) {}
}

function parseToken() {
    if (!_token) return null;
    try {
        const parts = _token.split(".");
        if (parts.length !== 3) return null;
        const payload = parts[1];
        const padded = payload + "=".repeat((4 - payload.length % 4) % 4);
        return JSON.parse(atob(padded));
    } catch (e) {
        return null;
    }
}

async function apiLogin(email, password) {
    const body = new URLSearchParams({ username: email, password: password });
    const res = await fetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Login failed" }));
        throw new Error(err.detail || "Login failed");
    }

    const data = await res.json();
    _token = data.access_token;
    _persistToken();
    return parseToken();
}

async function apiFetch(method, url, body) {
    const headers = { "Content-Type": "application/json" };
    if (_token) headers["Authorization"] = `Bearer ${_token}`;

    const options = { method, headers };
    if (body !== undefined && body !== null) {
        options.body = JSON.stringify(body);
    }

    const res = await fetch(url, options);

    if (res.status === 401) {
        clearToken();
        window.location.href = "/vendor/login.html";
        return null;
    }

    if (res.status === 422) {
        const err = await res.json().catch(() => null);
        if (err && err.detail) {
            if (Array.isArray(err.detail)) {
                const msgs = err.detail.map(e => `${e.loc?.join(".")}: ${e.msg}`).join("; ");
                throw new Error(msgs);
            }
            throw new Error(err.detail);
        }
        throw new Error("Validation error");
    }

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
        throw new Error(err.detail || `HTTP ${res.status}`);
    }

    if (res.status === 204) return null;
    return res.json();
}

function apiGet(url) {
    return apiFetch("GET", url, undefined);
}

function apiPost(url, body) {
    return apiFetch("POST", url, body);
}

function apiPut(url, body) {
    return apiFetch("PUT", url, body);
}

function apiDelete(url) {
    return apiFetch("DELETE", url, undefined);
}

function requireAuth() {
    if (!getToken()) {
        window.location.href = "/vendor/login.html";
        return false;
    }
    return true;
}

function showAlert(containerId, message, type = "error") {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = `<div class="alert alert-${type}">${message}</div>`;
    setTimeout(() => { el.innerHTML = ""; }, 5000);
}
