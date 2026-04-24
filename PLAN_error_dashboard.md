# Plan: Error Handling & Admin Dashboard Reporting

## Overview
Build a centralized error capture, storage, and admin dashboard viewing system so the BMM-POS team can monitor application health, diagnose issues quickly, and respond to incidents without checking server logs.

---

## 1. Goals

| # | Goal | Priority |
|---|------|----------|
| 1 | Capture all unhandled exceptions with stack traces, request context, and user info | Must |
| 2 | Store errors in a dedicated database table with automatic cleanup (retention: 30 days) | Must |
| 3 | Admin dashboard page to view, filter, search, and acknowledge errors | Must |
| 4 | Real-time error count badge on admin nav bar | Should |
| 5 | Email/notification alert when error rate spikes (>10 errors in 5 min) | Nice |
| 6 | Client-side JS error reporting to same backend | Nice |

---

## 2. Database Schema

### Table: `error_logs`

```sql
CREATE TABLE IF NOT EXISTS error_logs (
    id SERIAL PRIMARY KEY,
    level VARCHAR(20) NOT NULL DEFAULT 'error',     -- error, warning, critical
    status VARCHAR(20) NOT NULL DEFAULT 'new',        -- new, acknowledged, resolved, ignored
    source VARCHAR(50) NOT NULL,                      -- api, frontend, background, startup
    endpoint VARCHAR(255),                            -- /api/v1/pos/sale
    method VARCHAR(10),                               -- POST, GET
    error_type VARCHAR(100) NOT NULL,                 -- ValueError, HTTPException, etc.
    message TEXT NOT NULL,
    stack_trace TEXT,
    request_body TEXT,                                -- sanitized (no passwords)
    user_id INTEGER,                                  -- vendor.id if authenticated
    user_email VARCHAR(200),
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_by INTEGER REFERENCES vendors(id),
    acknowledged_at TIMESTAMPTZ,
    notes TEXT                                        -- admin notes
);

CREATE INDEX idx_error_logs_status ON error_logs(status);
CREATE INDEX idx_error_logs_level ON error_logs(level);
CREATE INDEX idx_error_logs_source ON error_logs(source);
CREATE INDEX idx_error_logs_type ON error_logs(error_type);
CREATE INDEX idx_error_logs_occurred ON error_logs(occurred_at);
CREATE INDEX idx_error_logs_new ON error_logs(status, occurred_at) WHERE status = 'new';
```

### Migration
- Add to `scripts/migrate.py` with advisory lock + marker

---

## 3. Backend Architecture

### 3.1 Error Capture Service (`app/services/error_logger.py`)

```python
async def log_error(
    db: AsyncSession,
    exc: Exception,
    source: str = "api",
    request: Optional[Request] = None,
    user: Optional[Vendor] = None,
    level: str = "error",
) -> int:
    """Log an error to the database. Returns the error_log id."""
```

Responsibilities:
- Extract stack trace via `traceback.format_exc()`
- Sanitize request body (strip `password`, `token`, `card_transaction_id`, `square_payment_id` fields)
- Truncate stack trace to 20KB to prevent DB bloat
- Store user context if available
- Never raise — catches and prints its own failures

### 3.2 Global Exception Handler Enhancement

Current handler in `app/main.py`:
```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # ... existing logic ...
```

Enhancement:
- Add `log_error()` call inside the handler BEFORE returning the response
- Distinguish HTTPException (client errors, 4xx) from unexpected exceptions (5xx)
- Only log 5xx and unhandled exceptions to error_logs
- Log 4xx to error_logs with `level="warning"` only for unusual volumes

### 3.3 Background / Startup Error Capture

- Startup task failures → `log_error()` with `source="startup"`
- Background job errors → `log_error()` with `source="background"`

### 3.4 Admin API Endpoints (`app/routers/admin.py`)

```python
@router.get("/errors")
async def list_errors(
    status: Optional[str] = Query(None),      # new, acknowledged, resolved, ignored
    level: Optional[str] = Query(None),       # error, warning, critical
    source: Optional[str] = Query(None),      # api, frontend, startup, background
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),      # search in message, error_type, endpoint
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
)

@router.get("/errors/summary")
async def error_summary(
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
    current_user: Vendor = Depends(require_staff_feature("role_view_reports")),
)
# Returns: total, new_count, by_type, by_endpoint, trend (per hour)

@router.post("/errors/{error_id}/acknowledge")
async def acknowledge_error(...)

@router.post("/errors/{error_id}/resolve")
async def resolve_error(...)

@router.post("/errors/bulk-resolve")
async def bulk_resolve_errors(...)
```

### 3.5 Error Spike Detection (Optional)

```python
# In-memory counter (per-process, sufficient for single-instance Railway)
_error_spike_counter: dict[str, list[float]] = {}

async def _check_error_spike(error_type: str) -> bool:
    """Return True if >10 errors of this type in last 5 minutes."""
```

Trigger: send admin notification when spike detected.

---

## 4. Frontend Admin Dashboard

### New Page: `frontend/admin/errors.html`

**Layout:**
```
+----------------------------------------------------------+
|  Error Dashboard                              [Filter ▼]  |
+----------------------------------------------------------+
|  Stats Cards:                                             |
|  [ Total: 47 ]  [ New: 12 ]  [ Critical: 2 ]  [ 24h ▼ ]  |
+----------------------------------------------------------+
|  Chart: Errors over time (last 24h)                       |
+----------------------------------------------------------+
|  Filters: Status [All ▼] | Level [All ▼] | Source [All ▼] |
|  Search: [________________]  [Apply] [Clear]              |
+----------------------------------------------------------+
|  Errors Table                                             |
|  Time        | Type        | Endpoint     | Status | Actions |
|  03:42:12    | KeyError    | /pos/sale    | New    | [Ack] [View] |
|  ...                                                     |
+----------------------------------------------------------+
|  [Prev] Page 1 of 5 [Next]  [Bulk: Ack Selected]          |
+----------------------------------------------------------+
```

**Features:**
1. **Stats bar** — total, new, critical counts with auto-refresh every 30s
2. **Trend chart** — simple bar chart using Canvas or lightweight chart lib (no heavy deps)
3. **Filter bar** — status, level, source dropdowns + date range + text search
4. **Errors table** — sortable by time, type, endpoint
   - Each row: time, error type, endpoint, user (if known), status badge
   - Expandable row: full message + stack trace + request body
   - Actions: Acknowledge, Resolve, Ignore
5. **Bulk actions** — checkbox per row, bulk acknowledge/resolve
6. **Error detail modal** — full stack trace, request info, admin notes field
7. **Nav badge** — show `(<count>)` next to "Errors" in admin nav when new errors exist

**Styling:** Match existing dark editorial theme (`--bg`, `--gold`, etc.)

**Data fetching:**
```javascript
// Poll every 30 seconds
setInterval(fetchErrors, 30000);

// Real-time badge update
fetch('/api/v1/admin/errors/summary?hours=1')
  .then(r => r.json())
  .then(data => updateBadge(data.new_count));
```

---

## 5. Frontend JS Error Reporting (Optional)

Add to all admin pages:
```javascript
window.addEventListener('error', function(event) {
    fetch('/api/v1/client-errors', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            message: event.message,
            source: event.filename,
            line: event.lineno,
            stack: event.error?.stack,
            url: window.location.href,
            user_agent: navigator.userAgent,
        })
    }).catch(() => {}); // silent fail
});
```

Backend endpoint: `POST /api/v1/client-errors` (no auth, rate limited to 10/min per IP)

---

## 6. Implementation Order

| Phase | Task | Est. Time | File Changes |
|-------|------|-----------|--------------|
| 1 | Create `error_logs` table + migration | 15 min | `scripts/migrate.py`, `app/models/error_log.py` |
| 2 | Build `error_logger.py` service | 30 min | `app/services/error_logger.py` |
| 3 | Wire global exception handler | 15 min | `app/main.py` |
| 4 | Add admin API endpoints | 45 min | `app/routers/admin.py` |
| 5 | Build admin dashboard HTML/JS | 2-3 hrs | `frontend/admin/errors.html` |
| 6 | Add nav badge to admin layout | 15 min | `frontend/admin/index.html` |
| 7 | Add client-side JS reporter | 15 min | `frontend/static/js/error-reporter.js` |
| 8 | Test + deploy | 30 min | — |

**Total estimate:** ~5-6 hours

---

## 7. Acceptance Criteria

- [ ] Any unhandled 500 error is visible in the admin dashboard within 1 minute
- [ ] Stack traces are captured and viewable
- [ ] Admin can acknowledge/resolve errors
- [ ] Errors older than 30 days are automatically purged
- [ ] No passwords, tokens, or payment IDs appear in stored request bodies
- [ ] Dashboard shows error trend over last 24 hours
- [ ] Admin nav shows badge count of "new" errors
- [ ] Dashboard is mobile-responsive

---

## 8. Future Enhancements

| Feature | Description |
|---------|-------------|
| Slack/Discord webhook | Post critical errors to a channel |
| Error grouping | Group similar errors by stack trace signature |
| User impact analysis | Show which vendors/users were affected |
| Sentry integration | Export to external error tracking if needed |
| Performance profiling | Capture slow query logs alongside errors |
