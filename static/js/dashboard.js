/**
 * Dashboard JavaScript - PT Agiva Indonesia Network Automation
 * Supports BOTH:
 * 1. Offline file:// direct double-click (simulates real-time chart animation)
 * 2. Online http:// server mode (polls /api/status live JSON endpoint)
 */

let cpuMemChart = null;
let trafficChart = null;
let currentDashboardRange = 'live';
let isRangeJustChanged = false;
const MAX_CHART_POINTS = 14;

document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    initTimeRangeSelector();
    setupTableFilters();
    setupSearchFilter();

    // Poll immediately on page load
    pollRealtimeStatus();

    // Polling interval (setiap 5 detik sekali sesuai permintaan)
    setInterval(pollRealtimeStatus, 5000);
});

/* --------------------------------------------------------------------------
   Chart.js Initialization
   -------------------------------------------------------------------------- */
function initCharts() {
    const initData = window.INITIAL_CHART_DATA || { labels: [], cpu: [], mem: [], ingress: [], egress: [] };

    // 1. CPU & Memory Chart
    const ctxCpuMem = document.getElementById('cpuMemChart');
    if (ctxCpuMem) {
        const gradientCpu = ctxCpuMem.getContext('2d').createLinearGradient(0, 0, 0, 220);
        gradientCpu.addColorStop(0, 'rgba(16, 185, 129, 0.4)');
        gradientCpu.addColorStop(1, 'rgba(16, 185, 129, 0.0)');

        const gradientMem = ctxCpuMem.getContext('2d').createLinearGradient(0, 0, 0, 220);
        gradientMem.addColorStop(0, 'rgba(245, 158, 11, 0.3)');
        gradientMem.addColorStop(1, 'rgba(245, 158, 11, 0.0)');

        cpuMemChart = new Chart(ctxCpuMem, {
            type: 'line',
            data: {
                labels: [...(initData.labels || [])],
                datasets: [
                    {
                        label: 'CPU (%)',
                        data: [...(initData.cpu || [])],
                        borderColor: '#10b981',
                        backgroundColor: gradientCpu,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.35,
                        pointRadius: 2,
                        pointHoverRadius: 5
                    },
                    {
                        label: 'Memory (%)',
                        data: [...(initData.mem || [])],
                        borderColor: '#f59e0b',
                        backgroundColor: gradientMem,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.35,
                        pointRadius: 2,
                        pointHoverRadius: 5
                    }
                ]
            },
            options: getCommonChartOptions('%', 0, 100, 20)
        });
    }

    // 2. Network Traffic Chart
    const ctxTraffic = document.getElementById('trafficChart');
    if (ctxTraffic) {
        const gradientCyan = ctxTraffic.getContext('2d').createLinearGradient(0, 0, 0, 220);
        gradientCyan.addColorStop(0, 'rgba(6, 182, 212, 0.35)');
        gradientCyan.addColorStop(1, 'rgba(6, 182, 212, 0.0)');

        const gradientOrange = ctxTraffic.getContext('2d').createLinearGradient(0, 0, 0, 220);
        gradientOrange.addColorStop(0, 'rgba(249, 115, 22, 0.25)');
        gradientOrange.addColorStop(1, 'rgba(249, 115, 22, 0.0)');

        trafficChart = new Chart(ctxTraffic, {
            type: 'line',
            data: {
                labels: [...(initData.labels || [])],
                datasets: [
                    {
                        label: 'Ingress (Mbps)',
                        data: [...(initData.ingress || [])],
                        borderColor: '#06b6d4',
                        backgroundColor: gradientCyan,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.35,
                        pointRadius: 2,
                        pointHoverRadius: 5
                    },
                    {
                        label: 'Egress (Mbps)',
                        data: [...(initData.egress || [])],
                        borderColor: '#f97316',
                        backgroundColor: gradientOrange,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.35,
                        pointRadius: 2,
                        pointHoverRadius: 5
                    }
                ]
            },
            options: getCommonChartOptions(' Mbps', 0, 250, 50)
        });
    }
}

function getCommonChartOptions(unit, minVal, maxVal, stepSize = null) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: '#1e293b',
                titleColor: '#f8fafc',
                bodyColor: '#cbd5e1',
                borderColor: '#334155',
                borderWidth: 1,
                callbacks: {
                    label: function (context) {
                        return `${context.dataset.label}: ${context.parsed.y}${unit}`;
                    }
                }
            }
        },
        scales: {
            x: {
                grid: { color: 'rgba(255, 255, 255, 0.05)' },
                ticks: { color: '#64748b', font: { family: "'JetBrains Mono', monospace", size: 10 } }
            },
            y: {
                min: minVal,
                max: maxVal,
                grid: { color: 'rgba(255, 255, 255, 0.05)' },
                ticks: {
                    color: '#64748b',
                    stepSize: stepSize || undefined,
                    font: { family: "'JetBrains Mono', monospace", size: 10 },
                    callback: (val) => `${val}${unit}`
                }
            }
        }
    };
}

/* --------------------------------------------------------------------------
   Time-Range Selector Logic & Chart History Management
   -------------------------------------------------------------------------- */
function initTimeRangeSelector() {
    const container = document.getElementById('dashboardTimeRange');
    if (!container) return;
    const buttons = container.querySelectorAll('.time-range-btn');
    buttons.forEach(btn => {
        btn.addEventListener('click', async () => {
            const range = btn.getAttribute('data-range') || 'live';
            if (currentDashboardRange === range) return;
            currentDashboardRange = range;
            isRangeJustChanged = true;
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            await pollRealtimeStatus();
        });
    });
}

function applyChartHistory(history) {
    if (!history) return;
    if (cpuMemChart) {
        cpuMemChart.data.labels = [...(history.labels || [])];
        cpuMemChart.data.datasets[0].data = [...(history.cpu || [])];
        cpuMemChart.data.datasets[1].data = [...(history.mem || [])];
        cpuMemChart.update('none');
    }
    if (trafficChart) {
        trafficChart.data.labels = [...(history.labels || [])];
        trafficChart.data.datasets[0].data = [...(history.ingress || [])];
        trafficChart.data.datasets[1].data = [...(history.egress || [])];
        trafficChart.update('none');
    }
}

/* --------------------------------------------------------------------------
   Real-Time Polling & Connection Health
   -------------------------------------------------------------------------- */
async function pollRealtimeStatus() {
    const indicator = document.querySelector('.status-indicator');
    const statusText = indicator ? indicator.querySelector('.status-text') : null;

    try {
        const response = await fetch(`/api/status?range=${encodeURIComponent(currentDashboardRange)}`, { cache: 'no-store' });
        if (!response.ok) {
            handleServerDisconnected(indicator, statusText);
            return;
        }

        const data = await response.json();
        handleServerConnected(indicator, statusText);
        updateDashboardView(data);
    } catch (error) {
        // Server backend offline / down: PAUSE charts & show disconnected indicator
        handleServerDisconnected(indicator, statusText);
    }
}

function handleServerConnected(indicator, statusText) {
    if (indicator) {
        indicator.classList.remove('is-offline');
        indicator.setAttribute('title', 'Polling Engine Terhubung Normal');
    }
    if (statusText) {
        statusText.textContent = 'LIVE POLLING';
    }
}

function handleServerDisconnected(indicator, statusText) {
    if (indicator) {
        indicator.classList.add('is-offline');
        indicator.setAttribute('title', 'Polling Engine Terputus');
    }
    if (statusText) {
        statusText.textContent = 'POLLING STOPPED';
    }
    // CATATAN: Tidak ada push data palsu/dummy ke grafik saat server offline!
    // Grafik tetap diam mempertahankan data terakhir (pause).
}

function pushChartData(chart, label, values) {
    if (!chart) return;
    chart.data.labels.push(label);
    values.forEach((val, idx) => {
        if (chart.data.datasets[idx]) {
            chart.data.datasets[idx].data.push(val);
        }
    });

    if (chart.data.labels.length > MAX_CHART_POINTS) {
        chart.data.labels.shift();
        chart.data.datasets.forEach(ds => ds.data.shift());
    }
    chart.update('none');
}

function updateDashboardView(data) {
    if (data.summary) {
        const kpiTot = document.getElementById('kpiTotal');
        const kpiOn = document.getElementById('kpiOnline');
        const kpiOff = document.getElementById('kpiOffline');
        const kpiAlt = document.getElementById('kpiAlerts');

        if (kpiTot) kpiTot.textContent = data.summary.total_devices;
        if (kpiOn) kpiOn.textContent = data.summary.devices_online;
        if (kpiOff) kpiOff.textContent = data.summary.devices_offline;
        if (kpiAlt) kpiAlt.textContent = data.summary.active_alerts;

        // Update filter badge counts
        const filterAll = document.querySelector('.badge-filter[data-filter="all"]');
        const filterUp = document.querySelector('.badge-filter[data-filter="UP"]');
        const filterDown = document.querySelector('.badge-filter[data-filter="DOWN"]');
        if (filterAll) filterAll.textContent = `Semua (${data.summary.total_devices})`;
        if (filterUp) filterUp.textContent = `Online (${data.summary.devices_online})`;
        if (filterDown) filterDown.textContent = `Offline (${data.summary.devices_offline})`;
    }

    if (data.metrics) {
        const timeLabel = data.timestamp;
        const ingress = data.metrics.ingress_traffic !== undefined ? data.metrics.ingress_traffic : data.metrics.total_traffic;
        const egress = data.metrics.egress_traffic !== undefined ? data.metrics.egress_traffic : Math.round(data.metrics.total_traffic * 0.35);

        if (currentDashboardRange === 'live') {
            if (isRangeJustChanged || (cpuMemChart && cpuMemChart.data.labels.length === 0)) {
                if (data.history) {
                    applyChartHistory(data.history);
                }
                isRangeJustChanged = false;
            } else {
                pushChartData(cpuMemChart, timeLabel, [data.metrics.avg_cpu, data.metrics.avg_mem]);
                pushChartData(trafficChart, timeLabel, [ingress, egress]);
            }
        } else {
            // Historical range (1h, 12h, 24h)
            if (data.history) {
                applyChartHistory(data.history);
            }
            isRangeJustChanged = false;
        }
    }

    // Dynamic real-time update of monitored devices table
    if (data.devices && data.devices.length > 0) {
        renderDeviceTable(data.devices);
    }

    // Dynamic real-time update of active alerts stream
    if (data.alerts !== undefined) {
        renderAlertsStream(data.alerts);
    }
}

function renderDeviceTable(devices) {
    const tbody = document.getElementById('deviceTableBody');
    if (!tbody) return;

    let html = '';
    devices.forEach(dev => {
        const vendorClass = (dev.vendor || '').toLowerCase();
        const vendorInitial = (dev.vendor || 'D')[0].toUpperCase();
        const isUp = dev.status === 'UP';
        const statusBadge = isUp
            ? `<span class="status-badge badge-up"><span class="badge-dot-green"></span> UP</span>`
            : `<span class="status-badge badge-down"><span class="badge-dot-red"></span> DOWN</span>`;

        const metricContent = isUp
            ? `<div class="metric-bars">
                <div class="mini-bar-row">
                    <span class="mini-lbl">C:</span>
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill fill-cpu" style="width: ${dev.cpu}%"></div>
                    </div>
                    <span class="mini-val">${dev.cpu}%</span>
                </div>
                <div class="mini-bar-row">
                    <span class="mini-lbl">M:</span>
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill fill-mem" style="width: ${dev.mem}%"></div>
                    </div>
                    <span class="mini-val">${dev.mem}%</span>
                </div>
               </div>`
            : `<span class="text-muted">-</span>`;

        html += `
        <tr class="device-row filter-${dev.status}" id="row-dev-${dev.id}"
            data-id="${dev.id}"
            data-name="${dev.name}"
            data-ip="${dev.ip}"
            data-vendor="${dev.vendor}"
            data-site="${dev.site}"
            data-status="${dev.status}">
            <td class="col-name">
                <div class="device-name-wrap">
                    <span class="device-icon-tag ${vendorClass}">${vendorInitial}</span>
                    <strong>${dev.name}</strong>
                </div>
            </td>
            <td class="col-ip"><code>${dev.ip}</code></td>
            <td><span class="vendor-badge badge-${vendorClass}">${dev.vendor}</span></td>
            <td class="col-site">${dev.site}</td>
            <td>${statusBadge}</td>
            <td class="col-metrics">${metricContent}</td>
            <td class="col-uptime">${dev.uptime || 'Unknown'}</td>
            <td class="text-center">
                <a href="/device/${dev.id}" class="btn-action btn-detail">Detail</a>
            </td>
        </tr>`;
    });
    tbody.innerHTML = html;
    applyTableFilters();
}

function renderAlertsStream(alerts) {
    const stream = document.getElementById('alertsStream');
    if (!stream) return;

    if (!alerts || alerts.length === 0) {
        stream.innerHTML = `
            <div style="text-align: center; padding: 40px 10px; color: #64748b;">
                <svg style="width: 40px; height: 40px; stroke: #10b981; fill: none; margin: 0 auto 8px auto; display: block;"
                    viewBox="0 0 24 24">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" stroke-width="2" stroke-linecap="round"
                        stroke-linejoin="round" />
                    <polyline points="22 4 12 14.01 9 11.01" stroke-width="2" stroke-linecap="round"
                        stroke-linejoin="round" />
                </svg>
                <p style="font-size: 0.9rem; font-weight: 500; color: #94a3b8; margin: 0 0 4px 0;">Semua Sistem Normal</p>
                <span style="font-size: 0.75rem; color: #64748b;">Tidak ada alert aktif yang memerlukan mitigasi</span>
            </div>
        `;
        return;
    }

    let html = '';
    alerts.forEach(alert => {
        const sevLower = (alert.severity || 'warning').toLowerCase();
        const badgeClass = alert.severity === 'CRITICAL' ? 'badge-crit' : 'badge-warn';
        const isAck = alert.acknowledged;

        html += `
        <div class="alert-card card-severity-${sevLower} ${isAck ? 'is-ack' : ''}" id="alert-card-${alert.id}">
            <div class="alert-card-header">
                <div class="alert-title-wrap">
                    <span class="alert-severity-badge ${badgeClass}">${escapeHtml(alert.severity)}</span>
                    <span class="alert-time">${escapeHtml(alert.triggered_at)}</span>
                </div>
                <span class="alert-id">#${alert.id}</span>
            </div>
            <div class="alert-device-name">
                <strong>${escapeHtml(alert.device_name || 'Device')}</strong> (${escapeHtml(alert.ip || '-')})
            </div>
            <p class="alert-message">${escapeHtml(alert.message)}</p>
            <div class="alert-footer">
                ${isAck ? `
                    <span class="badge-ack-state text-success">✓ Acknowledged</span>
                    <span class="text-muted-xs">${escapeHtml(alert.acknowledged_by || 'Terkonfirmasi')}</span>
                ` : `
                    <span class="badge-ack-state text-warning">● Menunggu ACK</span>
                    <span class="text-muted-xs" style="font-size: 11px;">via Bot Telegram</span>
                `}
            </div>
        </div>`;
    });
    stream.innerHTML = html;
}

/* --------------------------------------------------------------------------
   Acknowledge (ACK) Alert Action
   -------------------------------------------------------------------------- */
async function acknowledgeAlert(alertId) {
    // If online server is running
    if (window.location.protocol !== 'file:') {
        try {
            const response = await fetch(`/api/ack/${alertId}`, { method: 'POST' });
            const resData = await response.json();
        } catch (e) {
            console.warn('API error, using local UI update:', e);
        }
    }

    // Immediate UI update in both offline and online mode
    const card = document.getElementById(`alert-card-${alertId}`);
    if (card) {
        card.classList.add('is-ack');
        const footer = card.querySelector('.alert-footer');
        if (footer) {
            footer.innerHTML = `
                <span class="badge-ack-state text-success">✓ Acknowledged</span>
                <span class="text-muted-xs">Terkonfirmasi</span>
            `;
        }
    }

    const kpiAlerts = document.getElementById('kpiAlerts');
    if (kpiAlerts) {
        let current = parseInt(kpiAlerts.textContent, 10);
        if (current > 0) kpiAlerts.textContent = current - 1;
    }

    showToast(`Alert #${alertId} berhasil di-acknowledge.`);
}

/* --------------------------------------------------------------------------
   Table & Search Filters
   -------------------------------------------------------------------------- */
function getDevicesList() {
    const rows = document.querySelectorAll('#deviceTableBody .device-row');
    const list = [];
    rows.forEach(r => {
        list.push({
            id: r.getAttribute('data-id') || (r.id ? r.id.replace('row-dev-', '') : ''),
            name: r.getAttribute('data-name') || r.querySelector('.device-name-wrap strong')?.textContent.trim() || '',
            ip: r.getAttribute('data-ip') || r.querySelector('.col-ip code')?.textContent.trim() || '',
            vendor: r.getAttribute('data-vendor') || r.querySelector('.vendor-badge')?.textContent.trim() || '',
            site: r.getAttribute('data-site') || r.querySelector('.col-site')?.textContent.trim() || '',
            status: r.getAttribute('data-status') || (r.classList.contains('filter-UP') ? 'UP' : 'DOWN')
        });
    });
    return list;
}

function updateSearchDropdown(query) {
    const dropdown = document.getElementById('searchResultsDropdown');
    const clearBtn = document.getElementById('clearSearchBtn');
    if (!dropdown) return;

    if (clearBtn) {
        clearBtn.style.display = query ? 'flex' : 'none';
    }

    if (!query) {
        dropdown.style.display = 'none';
        dropdown.innerHTML = '';
        return;
    }

    const devices = getDevicesList();
    // Filter khusus berdasarkan Nama Vendor atau Site
    const matches = devices.filter(d =>
        (d.vendor && d.vendor.toLowerCase().includes(query)) ||
        (d.site && d.site.toLowerCase().includes(query))
    );

    if (matches.length > 0) {
        let itemsHtml = '';
        matches.forEach(dev => {
            const vendorClass = (dev.vendor || '').toLowerCase();
            const vendorInitial = (dev.vendor || 'D')[0].toUpperCase();

            // Status UP atau DOWN dihilangkan pada search bar dropdown
            itemsHtml += `
            <li class="search-dropdown-item" onclick="window.location.href='/device/${dev.id}'">
                <div class="search-item-info">
                    <span class="device-icon-tag ${vendorClass}">${vendorInitial}</span>
                    <div>
                        <div class="search-item-name">${escapeHtml(dev.name)}</div>
                        <div class="search-item-meta">
                            <span class="vendor-badge badge-${vendorClass}" style="padding: 1px 6px; font-size: 10px;">${escapeHtml(dev.vendor)}</span>
                            <span>•</span>
                            <span style="color: #cbd5e1; font-weight: 500;">Site: ${escapeHtml(dev.site)}</span>
                            <span>•</span>
                            <span class="search-item-ip">${escapeHtml(dev.ip)}</span>
                        </div>
                    </div>
                </div>
            </li>`;
        });

        dropdown.innerHTML = `
            <div class="search-dropdown-header">
                <span>Ditemukan ${matches.length} Perangkat</span>
            </div>
            <ul class="search-dropdown-list">
                ${itemsHtml}
            </ul>
        `;
        dropdown.style.display = 'block';
    } else {
        dropdown.innerHTML = `
            <div class="search-dropdown-header">
                <span>Ditemukan 0 Perangkat</span>
            </div>
            <div class="search-dropdown-empty">
                Tidak ada perangkat dengan vendor atau site "<strong>${escapeHtml(query)}</strong>".
            </div>
        `;
        dropdown.style.display = 'block';
    }
}

function scrollToDevicesTable() {
    const dropdown = document.getElementById('searchResultsDropdown');
    if (dropdown) dropdown.style.display = 'none';
    const tableSection = document.getElementById('monitored-devices');
    if (tableSection) {
        tableSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
}

function applyTableFilters() {
    const searchInput = document.getElementById('globalSearch');
    const query = searchInput ? searchInput.value.toLowerCase().trim() : '';

    const activeFilterBtn = document.querySelector('.badge-filter.active');
    const statusFilter = activeFilterBtn ? activeFilterBtn.getAttribute('data-filter') : 'all';

    const clearBtn = document.getElementById('clearSearchBtn');
    if (clearBtn) {
        clearBtn.style.display = query !== '' ? 'flex' : 'none';
    }

    const rows = document.querySelectorAll('#deviceTableBody .device-row');
    let visibleCount = 0;

    rows.forEach(row => {
        const vendor = (row.getAttribute('data-vendor') || '').toLowerCase();
        const site = (row.getAttribute('data-site') || '').toLowerCase();

        // Pencarian khusus kriteria Vendor dan Site saja
        const matchesVendorOrSite = !query || vendor.includes(query) || site.includes(query);

        const rowStatus = row.getAttribute('data-status') || (row.classList.contains('filter-UP') ? 'UP' : 'DOWN');
        const matchesStatus = statusFilter === 'all' || rowStatus === statusFilter;

        if (matchesVendorOrSite && matchesStatus) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    });

    // Handle empty state feedback di tabel
    const tbody = document.getElementById('deviceTableBody');
    let emptyRow = document.getElementById('noResultsRow');
    if (visibleCount === 0 && rows.length > 0) {
        let emptyMessage = '';
        if (query && statusFilter !== 'all') {
            const statusText = statusFilter === 'UP' ? 'online' : 'offline';
            emptyMessage = `Tidak ada perangkat ${statusText} dengan vendor atau site yang cocok dengan ${escapeHtml(query)}.`;
        } else if (query) {
            emptyMessage = `Tidak ada perangkat dengan vendor atau site yang cocok dengan ${escapeHtml(query)}.`;
        } else if (statusFilter === 'DOWN') {
            emptyMessage = `Tidak ada perangkat yang sedang offline.`;
        } else if (statusFilter === 'UP') {
            emptyMessage = `Tidak ada perangkat yang sedang online.`;
        } else {
            emptyMessage = `Tidak ada perangkat yang tersedia.`;
        }

        if (!emptyRow && tbody) {
            emptyRow = document.createElement('tr');
            emptyRow.id = 'noResultsRow';
            tbody.appendChild(emptyRow);
        }
        if (emptyRow) {
            emptyRow.innerHTML = `<td colspan="8" class="text-center text-muted" style="padding: 28px; font-size: 13px;">${emptyMessage}</td>`;
        }
    } else if (emptyRow) {
        emptyRow.remove();
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g,
        tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
    );
}

function setupTableFilters() {
    const filterButtons = document.querySelectorAll('.badge-filter');
    filterButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            filterButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            applyTableFilters();
        });
    });
}

function setupSearchFilter() {
    const searchInput = document.getElementById('globalSearch');
    const clearBtn = document.getElementById('clearSearchBtn');
    const dropdown = document.getElementById('searchResultsDropdown');
    if (!searchInput) return;

    searchInput.addEventListener('input', () => {
        const query = searchInput.value.toLowerCase().trim();
        applyTableFilters();
        updateSearchDropdown(query);
    });

    searchInput.addEventListener('focus', () => {
        const query = searchInput.value.toLowerCase().trim();
        if (query) {
            updateSearchDropdown(query);
        }
    });

    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            searchInput.value = '';
            clearBtn.style.display = 'none';
            if (dropdown) dropdown.style.display = 'none';
            applyTableFilters();
            searchInput.focus();
        });
    }

    // Close dropdown on click outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.nav-search')) {
            if (dropdown) dropdown.style.display = 'none';
        }
    });

    // Enter key: scroll to table and hide dropdown
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            scrollToDevicesTable();
            if (dropdown) dropdown.style.display = 'none';
        } else if (e.key === 'Escape') {
            if (dropdown) dropdown.style.display = 'none';
            searchInput.blur();
        }
    });
}


/* --------------------------------------------------------------------------
   Toast Notifications
   -------------------------------------------------------------------------- */
function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.style.borderLeft = type === 'error' ? '4px solid #ef4444' : '4px solid #10b981';
    toast.innerHTML = `
        <span>${type === 'error' ? '❌' : '✅'}</span>
        <span>${message}</span>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}
