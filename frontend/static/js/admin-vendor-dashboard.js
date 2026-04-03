/**
 * Consolidated admin vendor hub: overview API, accordion, rent / edit / payouts modals.
 * Loaded from admin/index.html after api.js.
 */
(function () {
    var _vendorData = null;
    var _filtered = [];
    var _expandedId = null;
    var _payVendorId = null;
    var _editVendorId = null;
    var _terminalPollInterval = null;
    var _vhPageSize = 10;
    var _vhCurrentPage = 1;

    function fmt(v) {
        var n = parseFloat(v);
        if (isNaN(n)) n = 0;
        return '$' + n.toFixed(2);
    }

    /** Coerce API numbers (may be strings) for comparisons and styling */
    function num(v) {
        var n = parseFloat(v);
        return isNaN(n) ? 0 : n;
    }

    function displayBalance(v) {
        if (v == null) return 0;
        if (v.balance != null && v.balance !== '') {
            return num(v.balance);
        }
        if (Object.prototype.hasOwnProperty.call(v, 'sales_balance')) {
            return num(v.sales_balance);
        }
        return 0;
    }

    function esc(s) {
        if (s == null || s === undefined) return '';
        var d = document.createElement('div');
        d.textContent = s;
        return d.innerHTML;
    }

    /** Set from admin/index.html; admin and cashiers get full vendor hub actions */
    function isVendorHubAdmin() {
        return window._adminDashboardIsAdmin !== false;
    }

    function rentBadge(status) {
        var map = {
            current: '<span class="vh-badge vh-badge--ok">CURRENT</span>',
            due: '<span class="vh-badge vh-badge--warn">DUE</span>',
            overdue: '<span class="vh-badge vh-badge--bad">OVERDUE</span>',
            none: '<span class="vh-badge vh-badge--muted">NONE</span>',
        };
        return map[status] || esc(status);
    }

    window.loadVendorOverview = async function loadVendorOverview() {
        try {
            var data = await apiGet('/api/v1/admin/vendor-overview');
            window._vendorData = data;
            _vendorData = data;
            _filtered = data.vendors || [];
            var el = document.getElementById('vendor-period-label');
            if (el) el.textContent = 'Vendor operations — ' + data.period;

            renderVendorStats(data.totals, data.already_processed);
            _vhCurrentPage = 1;
            renderVendorRows();
            _expandedId = null;
        } catch (e) {
            showAlert('alert-container', 'Vendor overview: ' + (e.message || e), 'error');
            var tb = document.getElementById('vendor-hub-tbody');
            if (tb) tb.innerHTML = '<tr><td colspan="5" class="empty-state">Failed to load vendors.</td></tr>';
        }
    };

    function renderVendorStats(totals, alreadyProcessed) {
        var gross = document.getElementById('vh-stat-gross');
        var coll = document.getElementById('vh-stat-rent-coll');
        var due = document.getElementById('vh-stat-rent-due');
        var net = document.getElementById('vh-stat-net');
        var short = document.getElementById('vh-stat-short');
        var vc = document.getElementById('vh-stat-count');
        var badge = document.getElementById('vh-processed-badge');
        var btn = document.getElementById('vh-process-btn');
        if (gross) gross.textContent = fmt(totals.gross_sales);
        if (coll) coll.textContent = fmt(totals.rent_collected);
        if (due) due.textContent = fmt(totals.rent_due);
        if (net) net.textContent = fmt(totals.net_payouts);
        if (short) short.textContent = fmt(totals.shortfalls);
        if (vc) vc.textContent = String(totals.vendor_count || 0);
        if (badge) {
            badge.style.display = alreadyProcessed ? 'inline-block' : 'none';
            if (alreadyProcessed) badge.textContent = 'Already processed this month';
        }
        if (btn) {
            btn.disabled = !!alreadyProcessed;
            btn.textContent = alreadyProcessed ? 'Already Processed' : 'Process Payouts';
        }
    }

    function updateVendorHubPagination(total, start, count, pages) {
        var info = document.getElementById('vendor-hub-page-info');
        var prev = document.getElementById('vendor-hub-prev');
        var next = document.getElementById('vendor-hub-next');
        if (info) {
            if (total === 0) {
                info.textContent = '';
            } else {
                info.textContent =
                    'Showing ' + (start + 1) + '–' + (start + count) + ' of ' + total;
            }
        }
        if (prev) {
            prev.disabled = total === 0 || _vhCurrentPage <= 1;
        }
        if (next) {
            next.disabled = total === 0 || _vhCurrentPage >= pages;
        }
    }

    window.vendorHubPage = function vendorHubPage(delta) {
        var total = (_filtered || []).length;
        var pages = Math.max(1, Math.ceil(total / _vhPageSize));
        _vhCurrentPage += delta;
        if (_vhCurrentPage < 1) _vhCurrentPage = 1;
        if (_vhCurrentPage > pages) _vhCurrentPage = pages;
        _expandedId = null;
        document.querySelectorAll('.vendor-detail-tr').forEach(function (r) {
            r.remove();
        });
        renderVendorRows();
    };

    function renderVendorRows() {
        var vendorsFull = _filtered || [];
        var tbody = document.getElementById('vendor-hub-tbody');
        var mob = document.getElementById('vendor-hub-cards-mobile');
        if (!tbody) return;

        document.querySelectorAll('.vendor-detail-tr').forEach(function (r) {
            r.remove();
        });

        var total = vendorsFull.length;
        var pages = Math.max(1, Math.ceil(total / _vhPageSize));
        if (_vhCurrentPage > pages) _vhCurrentPage = pages;
        if (_vhCurrentPage < 1) _vhCurrentPage = 1;
        var start = (_vhCurrentPage - 1) * _vhPageSize;
        var vendors = vendorsFull.slice(start, start + _vhPageSize);

        if (!vendors.length) {
            tbody.innerHTML =
                '<tr><td colspan="5" class="empty-state">' +
                (total === 0 ? 'No vendors found.' : 'No vendors on this page.') +
                '</td></tr>';
            if (mob) mob.innerHTML = '<div class="empty-state">No vendors.</div>';
            updateVendorHubPagination(total, start, 0, pages);
            return;
        }

        updateVendorHubPagination(total, start, vendors.length, pages);

        tbody.innerHTML = vendors
            .map(function (v) {
                var flag = v.rent_flagged ? '<span title="Flagged">🚩</span> ' : '';
                return (
                    '<tr class="vh-row" data-vid="' +
                    v.id +
                    '" onclick="window.toggleVendorAccordion(' +
                    v.id +
                    ')">' +
                    '<td><strong>' +
                    flag +
                    esc(v.name) +
                    '</strong></td>' +
                    '<td>' +
                    esc(v.booth_number) +
                    '</td>' +
                    '<td>' +
                    '<div style="font-size:0.75rem;color:var(--text-light)">Sales: ' +
                    fmt(num(v.sales_balance)) +
                    '</div>' +
                    '<div style="font-size:0.75rem;color:var(--text-light)">Rent: <span style="color:' +
                    (num(v.rent_balance) < 0 ? 'var(--danger)' : 'var(--text-light)') +
                    '">' +
                    fmt(num(v.rent_balance)) +
                    '</span></div>' +
                    '<div style="font-weight:600;color:' +
                    (displayBalance(v) < 0
                        ? 'var(--danger)'
                        : displayBalance(v) > 0
                          ? 'var(--success-light)'
                          : 'var(--text-light)') +
                    '">' +
                    fmt(displayBalance(v)) +
                    '</div>' +
                    '</td>' +
                    '<td>' +
                    rentBadge(v.rent_status) +
                    '</td>' +
                    '<td style="font-size:0.82rem">' +
                    esc(v.payout_method) +
                    ' <span class="vh-chevron">▼</span></td>' +
                    '</tr>'
                );
            })
            .join('');

        if (mob) {
            mob.innerHTML = vendors
                .map(function (v) {
                    return (
                        '<div class="vh-mob-card" onclick="window.toggleVendorAccordion(' +
                        v.id +
                        ')">' +
                        '<div class="vh-mob-top"><div><div class="vh-mob-name">' +
                        (v.rent_flagged ? '🚩 ' : '') +
                        esc(v.name) +
                        '</div>' +
                        '<div class="vh-mob-sub">Booth ' +
                        esc(v.booth_number) +
                        '</div></div>' +
                        '<div class="vh-mob-bal">' +
                        '<div style="font-size:0.7rem;color:var(--text-light)">Sales: ' +
                        fmt(num(v.sales_balance)) +
                        '</div>' +
                        '<div style="font-size:0.7rem;color:' +
                        (num(v.rent_balance) < 0 ? 'var(--danger)' : 'var(--text-light)') +
                        '">Rent: ' +
                        fmt(num(v.rent_balance)) +
                        '</div>' +
                        '<div style="font-weight:600;color:' +
                        (displayBalance(v) < 0
                            ? 'var(--danger)'
                            : displayBalance(v) > 0
                              ? 'var(--success-light)'
                              : 'var(--text-light)') +
                        '">' +
                        fmt(displayBalance(v)) +
                        '</div>' +
                        '</div></div>' +
                        '<div style="margin-top:0.5rem">' +
                        rentBadge(v.rent_status) +
                        '</div></div>'
                    );
                })
                .join('');
        }
    }

    window.filterVendorHub = function filterVendorHub() {
        var q = (document.getElementById('vendor-search-input') || {}).value;
        q = (q || '').trim().toLowerCase();
        if (!_vendorData || !_vendorData.vendors) return;
        if (!q) {
            _filtered = _vendorData.vendors;
        } else {
            _filtered = _vendorData.vendors.filter(function (v) {
                return (
                    (v.name && v.name.toLowerCase().includes(q)) ||
                    (v.email && v.email.toLowerCase().includes(q)) ||
                    String(v.booth_number || '')
                        .toLowerCase()
                        .includes(q)
                );
            });
        }
        _expandedId = null;
        _vhCurrentPage = 1;
        document.querySelectorAll('.vendor-detail-tr').forEach(function (r) {
            r.remove();
        });
        renderVendorRows();
    };

    function findVendor(id) {
        var list = _vendorData && _vendorData.vendors ? _vendorData.vendors : [];
        for (var i = 0; i < list.length; i++) {
            if (list[i].id === id) return list[i];
        }
        var directory = window._adminAccountDirectory || [];
        for (var j = 0; j < directory.length; j++) {
            if (directory[j].id === id) return directory[j];
        }
        return null;
    }

    window.toggleVendorAccordion = function toggleVendorAccordion(vendorId) {
        var tbody = document.getElementById('vendor-hub-tbody');
        if (!tbody) return;

        document.querySelectorAll('.vendor-detail-tr').forEach(function (r) {
            r.remove();
        });

        if (_expandedId === vendorId) {
            _expandedId = null;
            return;
        }

        _expandedId = vendorId;
        var v = findVendor(vendorId);
        if (!v) return;

        var row = tbody.querySelector('tr[data-vid="' + vendorId + '"]');
        if (!row) return;

        var tr = document.createElement('tr');
        tr.className = 'vendor-detail-tr';
        tr.innerHTML =
            '<td colspan="5" style="padding:0;background:var(--bg);border:1px solid var(--border)">' +
            buildDetailHtml(v) +
            '</td>';
        row.parentNode.insertBefore(tr, row.nextSibling);

        // Lazy-load sales history for this vendor
        loadVendorSalesHistory(vendorId);
    };

    async function loadVendorSalesHistory(vendorId) {
        var container = document.getElementById('vh-sales-' + vendorId);
        if (!container) return;
        try {
            var sales = await apiGet('/api/v1/sales/?vendor_id=' + vendorId + '&limit=50');
            if (!sales || !sales.length) {
                container.innerHTML = '<p style="color:var(--text-light);font-style:italic">No sales recorded yet.</p>';
                return;
            }
            var html = '<div style="max-height:300px;overflow-y:auto;scrollbar-width:thin;scrollbar-color:var(--border) transparent">' +
                '<table style="width:100%;border-collapse:collapse">' +
                '<thead><tr>' +
                '<th style="text-align:left;font-size:0.62rem;color:var(--text-light);text-transform:uppercase;letter-spacing:0.1em;padding:0.4rem 0.5rem;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg)">Date</th>' +
                '<th style="text-align:left;font-size:0.62rem;color:var(--text-light);text-transform:uppercase;letter-spacing:0.1em;padding:0.4rem 0.5rem;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg)">Items</th>' +
                '<th style="text-align:right;font-size:0.62rem;color:var(--text-light);text-transform:uppercase;letter-spacing:0.1em;padding:0.4rem 0.5rem;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg)">Total</th>' +
                '<th style="text-align:left;font-size:0.62rem;color:var(--text-light);text-transform:uppercase;letter-spacing:0.1em;padding:0.4rem 0.5rem;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--bg)">Method</th>' +
                '</tr></thead><tbody>';

            sales.forEach(function(sale) {
                var saleDate = '—';
                if (sale.created_at) {
                    var d = new Date(sale.created_at);
                    var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                    saleDate = months[d.getMonth()] + ' ' + d.getDate() + ', ' + d.getFullYear();
                }
                // API returns line_items (not items); lines use unit_price / line_total
                var lines = sale.line_items || sale.items || [];
                var vid = Number(vendorId);
                var vendorItems = lines.filter(function(si) {
                    return Number(si.vendor_id) === vid;
                });
                var itemNames = vendorItems.map(function(si) {
                    return (si.item_name || si.name || 'Item') + (si.quantity > 1 ? ' x' + si.quantity : '');
                }).join(', ') || '—';
                var vendorTotal = vendorItems.reduce(function(sum, si) {
                    if (si.line_total != null && si.line_total !== '') {
                        return sum + num(si.line_total);
                    }
                    var up = si.unit_price != null ? si.unit_price : si.price;
                    return sum + num(up) * (si.quantity || 1);
                }, 0);

                html += '<tr style="border-bottom:1px solid var(--border)">' +
                    '<td style="padding:0.4rem 0.5rem;font-size:0.82rem;color:var(--text);white-space:nowrap">' + saleDate + '</td>' +
                    '<td style="padding:0.4rem 0.5rem;font-size:0.82rem;color:var(--text);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + itemNames.replace(/"/g, '&quot;') + '">' + itemNames + '</td>' +
                    '<td style="padding:0.4rem 0.5rem;font-size:0.82rem;color:var(--gold);text-align:right;font-weight:600">$' + vendorTotal.toFixed(2) + '</td>' +
                    '<td style="padding:0.4rem 0.5rem;font-size:0.82rem;color:var(--text-light)">' + (sale.payment_method || '—') + '</td>' +
                    '</tr>';
            });

            html += '</tbody></table></div>';
            container.innerHTML = html;
        } catch (e) {
            container.innerHTML = '<p style="color:var(--danger)">Failed to load sales: ' + (e.message || e) + '</p>';
        }
    }

    function buildDetailHtml(v) {
        var pp = v.payout_preview || {};
        var shortHtml =
            pp.shortfall > 0
                ? '<p style="color:var(--danger);margin:0.35rem 0 0;font-size:0.9rem">Shortfall: ' +
                  fmt(pp.shortfall) +
                  '</p>'
                : '';

        return (
            '<div class="vh-detail-grid">' +
            '<div class="vh-detail-col">' +
            '<h4 class="vh-detail-h">Balance &amp; Payout</h4>' +
            '<div style="margin:0.5rem 0">' +
            '<div style="font-size:0.85rem;color:var(--text-light);margin-bottom:0.25rem">Sales Balance: <span style="color:var(--gold)">' +
            fmt(num(v.sales_balance)) +
            '</span></div>' +
            '<div style="font-size:0.85rem;color:var(--text-light);margin-bottom:0.25rem">Rent Balance: <span style="color:' +
            (num(v.rent_balance) < 0 ? 'var(--danger)' : 'var(--gold)') +
            '">' +
            fmt(num(v.rent_balance)) +
            '</span></div>' +
            '<p style="font-size:1.75rem;font-family:EB Garamond,serif;color:' +
            (displayBalance(v) < 0
                ? 'var(--danger)'
                : displayBalance(v) > 0
                  ? 'var(--success-light)'
                  : 'var(--text-light)') +
            ';margin:0.25rem 0">Current Sales Balance: ' +
            fmt(displayBalance(v)) +
            '</p></div>' +
            '<div style="font-size:0.82rem;color:var(--text-light);line-height:1.5">' +
            'Gross: ' +
            fmt(pp.gross) +
            '<br>Rent deduction: <span style="color:var(--danger)">-' +
            fmt(pp.rent_deducted) +
            '</span><br>' +
            '<strong style="color:var(--success-light)">Net: ' +
            fmt(pp.net) +
            '</strong>' +
            '</div>' +
            shortHtml +
            '<p style="margin:0.75rem 0 0;font-size:0.8rem">Method: ' +
            esc(v.payout_method) +
            '</p>' +
            (isVendorHubAdmin()
                ? '<div style="margin-top:0.75rem;display:flex;flex-wrap:wrap;gap:0.5rem">' +
                  '<button type="button" class="btn btn-sm" style="background:var(--gold);color:var(--charcoal-deep)" onclick="event.stopPropagation();window.openAdjustFromHub(' +
                  v.id +
                  ')">Adjust Balance</button>' +
                  '<button type="button" class="btn btn-sm" onclick="event.stopPropagation();window.openHistoryFromHub(' +
                  v.id +
                  ')">Balance History</button>' +
                  '</div>'
                : '') +
            '</div>' +

            '<div class="vh-detail-col">' +
            '<h4 class="vh-detail-h">Rent</h4>' +
            '<p style="font-size:0.88rem">Monthly: ' +
            fmt(v.monthly_rent) +
            '/mo</p>' +
            '<p style="font-size:0.85rem">' +
            (v.rent_paid
                ? '<span class="vh-badge vh-badge--ok">PAID</span> ' +
                  esc(v.rent_paid_method || '') +
                  ' · ' +
                  esc(v.rent_paid_date || '')
                : rentBadge(v.rent_status)) +
            '</p>' +
            '<p style="font-size:0.8rem;color:var(--text-light)">Last payment: ' +
            esc(v.last_rent_date || '—') +
            '</p>' +
            (isVendorHubAdmin()
                ? '<div style="margin-top:0.75rem;display:flex;flex-wrap:wrap;gap:0.5rem">' +
                  '<button type="button" class="btn btn-sm" style="background:color-mix(in srgb,var(--success-light) 20%,transparent);color:var(--success-light);border:1px solid color-mix(in srgb,var(--success-light) 35%,transparent)" onclick="event.stopPropagation();window.openRentModalHub(' +
                  v.id +
                  ')">Record Rent Payment</button>' +
                  '<button type="button" class="btn btn-sm" onclick="event.stopPropagation();window.toggleFlagHub(' +
                  v.id +
                  ',this)">' +
                  (v.rent_flagged ? '🚩 Unflag' : '⚑ Flag') +
                  '</button>' +
                  '</div>'
                : '') +
            '</div>' +

            '<div class="vh-detail-col">' +
            '<h4 class="vh-detail-h">Vendor</h4>' +
            '<p style="font-size:0.8rem;color:var(--text-light)">' +
            esc(v.email) +
            '<br>' +
            esc(v.phone || '—') +
            '</p>' +
            '<div style="margin-top:0.75rem;display:flex;flex-wrap:wrap;gap:0.5rem;align-items:center">' +
            (isVendorHubAdmin()
                ? '<button type="button" class="btn btn-sm btn-primary" onclick="event.stopPropagation();window.openEditModalHub(' +
                  v.id +
                  ')">Edit Vendor</button>'
                : '') +
            '<a href="/vendor/items.html?vendor_id=' +
            v.id +
            '" class="btn btn-sm" style="display:inline-block;text-decoration:none;border:1px solid var(--border);padding:0.45rem 0.75rem;font-size:0.78rem" onclick="event.stopPropagation()">View Items</a>' +
            '</div></div>' +
            '</div>' +

            /* ── Sales History section ── */
            '<div style="border-top:1px solid var(--border);padding:1rem 1.25rem">' +
            '<h4 class="vh-detail-h" style="margin-bottom:0.5rem">Sales History</h4>' +
            '<div id="vh-sales-' + v.id + '" style="font-size:0.85rem;color:var(--text-light)">Loading sales...</div>' +
            '</div>'
        );
    }

    window.openAdjustFromHub = function (id) {
        var v = findVendor(id);
        if (v && typeof window.openAdjustModal === 'function') {
            window.openAdjustModal(
                id,
                v.name,
                v.sales_balance != null && v.sales_balance !== '' ? num(v.sales_balance) : num(v.balance)
            );
        }
    };

    window.openHistoryFromHub = function (id) {
        var v = findVendor(id);
        if (v && typeof window.openHistoryModal === 'function') {
            window.openHistoryModal(id, v.name);
        }
    };

    window.openRentModalHub = function (vendorId) {
        var v = findVendor(vendorId);
        if (!v) return;
        _payVendorId = vendorId;
        var label = document.getElementById('rent-modal-vendor');
        if (label) label.textContent = v.name + ' — Booth ' + v.booth_number;
        var amt = document.getElementById('rent-pay-amount');
        if (amt) amt.value = (v.monthly_rent || 0).toFixed(2);
        var method = document.getElementById('rent-pay-method');
        if (method) {
            method.value = 'cash';
            window.onRentPayMethodChange();
        }
        var now = new Date();
        var per = document.getElementById('rent-pay-period');
        if (per) per.value = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0');
        var notes = document.getElementById('rent-pay-notes');
        if (notes) notes.value = '';
        var btn = document.getElementById('rent-pay-submit');
        if (btn) {
            btn.disabled = false;
            window.onRentPayMethodChange();
        }
        var overlay = document.getElementById('rent-modal-overlay');
        if (overlay) overlay.style.display = 'flex';
    };

    window.closeRentModalHub = function () {
        var overlay = document.getElementById('rent-modal-overlay');
        if (overlay) overlay.style.display = 'none';
        _payVendorId = null;
    };

    window.onRentPayMethodChange = function () {
        var method = (document.getElementById('rent-pay-method') || {}).value;
        var cardInfo = document.getElementById('rent-card-info');
        var btn = document.getElementById('rent-pay-submit');
        if (cardInfo) cardInfo.style.display = method === 'card' ? 'block' : 'none';
        if (btn) btn.textContent = method === 'card' ? 'Charge Card' : 'Record Payment';
    };

    window.submitRentModalHub = async function () {
        if (!_payVendorId) return;
        var amount = parseFloat((document.getElementById('rent-pay-amount') || {}).value);
        var method = (document.getElementById('rent-pay-method') || {}).value;
        var period = (document.getElementById('rent-pay-period') || {}).value;
        var notes = ((document.getElementById('rent-pay-notes') || {}).value || '').trim();
        var btn = document.getElementById('rent-pay-submit');

        if (!amount || amount <= 0) {
            showAlert('alert-container', 'Enter a valid amount.', 'error');
            return;
        }

        if (method === 'card') {
            window.closeRentModalHub();
            startCardRentHub(_payVendorId, amount, period, notes);
            return;
        }

        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Recording…';
        }
        try {
            var result = await apiPost('/api/v1/admin/vendors/' + _payVendorId + '/record-rent', {
                amount: amount,
                method: method,
                period: period,
                notes: notes,
            });
            window.closeRentModalHub();
            showAlert('alert-container', result.message || 'Recorded.', 'success');
            await window.loadVendorOverview();
        } catch (e) {
            showAlert('alert-container', e.message || 'Failed', 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Record Payment';
            }
        }
    };

    async function startCardRentHub(vendorId, amount, period, notes) {
        var v = findVendor(vendorId);
        var vLabel = v ? v.name + ' — Booth ' + v.booth_number : 'Vendor #' + vendorId;
        var tl = document.getElementById('rent-terminal-vendor');
        if (tl) tl.textContent = vLabel;
        var ta = document.getElementById('rent-terminal-amount');
        if (ta) ta.textContent = fmt(amount);
        var ts = document.getElementById('rent-terminal-status');
        if (ts) ts.style.display = '';
        var tr = document.getElementById('rent-terminal-result');
        if (tr) tr.style.display = 'none';
        var ov = document.getElementById('rent-terminal-overlay');
        if (ov) ov.style.display = 'flex';

        try {
            var charge = await apiPost('/api/v1/admin/vendors/' + vendorId + '/rent-charge-card', { amount: amount });
            pollTerminalHub(charge.poynt_order_id, vendorId, amount, period, notes);
        } catch (e) {
            showTerminalErrorHub(e.message || 'Failed to start terminal');
        }
    }

    function pollTerminalHub(orderId, vendorId, amount, period, notes) {
        var attempts = 0;
        var maxAttempts = 90;
        if (_terminalPollInterval) {
            clearInterval(_terminalPollInterval);
            _terminalPollInterval = null;
        }
        _terminalPollInterval = setInterval(async function () {
            attempts++;
            if (attempts > maxAttempts) {
                clearInterval(_terminalPollInterval);
                _terminalPollInterval = null;
                showTerminalErrorHub('Payment timed out.');
                return;
            }
            try {
                var status = await apiGet('/api/v1/admin/rent-charge-status/' + orderId);
                if (status.status === 'APPROVED') {
                    clearInterval(_terminalPollInterval);
                    _terminalPollInterval = null;
                    await recordCardRentHub(vendorId, amount, period, notes, status.transaction_id);
                } else if (status.status === 'DECLINED') {
                    clearInterval(_terminalPollInterval);
                    _terminalPollInterval = null;
                    showTerminalErrorHub('Card declined.');
                }
            } catch (err) {}
        }, 2000);
    }

    async function recordCardRentHub(vendorId, amount, period, notes, transactionId) {
        try {
            var result = await apiPost('/api/v1/admin/vendors/' + vendorId + '/record-rent', {
                amount: amount,
                method: 'card',
                period: period,
                notes: (notes ? notes + ' | ' : '') + 'Poynt Txn: ' + (transactionId || 'N/A'),
            });
            var ts = document.getElementById('rent-terminal-status');
            if (ts) ts.style.display = 'none';
            var tr = document.getElementById('rent-terminal-result');
            if (tr) {
                tr.style.display = 'block';
                tr.style.background = 'color-mix(in srgb, var(--success-light) 10%, transparent)';
                tr.style.color = 'var(--success-light)';
                tr.textContent = result.message || 'Recorded.';
            }
            var btn = document.getElementById('rent-terminal-close');
            if (btn) btn.textContent = 'Close';
            await window.loadVendorOverview();
        } catch (e) {
            showTerminalErrorHub('Charged but record failed: ' + (e.message || ''));
        }
    }

    function showTerminalErrorHub(msg) {
        var ts = document.getElementById('rent-terminal-status');
        if (ts) ts.style.display = 'none';
        var tr = document.getElementById('rent-terminal-result');
        if (tr) {
            tr.style.display = 'block';
            tr.style.background = 'color-mix(in srgb, var(--danger) 10%, transparent)';
            tr.style.color = 'var(--danger)';
            tr.textContent = msg;
        }
    }

    window.closeRentTerminalHub = function () {
        if (_terminalPollInterval) {
            clearInterval(_terminalPollInterval);
            _terminalPollInterval = null;
        }
        var ov = document.getElementById('rent-terminal-overlay');
        if (ov) ov.style.display = 'none';
    };

    window.toggleFlagHub = async function (vendorId, btn) {
        if (btn) btn.disabled = true;
        try {
            await apiPost('/api/v1/admin/vendors/' + vendorId + '/flag', {});
            await window.loadVendorOverview();
        } catch (e) {
            showAlert('alert-container', e.message || 'Flag failed', 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    };

    window.openEditModalHub = function (vendorId) {
        var v = findVendor(vendorId);
        if (!v) return;
        _editVendorId = vendorId;
        var title = document.getElementById('edit-account-title');
        if (title) title.textContent = v.role === 'vendor' ? 'Edit vendor' : 'Edit employee';
        var set = function (id, val) {
            var el = document.getElementById(id);
            if (el) el.value = val != null ? val : '';
        };
        set('edit-v-name', v.name);
        set('edit-v-email', v.email);
        set('edit-v-phone', v.phone);
        set('edit-v-booth', v.booth_number === '—' ? '' : v.booth_number);
        set('edit-v-rent', v.monthly_rent);
        set('edit-v-comm', v.commission_rate);
        set('edit-v-payout', v.payout_method === '—' ? '' : v.payout_method);
        // zelle removed
        set('edit-v-status', v.status || 'active');
        set('edit-v-notes', v.notes);
        window.onEditPayoutChange();
        var o = document.getElementById('edit-vendor-overlay');
        if (o) o.style.display = 'flex';
    };

    window.onEditPayoutChange = function () {
        // payout method is always check — no conditional UI needed
    };

    window.closeEditModalHub = function () {
        var o = document.getElementById('edit-vendor-overlay');
        if (o) o.style.display = 'none';
        _editVendorId = null;
    };

    window.submitEditModalHub = async function () {
        if (!_editVendorId) return;
        var body = {
            name: (document.getElementById('edit-v-name') || {}).value.trim(),
            email: (document.getElementById('edit-v-email') || {}).value.trim(),
            phone: (document.getElementById('edit-v-phone') || {}).value.trim() || null,
            booth_number: (document.getElementById('edit-v-booth') || {}).value.trim() || null,
            monthly_rent: parseFloat((document.getElementById('edit-v-rent') || {}).value) || 0,
            commission_rate: parseFloat((document.getElementById('edit-v-comm') || {}).value) || 0,
            payout_method: (document.getElementById('edit-v-payout') || {}).value || null,
            zelle_handle: null,
            status: (document.getElementById('edit-v-status') || {}).value,
            notes: (document.getElementById('edit-v-notes') || {}).value.trim() || null,
        };
        var btn = document.getElementById('edit-v-submit');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Saving…';
        }
        try {
            var token = sessionStorage.getItem('bmm_token');
            var resp = await fetch('/api/v1/vendors/' + _editVendorId, {
                method: 'PUT',
                headers: {
                    Authorization: 'Bearer ' + token,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(body),
            });
            var data = await resp.json();
            if (!resp.ok) throw new Error(data.detail || 'Update failed');
            window.closeEditModalHub();
            showAlert('alert-container', 'Vendor updated.', 'success');
            await window.loadVendorOverview();
            if (typeof window.loadEmployees === 'function') window.loadEmployees();
        } catch (e) {
            showAlert('alert-container', e.message || 'Save failed', 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Save';
            }
        }
    };

    window.confirmProcessPayoutsHub = function () {
        if (!_vendorData || _vendorData.already_processed) return;
        var o = document.getElementById('payout-confirm-overlay');
        var msg = document.getElementById('payout-confirm-msg');
        if (msg)
            msg.textContent =
                'This will process payouts for ' +
                (_vendorData.period || '') +
                ', deducting rent from vendor balances and resetting balances. Vendors will be notified by email. This cannot be undone.';
        if (o) o.style.display = 'flex';
    };

    window.closePayoutConfirmHub = function () {
        var o = document.getElementById('payout-confirm-overlay');
        if (o) o.style.display = 'none';
    };

    window.doProcessPayoutsHub = async function () {
        var btn = document.getElementById('payout-confirm-go');
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Processing…';
        }
        try {
            var result = await apiPost('/api/v1/admin/process-payouts', {});
            window.closePayoutConfirmHub();
            showAlert(
                'alert-container',
                result.message || 'Payouts processed.',
                'success'
            );
            await window.loadVendorOverview();
        } catch (e) {
            showAlert('alert-container', e.message || 'Failed', 'error');
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Process Payouts';
            }
        }
    };

    window.sendRentRemindersHub = async function () {
        try {
            var r = await apiPost('/api/v1/admin/send-rent-reminders', {});
            showAlert('alert-container', r.message || 'Reminders sent.', 'success');
        } catch (e) {
            showAlert('alert-container', e.message || 'Failed', 'error');
        }
    };

    window.sendWeeklyReportsHub = async function () {
        try {
            var r = await apiPost('/api/v1/admin/send-weekly-reports', {});
            showAlert('alert-container', r.message || 'Reports sent.', 'success');
        } catch (e) {
            showAlert('alert-container', e.message || 'Failed', 'error');
        }
    };
})();
