/**
 * Consolidated admin vendor workspace: overview API, inspector, and modal actions.
 * Loaded from admin/index.html after api.js.
 */
(function () {
    var _vendorData = null;
    var _filtered = [];
    var _selectedVendorId = null;
    var _payVendorId = null;
    var _editVendorId = null;
    var _terminalPollInterval = null;
    var _vhPageSize = 10;
    var _vhCurrentPage = 1;
    var _inspectorRequestSeq = 0;
    var _inspectorPages = { sales: 1, rent: 1, payout: 1 };

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
        } catch (e) {
            showAlert('alert-container', 'Vendor overview: ' + (e.message || e), 'error');
            var list = document.getElementById('vendor-hub-browser-list');
            if (list) list.innerHTML = '<div class="vendor-browser-empty">Failed to load vendors.</div>';
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
        renderVendorRows();
    };

    function getVisibleVendors() {
        var vendorsFull = _filtered || [];
        var total = vendorsFull.length;
        var pages = Math.max(1, Math.ceil(total / _vhPageSize));
        if (_vhCurrentPage > pages) _vhCurrentPage = pages;
        if (_vhCurrentPage < 1) _vhCurrentPage = 1;
        var start = (_vhCurrentPage - 1) * _vhPageSize;
        return {
            total: total,
            pages: pages,
            start: start,
            vendors: vendorsFull.slice(start, start + _vhPageSize),
        };
    }

    function selectedVendorInView(vendors) {
        for (var i = 0; i < vendors.length; i++) {
            if (vendors[i].id === _selectedVendorId) return true;
        }
        return false;
    }

    function selectionTone(value) {
        if (value < 0) return 'var(--danger)';
        if (value > 0) return 'var(--success-light)';
        return 'var(--text-light)';
    }

    function renderVendorRows() {
        var browser = document.getElementById('vendor-hub-browser-list');
        if (!browser) return;
        var view = getVisibleVendors();
        var total = view.total;
        var pages = view.pages;
        var start = view.start;
        var vendors = view.vendors;

        if (!vendors.length) {
            browser.innerHTML = '<div class="vendor-browser-empty">' +
                (total === 0 ? 'No vendors found.' : 'No vendors on this page.') +
                '</div>';
            _selectedVendorId = null;
            renderVendorInspector(null);
            updateVendorHubPagination(total, start, 0, pages);
            return;
        }

        if (!selectedVendorInView(vendors)) {
            _selectedVendorId = vendors[0].id;
        }

        updateVendorHubPagination(total, start, vendors.length, pages);

        browser.innerHTML = vendors
            .map(function (v) {
                var flag = v.rent_flagged ? '<span title="Flagged">🚩</span> ' : '';
                var current = displayBalance(v);
                return (
                    '<button type="button" class="vendor-browser-item' +
                    (v.id === _selectedVendorId ? ' is-selected' : '') +
                    '" onclick="window.selectVendorWorkspace(' + v.id + ')">' +
                    '<div>' +
                    '<div class="vendor-browser-name">' +
                    flag +
                    esc(v.name) +
                    '</div>' +
                    '<div class="vendor-browser-meta">Booth ' +
                    esc(v.booth_number) +
                    ' · ' +
                    rentBadge(v.rent_status) +
                    '<br>Sales ' +
                    fmt(num(v.sales_balance)) +
                    ' · Rent ' +
                    fmt(num(v.rent_balance)) +
                    '</div>' +
                    '</div>' +
                    '<div class="vendor-browser-balance">' +
                    '<div class="balance-amount" style="color:' + selectionTone(current) + '">' + fmt(current) + '</div>' +
                    '<div class="balance-caption">Current</div>' +
                    '</div>' +
                    '</button>'
                );
            })
            .join('');
        renderVendorInspector(findVendor(_selectedVendorId));
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
        _vhCurrentPage = 1;
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

    window.selectVendorWorkspace = function selectVendorWorkspace(vendorId) {
        if (_selectedVendorId !== vendorId) {
            _inspectorPages = { sales: 1, rent: 1, payout: 1 };
        }
        _selectedVendorId = vendorId;
        var v = findVendor(vendorId);
        if (!v) return;
        renderVendorRows();
    };

    window.vendorInspectorPage = function vendorInspectorPage(section, delta) {
        if (!_selectedVendorId) return;
        var current = _inspectorPages[section] || 1;
        current += delta;
        if (current < 1) current = 1;
        _inspectorPages[section] = current;
        loadVendorInspectorData(_selectedVendorId);
    };

    function renderVendorInspector(v) {
        var inspector = document.getElementById('vendor-inspector');
        if (!inspector) return;
        if (!v) {
            inspector.innerHTML =
                '<div class="vendor-inspector-placeholder"><div>' +
                '<div class="vendor-browser-kicker">Ready</div>' +
                '<h3 class="vendor-browser-title" style="margin-top:0.4rem">Select a vendor</h3>' +
                '<p class="vendor-browser-sub" style="max-width:32rem;margin:0.55rem auto 0">Use the search on the left to open a single vendor workspace with balances, rent, payout preview, notes, recent sales, and history.</p>' +
                '</div></div>';
            return;
        }

        var balance = displayBalance(v);
        var pp = v.payout_preview || {};
        var rentTone = num(v.rent_balance) < 0 ? 'var(--danger)' : 'var(--gold)';
        var balanceTone = selectionTone(balance);
        var actions = '';
        if (isVendorHubAdmin()) {
            actions += '<button type="button" class="btn btn-sm btn-primary" onclick="window.openEditModalHub(' + v.id + ')">Edit Vendor</button>';
            actions += '<button type="button" class="btn btn-sm" style="background:var(--gold);color:var(--charcoal-deep)" onclick="window.openAdjustFromHub(' + v.id + ')">Adjust Balance</button>';
            actions += '<button type="button" class="btn btn-sm" style="background:color-mix(in srgb,var(--success-light) 20%,transparent);color:var(--success-light);border:1px solid color-mix(in srgb,var(--success-light) 35%,transparent)" onclick="window.openRentModalHub(' + v.id + ')">Record Rent</button>';
            actions += '<button type="button" class="btn btn-sm" onclick="window.toggleFlagHub(' + v.id + ', this)">' + (v.rent_flagged ? 'Unflag Rent' : 'Flag Rent') + '</button>';
        }
        actions += '<a href="/vendor/items.html?vendor_id=' + v.id + '" class="btn btn-sm" style="display:inline-flex;align-items:center;justify-content:center;text-decoration:none">View Items</a>';
        actions += '<a href="/admin/vendors.html?vendor_id=' + v.id + '" class="btn btn-sm" style="display:inline-flex;align-items:center;justify-content:center;text-decoration:none">Open Vendor Page</a>';

        inspector.innerHTML =
            '<div class="vendor-inspector-body">' +
            '<div class="vendor-inspector-head">' +
            '<div>' +
            '<div class="vendor-inspector-kicker">Vendor workspace</div>' +
            '<h3 class="vendor-inspector-name">' + esc(v.name) + '</h3>' +
            '<div class="vendor-inspector-sub">' +
            '<span>Booth ' + esc(v.booth_number) + '</span>' +
            '<span>•</span>' +
            '<span>' + esc(v.email || 'No email') + '</span>' +
            '<span>•</span>' +
            rentBadge(v.rent_status) +
            (v.rent_flagged ? '<span class="vh-badge vh-badge--bad">FLAGGED</span>' : '') +
            '</div>' +
            '</div>' +
            '<div class="vendor-inspector-actions">' + actions + '</div>' +
            '</div>' +

            '<div class="vendor-inspector-grid">' +
            '<div class="vendor-stat"><div class="vendor-stat-label">Current balance</div><div class="vendor-stat-value" style="color:' + balanceTone + '">' + fmt(balance) + '</div><div class="vendor-stat-note">Sales plus any past-due rent only</div></div>' +
            '<div class="vendor-stat"><div class="vendor-stat-label">Sales balance</div><div class="vendor-stat-value" style="color:var(--gold)">' + fmt(num(v.sales_balance)) + '</div><div class="vendor-stat-note">Available sales total</div></div>' +
            '<div class="vendor-stat"><div class="vendor-stat-label">Rent ledger</div><div class="vendor-stat-value" style="color:' + rentTone + '">' + fmt(num(v.rent_balance)) + '</div><div class="vendor-stat-note">' + (num(v.rent_balance) < 0 ? 'Past-due rent is reducing balance' : 'Positive value is prepaid credit') + '</div></div>' +
            '<div class="vendor-stat"><div class="vendor-stat-label">Monthly rent</div><div class="vendor-stat-value">' + fmt(num(v.monthly_rent)) + '</div><div class="vendor-stat-note">Payout method: ' + esc(v.payout_method || '—') + '</div></div>' +
            '</div>' +

            '<div class="vendor-inspector-sections">' +
            '<div class="vendor-stack">' +
            '<section class="vendor-panel">' +
            '<h4 class="vendor-panel-title">Account</h4>' +
            '<div class="vendor-info-grid">' +
            '<div class="vendor-info-item"><label>Email</label><div>' + esc(v.email || '—') + '</div></div>' +
            '<div class="vendor-info-item"><label>Phone</label><div>' + esc(v.phone || '—') + '</div></div>' +
            '<div class="vendor-info-item"><label>Status</label><div>' + esc(v.status || '—') + '</div></div>' +
            '<div class="vendor-info-item"><label>Commission</label><div>' + (num(v.commission_rate) * 100).toFixed(1) + '%</div></div>' +
            '</div>' +
            '<div style="margin-top:1rem">' +
            '<div class="vendor-info-item"><label>Notes</label><div class="vendor-notes-box">' + esc(v.notes || 'No notes on file.') + '</div></div>' +
            '</div>' +
            '</section>' +

            '<section class="vendor-panel">' +
            '<h4 class="vendor-panel-title">Payout preview</h4>' +
            '<div class="vendor-info-grid">' +
            '<div class="vendor-info-item"><label>Gross</label><div>' + fmt(pp.gross) + '</div></div>' +
            '<div class="vendor-info-item"><label>Rent deduction</label><div style="color:var(--danger)">-' + fmt(pp.rent_deducted) + '</div></div>' +
            '<div class="vendor-info-item"><label>Net payout</label><div style="color:var(--success-light)">' + fmt(pp.net) + '</div></div>' +
            '<div class="vendor-info-item"><label>Shortfall</label><div style="color:' + (num(pp.shortfall) > 0 ? 'var(--danger)' : 'var(--text)') + '">' + fmt(pp.shortfall || 0) + '</div></div>' +
            '</div>' +
            '</section>' +

            '<section class="vendor-panel">' +
            '<h4 class="vendor-panel-title">Recent sales</h4>' +
            '<div id="vh-sales-panel" class="vendor-inline-loading">Loading recent sales…</div>' +
            '</section>' +
            '</div>' +

            '<div class="vendor-stack">' +
            '<section class="vendor-panel">' +
            '<h4 class="vendor-panel-title">Balance history</h4>' +
            '<div id="vh-balance-history-panel" class="vendor-inline-loading">Loading balance history…</div>' +
            '</section>' +
            '<section class="vendor-panel">' +
            '<h4 class="vendor-panel-title">Rent history</h4>' +
            '<div id="vh-rent-history-panel" class="vendor-inline-loading">Loading rent history…</div>' +
            '</section>' +
            '<section class="vendor-panel">' +
            '<h4 class="vendor-panel-title">Payout history</h4>' +
            '<div id="vh-payout-history-panel" class="vendor-inline-loading">Loading payout history…</div>' +
            '</section>' +
            '</div>' +
            '</div>' +
            '</div>';

        loadVendorInspectorData(v.id);
    }

    async function loadVendorInspectorData(vendorId) {
        var requestSeq = ++_inspectorRequestSeq;
        var salesPanel = document.getElementById('vh-sales-panel');
        var balancePanel = document.getElementById('vh-balance-history-panel');
        var rentPanel = document.getElementById('vh-rent-history-panel');
        var payoutPanel = document.getElementById('vh-payout-history-panel');
        if (salesPanel) salesPanel.textContent = 'Loading recent sales…';
        if (balancePanel) balancePanel.textContent = 'Loading balance history…';
        if (rentPanel) rentPanel.textContent = 'Loading rent history…';
        if (payoutPanel) payoutPanel.textContent = 'Loading payout history…';

        var salesOffset = (_inspectorPages.sales - 1) * 10;
        var salesPromise = apiGet('/api/v1/sales/?vendor_id=' + vendorId + '&limit=11&offset=' + salesOffset);
        var balancePromise = apiGet('/api/v1/vendors/' + vendorId + '/balance/history?limit=20');
        var rentPromise = apiGet('/api/v1/admin/vendors/' + vendorId + '/rent-history');
        var payoutPromise = apiGet('/api/v1/admin/reference-history?vendor_id=' + vendorId + '&entry_type=payout&limit=200');

        var results = await Promise.allSettled([salesPromise, balancePromise, rentPromise, payoutPromise]);
        if (requestSeq !== _inspectorRequestSeq || vendorId !== _selectedVendorId) return;

        renderVendorSalesPanel(vendorId, results[0], salesPanel);
        renderBalanceHistoryPanel(results[1], balancePanel);
        renderRentHistoryPanel(results[2], rentPanel);
        renderPayoutHistoryPanel(results[3], payoutPanel);
    }

    function shortDate(iso) {
        if (!iso) return '—';
        var d = new Date(iso);
        return window.bmmFormatDate(d, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'America/Chicago' });
    }

    function shortDateTime(iso) {
        if (!iso) return '—';
        var d = new Date(iso);
        return window.bmmFormatDate(d, { month: 'short', day: 'numeric', timeZone: 'America/Chicago' }) +
            ' · ' +
            window.bmmFormatTime(d, { hour: 'numeric', minute: '2-digit', timeZone: 'America/Chicago' });
    }

    function renderHistoryRows(rows) {
        if (!rows || !rows.length) {
            return '<div class="vendor-inline-empty">No history found.</div>';
        }
        return '<div class="vendor-history-list">' + rows.join('') + '</div>';
    }

    function renderPager(section, page, hasMore, emptyLabel, rowCount, pageSize) {
        if (!rowCount && page <= 1) return '';
        var status = rowCount
            ? ('Showing ' + (((page - 1) * pageSize) + 1) + '–' + (((page - 1) * pageSize) + rowCount))
            : emptyLabel;
        return '<div class="vendor-history-controls">' +
            '<div class="pager-status">' + esc(status) + '</div>' +
            '<div class="pager-buttons">' +
            '<button type="button" class="btn btn-sm" onclick="window.vendorInspectorPage(\'' + section + '\', -1)"' + (page <= 1 ? ' disabled' : '') + '>Previous</button>' +
            '<button type="button" class="btn btn-sm" onclick="window.vendorInspectorPage(\'' + section + '\', 1)"' + (!hasMore ? ' disabled' : '') + '>Next</button>' +
            '</div>' +
            '</div>';
    }

    function renderVendorSalesPanel(vendorId, result, container) {
        if (!container) return;
        if (result.status !== 'fulfilled') {
            container.innerHTML = '<div class="vendor-inline-error">' + esc(result.reason && result.reason.message ? result.reason.message : 'Failed to load sales.') + '</div>';
            return;
        }
        var sales = result.value || [];
        var hasMore = sales.length > 10;
        if (hasMore) sales = sales.slice(0, 10);
        if (!sales.length) {
            container.innerHTML = '<div class="vendor-inline-empty">No sales recorded yet.</div>' + renderPager('sales', _inspectorPages.sales, false, 'No older sales', 0, 10);
            return;
        }
        var rows = sales.map(function (sale) {
            var lines = sale.line_items || sale.items || [];
            var vendorItems = lines.filter(function (si) { return Number(si.vendor_id) === Number(vendorId); });
            var vendorTotal = vendorItems.reduce(function (sum, si) {
                if (si.line_total != null && si.line_total !== '') return sum + num(si.line_total);
                return sum + (num(si.unit_price != null ? si.unit_price : si.price) * (si.quantity || 1));
            }, 0);
            var summary = vendorItems.map(function (si) {
                return (si.item_name || si.name || 'Item') + ((si.quantity || 1) > 1 ? ' x' + (si.quantity || 1) : '');
            }).join(', ') || '—';
            return '<div class="vendor-history-row">' +
                '<div class="vendor-history-main">' + esc(summary) +
                '<div class="vendor-history-sub">Sale #' + esc(sale.id) + ' · ' + shortDateTime(sale.created_at) + ' · ' + esc((sale.payment_method || '—').toUpperCase()) + '</div>' +
                '</div>' +
                '<div class="vendor-history-amount">' + fmt(vendorTotal) + '</div>' +
                '</div>';
        });
        container.innerHTML = renderHistoryRows(rows) + renderPager('sales', _inspectorPages.sales, hasMore, 'No older sales', rows.length, 10);
    }

    function renderBalanceHistoryPanel(result, container) {
        if (!container) return;
        if (result.status !== 'fulfilled') {
            container.innerHTML = '<div class="vendor-inline-error">' + esc(result.reason && result.reason.message ? result.reason.message : 'Failed to load balance history.') + '</div>';
            return;
        }
        var entries = result.value || [];
        var rows = entries.map(function (a) {
            return '<div class="vendor-history-row">' +
                '<div class="vendor-history-main">' + esc(a.reason || 'Adjustment') +
                '<div class="vendor-history-sub">' + shortDateTime(a.created_at) + ' · ' + esc((a.adjustment_type || '').toUpperCase()) + ' · ' + fmt(a.balance_before) + ' → ' + fmt(a.balance_after) + '</div>' +
                '</div>' +
                '<div class="vendor-history-amount" style="color:' + (a.adjustment_type === 'debit' ? 'var(--danger)' : 'var(--success-light)') + '">' + fmt(a.amount) + '</div>' +
                '</div>';
        });
        container.innerHTML = renderHistoryRows(rows);
    }

    function renderRentHistoryPanel(result, container) {
        if (!container) return;
        if (result.status !== 'fulfilled') {
            container.innerHTML = '<div class="vendor-inline-error">' + esc(result.reason && result.reason.message ? result.reason.message : 'Failed to load rent history.') + '</div>';
            return;
        }
        var data = result.value || {};
        var entries = [];
        (data.payments || []).forEach(function (p) {
            entries.push({
                sortDate: p.processed_at || ((p.period_month || '') + '-01'),
                html: '<div class="vendor-history-row">' +
                '<div class="vendor-history-main">' + esc(p.period_month || 'Rent payment') +
                '<div class="vendor-history-sub">' + shortDateTime(p.processed_at) + ' · ' + esc((p.method || '—').toUpperCase()) + (p.notes ? ' · ' + esc(p.notes) : '') + '</div>' +
                '</div>' +
                '<div class="vendor-history-amount">' + fmt(p.amount) + '</div>' +
                '</div>'
            });
        });
        (data.legacy_entries || []).forEach(function (entry) {
            entries.push({
                sortDate: entry.entry_date || entry.imported_at,
                html: '<div class="vendor-history-row">' +
                '<div class="vendor-history-main">' + esc(entry.description || 'Legacy rent record') +
                '<div class="vendor-history-sub">' + shortDate(entry.entry_date) + ' · Ricochet reference</div>' +
                '</div>' +
                '<div class="vendor-history-amount">' + fmt(entry.amount) + '</div>' +
                '</div>'
            });
        });
        entries.sort(function (a, b) {
            return new Date(b.sortDate || 0) - new Date(a.sortDate || 0);
        });
        var page = _inspectorPages.rent || 1;
        var pageSize = 3;
        var start = (page - 1) * pageSize;
        var visible = entries.slice(start, start + pageSize).map(function (entry) { return entry.html; });
        var hasMore = entries.length > (start + pageSize);
        container.innerHTML = renderHistoryRows(visible) + renderPager('rent', page, hasMore, 'No older rent entries', visible.length, pageSize);
    }

    function renderPayoutHistoryPanel(result, container) {
        if (!container) return;
        if (result.status !== 'fulfilled') {
            container.innerHTML = '<div class="vendor-inline-error">' + esc(result.reason && result.reason.message ? result.reason.message : 'Failed to load payout history.') + '</div>';
            return;
        }
        var data = result.value || {};
        var entries = data.entries || [];
        var page = _inspectorPages.payout || 1;
        var pageSize = 3;
        var start = (page - 1) * pageSize;
        var visibleEntries = entries.slice(start, start + pageSize);
        var rows = visibleEntries.map(function (entry) {
            return '<div class="vendor-history-row">' +
                '<div class="vendor-history-main">' + esc(entry.description || 'Payout') +
                '<div class="vendor-history-sub">' + shortDate(entry.entry_date) + ' · ' + esc(entry.source_system || 'Reference') + '</div>' +
                '</div>' +
                '<div class="vendor-history-amount">' + fmt(entry.amount) + '</div>' +
                '</div>';
        });
        var hasMore = entries.length > (start + pageSize);
        container.innerHTML = renderHistoryRows(rows) + renderPager('payout', page, hasMore, 'No older payout entries', rows.length, pageSize);
    }

    window.openAdjustFromHub = function (id) {
        var v = findVendor(id);
        if (v && typeof window.openAdjustModal === 'function') {
            window.openAdjustModal(
                id,
                v.name,
                displayBalance(v)
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
        set('edit-v-new-password', '');
        var passwordStatus = document.getElementById('edit-v-password-status');
        if (passwordStatus) passwordStatus.textContent = '';
        var passwordBlock = document.getElementById('edit-v-password-block');
        if (passwordBlock) passwordBlock.style.display = v.role === 'vendor' ? 'block' : 'none';
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
        var passwordInput = document.getElementById('edit-v-new-password');
        if (passwordInput) passwordInput.value = '';
        var passwordStatus = document.getElementById('edit-v-password-status');
        if (passwordStatus) passwordStatus.textContent = '';
        _editVendorId = null;
    };

    window.resetVendorPasswordHub = async function () {
        if (!_editVendorId) return;
        var vendor = findVendor(_editVendorId);
        if (!vendor || vendor.role !== 'vendor') return;
        var input = document.getElementById('edit-v-new-password');
        var status = document.getElementById('edit-v-password-status');
        var btn = document.getElementById('edit-v-reset-password-btn');
        var newPassword = ((input || {}).value || '').trim();
        if (!newPassword || newPassword.length < 6) {
            if (status) {
                status.textContent = 'Password must be at least 6 characters.';
                status.style.color = 'var(--danger)';
            }
            return;
        }
        if (btn) {
            btn.disabled = true;
            btn.textContent = 'Resetting…';
        }
        if (status) {
            status.textContent = '';
        }
        try {
            await apiPost('/api/v1/vendors/' + _editVendorId + '/reset-password', {
                new_password: newPassword,
            });
            if (input) input.value = '';
            if (status) {
                status.textContent = 'Password reset successfully.';
                status.style.color = 'var(--success-light)';
            }
        } catch (e) {
            if (status) {
                status.textContent = e.message || 'Password reset failed.';
                status.style.color = 'var(--danger)';
            }
        } finally {
            if (btn) {
                btn.disabled = false;
                btn.textContent = 'Reset Password';
            }
        }
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
