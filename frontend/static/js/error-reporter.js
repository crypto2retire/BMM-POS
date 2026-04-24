/* Client-side error reporter — captures JS errors and sends to backend */
(function() {
    const ENDPOINT = '/api/v1/errors/report';
    let lastReport = 0;
    const DEBOUNCE_MS = 5000; // don't report same error more than once every 5s

    function sendReport(payload) {
        try {
            const now = Date.now();
            if (now - lastReport < DEBOUNCE_MS) return;
            lastReport = now;
            const body = JSON.stringify(payload);
            if (navigator.sendBeacon) {
                navigator.sendBeacon(ENDPOINT, new Blob([body], { type: 'application/json' }));
            } else {
                fetch(ENDPOINT, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: body,
                    keepalive: true
                }).catch(() => {});
            }
        } catch (e) {
            // Never break the app because of error reporting
        }
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
        const reason = event.reason;
        const message = typeof reason === 'string' ? reason : (reason && reason.message ? reason.message : 'Unhandled promise rejection');
        const stack = reason && reason.stack ? reason.stack.substring(0, 4000) : null;
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
