/**
 * Device Detail JavaScript - PT Agiva Indonesia Network Automation
 * Real-time metric polling, manual refresh interaction, and 8-card live charts.
 */

// 4 Main Chart & Visual instances (Model 1: 2 baris x 2 panel)
let chartCpuMem = null;
let chartTraffic = null;
let chartBuffers = null;
let chartErrorsDrops = null;

// 4 Timeline Navigator instances
let navCpuMem = null;
let navTraffic = null;
let navBuffers = null;
let navErrorsDrops = null;

let isNavBatchUpdating = false;
let lastDeviceRawData = null;
let currentFilter = 'all';
let currentSearch = '';
let currentDeviceRange = 'live';

document.addEventListener('DOMContentLoaded', () => {
    initPortControls();
    initTimeRangeSelector();
    fetchDeviceMetrics(false);
    // Real-time polling per 5 detik
    setInterval(() => fetchDeviceMetrics(false), 5000);
});

function initTimeRangeSelector() {
    const container = document.getElementById('deviceTimeRange');
    if (!container) return;
    const buttons = container.querySelectorAll('.time-range-btn');
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            const range = btn.getAttribute('data-range') || 'live';
            if (currentDeviceRange === range) return;
            currentDeviceRange = range;
            buttons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            fetchDeviceMetrics(false);
        });
    });
}

function initPortControls() {
    const tabs = document.querySelectorAll('#portFilterTabs .port-filter-btn');
    tabs.forEach(btn => {
        btn.addEventListener('click', () => {
            tabs.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentFilter = btn.getAttribute('data-filter') || 'all';
            applyPortFilters();
        });
    });

    const searchInput = document.getElementById('portSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            currentSearch = (e.target.value || '').trim().toLowerCase();
            applyPortFilters();
        });
    }
}

function applyPortFilters() {
    const rows = document.querySelectorAll('#portsTableBody .port-row');
    rows.forEach(row => {
        const status = row.getAttribute('data-status') || '';
        const type = row.getAttribute('data-type') || '';
        const searchData = row.getAttribute('data-search') || '';

        let matchesTab = true;
        if (currentFilter === 'UP') {
            matchesTab = (status === 'UP');
        } else if (currentFilter === 'DOWN') {
            matchesTab = (status === 'DOWN');
        } else if (currentFilter === 'sfp') {
            matchesTab = (type === 'sfp');
        } else if (currentFilter === 'poe') {
            matchesTab = (type === 'poe');
        }

        let matchesSearch = true;
        if (currentSearch) {
            matchesSearch = searchData.includes(currentSearch);
        }

        if (matchesTab && matchesSearch) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}

function updateConnectionStatus(isOnline) {
    const indicator = document.querySelector('.status-indicator');
    if (!indicator) return;
    const textEl = indicator.querySelector('.status-text');

    if (isOnline) {
        indicator.classList.remove('is-offline');
        indicator.setAttribute('title', 'Polling Engine Terhubung Normal');
        if (textEl) textEl.textContent = 'LIVE POLLING';
    } else {
        indicator.classList.add('is-offline');
        indicator.setAttribute('title', 'Polling Engine Terputus');
        if (textEl) textEl.textContent = 'POLLING STOPPED';
    }
}

function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    const icon = type === 'success' ? '✅' : '⚠️';
    toast.innerHTML = `
        <span style="font-size: 16px;">${icon}</span>
        <div class="toast-content" style="flex:1;">
            <div class="toast-title">${type === 'success' ? 'Berhasil' : 'Peringatan'}</div>
            <div class="toast-message">${message}</div>
        </div>
        <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
    `;
    container.appendChild(toast);
    setTimeout(() => {
        if (toast.parentElement) toast.remove();
    }, 3000);
}

async function fetchDeviceMetrics(isManual = false) {
    const btn = document.getElementById('btnRefreshDevice') || document.querySelector('.btn-refresh');
    const originalBtnHtml = `
        <svg class="refresh-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" style="display:inline-block; vertical-align:middle; margin-right:4px;">
            <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path>
        </svg>
        <span>Refresh Data</span>
    `;

    if (isManual && btn) {
        btn.disabled = true;
        btn.innerHTML = `
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" style="display:inline-block; vertical-align:middle; margin-right:4px; animation: spin 0.8s linear infinite;">
                <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path>
            </svg>
            <span>Memperbarui...</span>
        `;
    }

    try {
        const devId = typeof CURRENT_DEVICE_ID !== 'undefined' ? CURRENT_DEVICE_ID : 1;
        const res = await fetch(`/api/device/${devId}/metrics?range=${encodeURIComponent(currentDeviceRange)}`, { cache: 'no-store' });
        if (!res.ok) {
            updateConnectionStatus(false);
            if (isManual && btn) {
                btn.disabled = false;
                btn.innerHTML = originalBtnHtml;
                showToast('Gagal memperbarui data: Endpoint metrik tidak merespon.', 'warning');
            }
            return;
        }

        const data = await res.json();
        updateConnectionStatus(true);

        // Update Quick Stat values
        if (data.current_cpu !== undefined) {
            const cpuEl = document.getElementById('currCpuVal');
            if (cpuEl) cpuEl.textContent = `${data.current_cpu}%`;
            const valCpu = document.getElementById('valCpu');
            if (valCpu) valCpu.textContent = `${data.current_cpu}%`;
        }
        if (data.current_memory !== undefined) {
            const memEl = document.getElementById('currMemVal');
            if (memEl) memEl.textContent = `${data.current_memory}%`;
            const valMemory = document.getElementById('valMemory');
            if (valMemory) valMemory.textContent = `${data.current_memory}%`;
        }
        if (data.current_traffic !== undefined) {
            const trfEl = document.getElementById('currTrafficVal');
            if (trfEl) trfEl.textContent = `${data.current_traffic} Mbps`;
            const valTrf = document.getElementById('valThroughput');
            if (valTrf) valTrf.textContent = `${data.current_traffic}`;
        }
        if (data.current_packet_buffers !== undefined) {
            const pbEl = document.getElementById('valPacketBuffers');
            if (pbEl) pbEl.textContent = `${data.current_packet_buffers}%`;
        }
        if (data.current_message_buffers !== undefined) {
            const mbEl = document.getElementById('valMessageBuffers');
            if (mbEl) mbEl.textContent = `${data.current_message_buffers}%`;
        }
        if (data.current_rx_errors !== undefined) {
            const reEl = document.getElementById('valRxErrors');
            if (reEl) reEl.textContent = `${data.current_rx_errors}`;
        }
        if (data.current_tx_errors !== undefined) {
            const teEl = document.getElementById('valTxErrors');
            if (teEl) teEl.textContent = `${data.current_tx_errors}`;
        }
        if (data.current_tx_drops !== undefined) {
            const tdEl = document.getElementById('valTxDrops');
            if (tdEl) tdEl.textContent = `${data.current_tx_drops}`;
        }
        if (data.uptime) {
            const uptimeEl = document.getElementById('currUptimeVal');
            if (uptimeEl) uptimeEl.textContent = data.uptime;
        }
        if (data.summary && data.summary.up_ports !== undefined) {
            const portUpEl = document.getElementById('currPortUpVal');
            if (portUpEl) portUpEl.textContent = `${data.summary.up_ports} / ${data.summary.total_ports}`;
        }
        if (data.specs && data.specs.poe_consumption) {
            const poeEl = document.getElementById('currPoeVal');
            if (poeEl) poeEl.textContent = data.specs.poe_consumption;
        }

        renderDeviceCharts(data);

        if (isManual && btn) {
            btn.innerHTML = `
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="#ffffff" stroke-width="2.5" style="display:inline-block; vertical-align:middle; margin-right:4px;">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                <span style="color: #ffffff;">Terperbarui</span>
            `;
            setTimeout(() => {
                btn.disabled = false;
                btn.innerHTML = originalBtnHtml;
            }, 1000);
        }
    } catch (err) {
        updateConnectionStatus(false);
        if (isManual && btn) {
            btn.disabled = false;
            btn.innerHTML = originalBtnHtml;
            showToast('Gagal menghubungi backend server.', 'warning');
        }
    }
}

function drawRadialGauge(canvasId, value, maxVal, color) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const size = 104;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    canvas.style.width = `${size}px`;
    canvas.style.height = `${size}px`;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, size, size);

    const centerX = size / 2;
    const centerY = size / 2;
    const radius = (size / 2) - 9;
    const startAngle = 0.75 * Math.PI; // 135 degrees
    const endAngle = 2.25 * Math.PI;   // 405 degrees (270 deg sweep)
    const sweep = endAngle - startAngle;

    // Background track
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius, startAngle, endAngle, false);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
    ctx.lineWidth = 8;
    ctx.lineCap = 'round';
    ctx.stroke();

    // Active progress arc
    const pct = Math.min(1, Math.max(0, value / maxVal));
    if (pct > 0.005) {
        const currentAngle = startAngle + (sweep * pct);
        ctx.beginPath();
        ctx.arc(centerX, centerY, radius, startAngle, currentAngle, false);
        ctx.strokeStyle = color;
        ctx.lineWidth = 8;
        ctx.lineCap = 'round';
        ctx.shadowColor = color;
        ctx.shadowBlur = 6;
        ctx.stroke();
        ctx.shadowBlur = 0;
    }
}

function createOrUpdateDualChart(existingChart, ctx, labels, ds1, ds2, unit = '', suggestedMax = 100, customTooltip = null) {
    if (!ctx) return null;

    const visibleCount = (labels || []).length;
    const dynamicPointRadius = visibleCount <= 45 ? 3 : (visibleCount <= 85 ? 1.5 : 0);
    const hoverPointRadius = dynamicPointRadius > 0 ? dynamicPointRadius + 3 : 5;

    const allVals = [...(ds1.data || []), ...(ds2.data || [])];
    const maxVal = allVals.length > 0 ? Math.max(...allVals) : 0;
    let actualMax = suggestedMax;
    if (maxVal > suggestedMax) {
        actualMax = Math.ceil((maxVal * 1.25) / 10) * 10;
    }

    if (existingChart) {
        existingChart.data.labels = labels;
        existingChart.data.datasets[0].data = ds1.data;
        existingChart.data.datasets[1].data = ds2.data;
        existingChart.data.datasets[0].pointRadius = dynamicPointRadius;
        existingChart.data.datasets[1].pointRadius = dynamicPointRadius;
        existingChart.data.datasets[0].pointHoverRadius = hoverPointRadius;
        existingChart.data.datasets[1].pointHoverRadius = hoverPointRadius;
        if (customTooltip && existingChart.options.plugins && existingChart.options.plugins.tooltip) {
            if (typeof customTooltip === 'object') {
                Object.assign(existingChart.options.plugins.tooltip.callbacks, customTooltip);
            } else {
                existingChart.options.plugins.tooltip.callbacks.label = customTooltip;
            }
        }
        if (existingChart.options.scales.y) {
            existingChart.options.scales.y.suggestedMax = actualMax;
            existingChart.options.scales.y.max = actualMax;
        }
        existingChart.update('none');
        return existingChart;
    }

    const gradCyan = ctx.getContext('2d').createLinearGradient(0, 0, 0, 140);
    gradCyan.addColorStop(0, 'rgba(6, 182, 212, 0.35)');
    gradCyan.addColorStop(1, 'rgba(6, 182, 212, 0.0)');

    const gradOrange = ctx.getContext('2d').createLinearGradient(0, 0, 0, 140);
    gradOrange.addColorStop(0, 'rgba(249, 115, 22, 0.25)');
    gradOrange.addColorStop(1, 'rgba(249, 115, 22, 0.0)');

    return new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: ds1.label,
                    data: ds1.data,
                    borderColor: '#06b6d4',
                    backgroundColor: gradCyan,
                    borderWidth: 2,
                    fill: true,
                    tension: 0.35,
                    pointRadius: dynamicPointRadius,
                    pointHoverRadius: hoverPointRadius,
                    pointBackgroundColor: '#ffffff',
                    pointBorderColor: '#06b6d4',
                    pointBorderWidth: 1.5
                },
                {
                    label: ds2.label,
                    data: ds2.data,
                    borderColor: '#f97316',
                    backgroundColor: gradOrange,
                    borderWidth: 2,
                    fill: true,
                    tension: 0.35,
                    pointRadius: dynamicPointRadius,
                    pointHoverRadius: hoverPointRadius,
                    pointBackgroundColor: '#ffffff',
                    pointBorderColor: '#f97316',
                    pointBorderWidth: 1.5
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: '#18142c',
                    titleColor: '#f8fafc',
                    bodyColor: '#cbd5e1',
                    borderColor: '#2b244d',
                    borderWidth: 1,
                    padding: 8,
                    cornerRadius: 6,
                    callbacks: (customTooltip && typeof customTooltip === 'object')
                        ? customTooltip
                        : {
                            label: typeof customTooltip === 'function' ? customTooltip : function (ctx) {
                                return ` ${ctx.dataset.label}: ${ctx.parsed.y}${unit}`;
                            }
                        }
                }
            },
            scales: {
                x: {
                    display: true,
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: { color: '#64748b', font: { size: 9 }, maxTicksLimit: 6 }
                },
                y: {
                    min: 0,
                    suggestedMax: actualMax,
                    max: actualMax,
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: {
                        color: '#64748b',
                        font: { size: 9 },
                        maxTicksLimit: 4,
                        callback: (val) => `${val}${unit}`
                    }
                }
            }
        }
    });
}

function createOrUpdateBarChart(existingChart, ctx, labels, datasets, suggestedMax = 100, unit = '') {
    if (!ctx) return null;

    const allVals = datasets.flatMap(d => d.data || []);
    const maxVal = allVals.length > 0 ? Math.max(...allVals) : 0;
    let actualMax = suggestedMax;
    if (maxVal > suggestedMax) {
        actualMax = Math.ceil((maxVal * (unit === '%' ? 1.05 : 1.25)) / 10) * 10;
    }

    if (existingChart) {
        existingChart.data.labels = labels;
        datasets.forEach((ds, i) => {
            if (existingChart.data.datasets[i]) {
                existingChart.data.datasets[i].data = ds.data;
            }
        });
        if (existingChart.options.scales.y) {
            existingChart.options.scales.y.suggestedMax = actualMax;
            existingChart.options.scales.y.max = actualMax;
        }
        existingChart.update('none');
        return existingChart;
    }

    return new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: datasets.map(d => ({
                label: d.label,
                data: d.data,
                backgroundColor: d.color,
                borderColor: d.borderColor || d.color,
                borderWidth: 1,
                borderRadius: 2,
                barPercentage: 0.65,
                categoryPercentage: 0.75
            }))
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: '#18142c',
                    titleColor: '#f8fafc',
                    bodyColor: '#cbd5e1',
                    borderColor: '#2b244d',
                    borderWidth: 1,
                    padding: 8,
                    cornerRadius: 6,
                    callbacks: {
                        label: function (ctx) {
                            return ` ${ctx.dataset.label}: ${ctx.parsed.y}${unit}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    display: true,
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: { color: '#64748b', font: { size: 9 }, maxTicksLimit: 6 }
                },
                y: {
                    min: 0,
                    suggestedMax: actualMax,
                    max: actualMax,
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: {
                        color: '#64748b',
                        font: { size: 9 },
                        maxTicksLimit: 4,
                        precision: 0,
                        callback: (val) => `${val}${unit}`
                    }
                }
            }
        }
    });
}

function renderDeviceCharts(data) {
    if (!data) return;
    lastDeviceRawData = data;

    const labels = data.labels || [];
    if (labels.length === 0) return;

    // Pastikan fallback array terisi bila kosong
    if (!data.cpu) data.cpu = labels.map(() => 0);
    if (!data.memory) data.memory = labels.map(() => 0);
    if (!data.traffic) data.traffic = labels.map(() => 0);
    if (!data.traffic_in) data.traffic_in = labels.map(() => 0);
    if (!data.traffic_out) data.traffic_out = labels.map(() => 0);
    if (!data.packet_buffers) data.packet_buffers = labels.map(() => 35.1);
    if (!data.message_buffers) data.message_buffers = labels.map(() => 22.0);
    if (!data.rx_errors) data.rx_errors = labels.map(() => 0);
    if (!data.tx_errors) data.tx_errors = labels.map(() => 0);
    if (!data.tx_drops) data.tx_drops = labels.map(() => 0);

    const navIds = ['navCpuMem', 'navTraffic', 'navBuffers', 'navErrorsDrops'];

    // Jika mode live: sembunyikan semua 4 navigator slider, render seluruh data live
    if (currentDeviceRange === 'live') {
        navIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });
        renderDeviceChartsSlice(data, 0, labels.length - 1);
        return;
    }

    // Mode histori: 1h, 12h, 24h -> Inisialisasi 4 Timeline Navigators jika belum dibuat
    initTimelineNavigators();

    // Pertahankan batas pecahan jendela aktif jika pengguna sedang menyeret slider
    const sampleNav = navCpuMem || navTraffic;
    const preserveFractions = (sampleNav && (sampleNav.isDragging || (sampleNav.fullLabels && sampleNav.fullLabels.length > 0)))
        ? { start: sampleNav.startFrac, end: sampleNav.endFrac }
        : null;

    isNavBatchUpdating = true;
    try {
        if (navCpuMem) navCpuMem.setData(labels, data.cpu, data.memory, preserveFractions);
        if (navTraffic) navTraffic.setData(labels, data.traffic_in, data.traffic_out, preserveFractions);
        if (navBuffers) navBuffers.setData(labels, data.packet_buffers, data.message_buffers, preserveFractions);
        if (navErrorsDrops) navErrorsDrops.setData(labels, data.tx_errors, data.rx_errors, preserveFractions);
    } finally {
        isNavBatchUpdating = false;
    }

    // Sinkronisasi posisi awal seluruh visual slider dan render potongan grafik aktif
    const activeNav = navCpuMem || navTraffic;
    if (activeNav) {
        const total = labels.length;
        const startIdx = Math.min(total - 1, Math.round(activeNav.startFrac * (total - 1)));
        const endIdx = Math.min(total - 1, Math.round(activeNav.endFrac * (total - 1)));
        renderDeviceChartsSlice(data, startIdx, endIdx);
    } else {
        renderDeviceChartsSlice(data, 0, labels.length - 1);
    }
}

function initTimelineNavigators() {
    if (typeof TimelineNavigator === 'undefined') return;

    if (!navCpuMem) {
        const el = document.getElementById('navCpuMem');
        if (el) {
            navCpuMem = new TimelineNavigator({
                containerId: 'navCpuMem',
                color: '#06b6d4',
                secondaryColor: '#f97316',
                unit: '%',
                onWindowChange: (startIdx, endIdx) => {
                    if (isNavBatchUpdating) return;
                    if (lastDeviceRawData) {
                        renderDeviceChartsSlice(lastDeviceRawData, startIdx, endIdx);
                        syncAllNavigators('navCpuMem');
                    }
                }
            });
        }
    }

    if (!navTraffic) {
        const el = document.getElementById('navTraffic');
        if (el) {
            navTraffic = new TimelineNavigator({
                containerId: 'navTraffic',
                color: '#06b6d4',
                secondaryColor: '#f97316',
                unit: ' Mbps',
                onWindowChange: (startIdx, endIdx) => {
                    if (isNavBatchUpdating) return;
                    if (lastDeviceRawData) {
                        renderDeviceChartsSlice(lastDeviceRawData, startIdx, endIdx);
                        syncAllNavigators('navTraffic');
                    }
                }
            });
        }
    }

    if (!navBuffers) {
        const el = document.getElementById('navBuffers');
        if (el) {
            navBuffers = new TimelineNavigator({
                containerId: 'navBuffers',
                color: '#06b6d4',
                secondaryColor: '#f97316',
                unit: '%',
                onWindowChange: (startIdx, endIdx) => {
                    if (isNavBatchUpdating) return;
                    if (lastDeviceRawData) {
                        renderDeviceChartsSlice(lastDeviceRawData, startIdx, endIdx);
                        syncAllNavigators('navBuffers');
                    }
                }
            });
        }
    }

    if (!navErrorsDrops) {
        const el = document.getElementById('navErrorsDrops');
        if (el) {
            navErrorsDrops = new TimelineNavigator({
                containerId: 'navErrorsDrops',
                color: '#06b6d4',
                secondaryColor: '#f97316',
                unit: '',
                onWindowChange: (startIdx, endIdx) => {
                    if (isNavBatchUpdating) return;
                    if (lastDeviceRawData) {
                        renderDeviceChartsSlice(lastDeviceRawData, startIdx, endIdx);
                        syncAllNavigators('navErrorsDrops');
                    }
                }
            });
        }
    }
}

function syncAllNavigators(sourceId) {
    const navs = [navCpuMem, navTraffic, navBuffers, navErrorsDrops];
    const sourceNav = navs.find(n => n && n.container && n.container.id === sourceId);
    if (!sourceNav) return;

    const s = sourceNav.startFrac;
    const e = sourceNav.endFrac;

    navs.forEach(n => {
        if (n && n.container && n.container.id !== sourceId && !n.isDragging) {
            n.updateWindowDOM(s, e);
        }
    });
}

function renderDeviceChartsSlice(data, startIdx, endIdx) {
    if (!data) return;
    const allLabels = data.labels || [];
    if (allLabels.length === 0) return;

    const s = Math.max(0, startIdx);
    const e = Math.min(allLabels.length - 1, endIdx);

    const labels = allLabels.slice(s, e + 1);
    const cpuVals = (data.cpu || []).slice(s, e + 1);
    const memVals = (data.memory || []).slice(s, e + 1);
    const inVals = (data.traffic_in || []).slice(s, e + 1);
    const outVals = (data.traffic_out || []).slice(s, e + 1);
    const trfVals = (data.traffic || []).slice(s, e + 1);
    const pbVals = (data.packet_buffers || []).slice(s, e + 1);
    const mbVals = (data.message_buffers || []).slice(s, e + 1);
    const txVals = (data.tx_errors || []).slice(s, e + 1);
    const rxVals = (data.rx_errors || []).slice(s, e + 1);
    const tdVals = (data.tx_drops || []).slice(s, e + 1);

    // 1. Chart CPU & Memory (Dual-Line)
    chartCpuMem = createOrUpdateDualChart(
        chartCpuMem,
        document.getElementById('chartCpuMem'),
        labels,
        { label: 'CPU', data: cpuVals },
        { label: 'Memory', data: memVals },
        '%',
        100
    );

    // 2. Chart Traffic Ingress & Egress (Dual-Line with Ingress and Egress only)
    const trafficTooltip = {
        beforeBody: () => '',
        label: function (ctx) {
            if (ctx.datasetIndex === 0) {
                return ` • Ingress (Rx): ${ctx.parsed.y} Mbps`;
            }
            return ` • Egress (Tx): ${ctx.parsed.y} Mbps`;
        }
    };

    chartTraffic = createOrUpdateDualChart(
        chartTraffic,
        document.getElementById('chartTraffic'),
        labels,
        { label: 'Ingress', data: inVals },
        { label: 'Egress', data: outVals },
        ' Mbps',
        100,
        trafficTooltip
    );

    // 3. Chart Buffer Hardware Switch (Spike Bar Chart Histogram persis Integritas Transmisi Fisik)
    chartBuffers = createOrUpdateBarChart(
        chartBuffers,
        document.getElementById('chartBuffers'),
        labels,
        [
            { label: 'Packet Buffer', data: pbVals, color: 'rgba(6, 182, 212, 0.85)', borderColor: '#06b6d4' },
            { label: 'Message Buffer', data: mbVals, color: 'rgba(249, 115, 22, 0.85)', borderColor: '#f97316' }
        ],
        100,
        '%'
    );

    // 4. Spike Bar Chart (Integritas Transmisi Fisik)
    chartErrorsDrops = createOrUpdateBarChart(
        chartErrorsDrops,
        document.getElementById('chartErrorsDrops'),
        labels,
        [
            { label: 'TX Errors', data: txVals, color: 'rgba(6, 182, 212, 0.85)', borderColor: '#06b6d4' },
            { label: 'RX Errors', data: rxVals, color: 'rgba(249, 115, 22, 0.85)', borderColor: '#f97316' },
            { label: 'TX Drops', data: tdVals, color: 'rgba(234, 179, 8, 0.85)', borderColor: '#eab308' }
        ],
        100,
        ''
    );
}
