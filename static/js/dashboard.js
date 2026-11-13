/**
 * Dashboard JavaScript - PT Agiva Indonesia Network Automation
 * Supports:
 * 1. Offline Mode with localStorage & fallback cache (when app.py backend is offline)
 * 2. Online http:// server mode (polls /api/status live JSON endpoint)
 */

let cpuMemChart = null;
let trafficChart = null;
let cpuMemTimelineNav = null;
let trafficTimelineNav = null;
let lastDashboardHistory = null;
let currentDashboardRange = 'live';
let isRangeJustChanged = false;
let offlineToastShown = false;
let isPrefetchingRanges = false;
const MAX_CHART_POINTS = 18;

const STORAGE_KEYS = {
    DASHBOARD_DATA: 'agiva_dashboard_latest_data',
    CHART_PREFIX: 'agiva_chart_history_', // agiva_chart_history_live, 1h, 12h, 24h
    WAN_PREFIX: 'agiva_wan_history_',     // agiva_wan_history_live, 1h, 12h, 24h
    LAST_UPDATED: 'agiva_dashboard_last_updated'
};

/* --------------------------------------------------------------------------
   Local Storage & Offline Data Management
   -------------------------------------------------------------------------- */
function saveDashboardDataToStorage(data) {
    if (!data) return;
    try {
        const payload = {
            summary: data.summary,
            metrics: data.metrics,
            wan: data.wan,
            devices: data.devices,
            alerts: data.alerts,
            timestamp: data.timestamp || new Date().toTimeString().split(' ')[0],
            savedAt: new Date().toISOString()
        };
        localStorage.setItem(STORAGE_KEYS.DASHBOARD_DATA, JSON.stringify(payload));
        localStorage.setItem(STORAGE_KEYS.LAST_UPDATED, payload.savedAt);

        if (data.history) {
            saveChartHistoryToStorage(data.range || currentDashboardRange, data.history);
        }
        if (data.wan_history) {
            saveWanHistoryToStorage(data.range || currentDashboardRange, data.wan_history);
        }
    } catch (e) {
        console.warn('Failed to save dashboard cache to localStorage:', e);
    }
}

function saveWanHistoryToStorage(range, history) {
    if (!history || !history.labels || history.labels.length === 0) return;
    try {
        localStorage.setItem(STORAGE_KEYS.WAN_PREFIX + range, JSON.stringify(history));
    } catch (e) {
        console.warn('Failed to save WAN chart cache:', e);
    }
}

function loadWanHistoryFromStorage(range) {
    try {
        const raw = localStorage.getItem(STORAGE_KEYS.WAN_PREFIX + range);
        if (raw) return JSON.parse(raw);
        const liveRaw = localStorage.getItem(STORAGE_KEYS.WAN_PREFIX + 'live');
        if (liveRaw) return JSON.parse(liveRaw);
    } catch (e) {
        console.warn('Error reading localStorage WAN chart:', e);
    }
    return null;
}

function saveChartHistoryToStorage(range, history) {
    if (!history || !history.labels || history.labels.length === 0) return;
    try {
        localStorage.setItem(STORAGE_KEYS.CHART_PREFIX + range, JSON.stringify(history));
    } catch (e) {
        console.warn('Failed to save chart cache:', e);
    }
}

function loadDashboardDataFromStorage() {
    try {
        const raw = localStorage.getItem(STORAGE_KEYS.DASHBOARD_DATA);
        if (raw) return JSON.parse(raw);
    } catch (e) {
        console.warn('Error reading localStorage dashboard:', e);
    }
    return null;
}

function loadChartHistoryFromStorage(range) {
    try {
        const raw = localStorage.getItem(STORAGE_KEYS.CHART_PREFIX + range);
        if (raw) return JSON.parse(raw);

        // Fallback to 'live' if requested range not found
        const liveRaw = localStorage.getItem(STORAGE_KEYS.CHART_PREFIX + 'live');
        if (liveRaw) return JSON.parse(liveRaw);
    } catch (e) {
        console.warn('Error reading localStorage chart:', e);
    }
    return null;
}

async function prefetchHistoricalRanges() {
    if (isPrefetchingRanges) return;
    isPrefetchingRanges = true;
    const ranges = ['1h', '12h', '24h'];
    for (const r of ranges) {
        if (!localStorage.getItem(STORAGE_KEYS.CHART_PREFIX + r)) {
            try {
                const res = await fetch(`/api/status?range=${encodeURIComponent(r)}`, { cache: 'no-store' });
                if (res.ok) {
                    const data = await res.json();
                    if (data && data.history) {
                        saveChartHistoryToStorage(r, data.history);
                    }
                    if (data && data.wan_history) {
                        saveWanHistoryToStorage(r, data.wan_history);
                    }
                }
            } catch (e) {
                // Ignore silent prefetch error
            }
        }
    }
}

function cleanupServiceWorker() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.getRegistrations().then(registrations => {
            for (const r of registrations) {
                r.unregister();
            }
        });
    }
    if ('caches' in window) {
        caches.keys().then(keys => keys.forEach(k => caches.delete(k)));
    }
}

function restoreDashboardFromStorageIfEmpty() {
    const cachedData = loadDashboardDataFromStorage();
    if (!cachedData) return;

    const kpiTot = document.getElementById('kpiTotal');
    const tbody = document.getElementById('deviceTableBody');
    const isEmptyTable = !tbody || tbody.children.length === 0 || (tbody.children.length === 1 && tbody.children[0].textContent.includes('No devices'));

    if (isEmptyTable || (kpiTot && (kpiTot.textContent === '0' || !kpiTot.textContent.trim()))) {
        updateDashboardView(cachedData);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    initTimeRangeSelector();
    setupTableFilters();
    setupWanActions();

    // Restore table data and KPIs from cache if not yet populated
    restoreDashboardFromStorageIfEmpty();

    // Clear service worker so browser displays standard disconnected screen when app.py terminates
    cleanupServiceWorker();

    // Poll immediately on page load
    pollRealtimeStatus();

    // Polling interval (every 5 seconds)
    setInterval(pollRealtimeStatus, 5000);
});

/* --------------------------------------------------------------------------
   Chart.js Initialization
   -------------------------------------------------------------------------- */
function initCharts() {
    let initData = window.INITIAL_CHART_DATA || { labels: [], cpu: [], mem: [], ingress: [], egress: [] };

    // Validate whether initial data contains valid datapoints
    const hasValidInitialData = initData && initData.labels && initData.labels.length > 1;

    if (hasValidInitialData) {
        saveChartHistoryToStorage('live', initData);
    } else {
        // Retrieve latest chart data from localStorage or fallback
        const cachedChart = loadChartHistoryFromStorage('live');
        if (cachedChart && cachedChart.labels && cachedChart.labels.length > 0) {
            initData = cachedChart;
        }
    }

    // 1. CPU & Memory Chart
    const ctxCpuMem = document.getElementById('cpuMemChart');
    if (ctxCpuMem) {
        const gradientCpu = ctxCpuMem.getContext('2d').createLinearGradient(0, 0, 0, 220);
        gradientCpu.addColorStop(0, 'rgba(6, 182, 212, 0.35)');
        gradientCpu.addColorStop(1, 'rgba(6, 182, 212, 0.0)');

        const gradientMem = ctxCpuMem.getContext('2d').createLinearGradient(0, 0, 0, 220);
        gradientMem.addColorStop(0, 'rgba(249, 115, 22, 0.25)');
        gradientMem.addColorStop(1, 'rgba(249, 115, 22, 0.0)');

        const allInitCpuMem = [...(initData.cpu || []), ...(initData.mem || [])];
        const maxInitCpuMem = allInitCpuMem.length > 0 ? Math.max(...allInitCpuMem) : 0;
        let initialCpuMemMax = 100;
        if (maxInitCpuMem > 100) {
            initialCpuMemMax = Math.ceil((maxInitCpuMem * 1.2) / 10) * 10;
        }

        cpuMemChart = new Chart(ctxCpuMem, {
            type: 'line',
            data: {
                labels: [...(initData.labels || [])],
                datasets: [
                    {
                        label: 'CPU (%)',
                        data: [...(initData.cpu || [])],
                        borderColor: '#06b6d4',
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
                        borderColor: '#f97316',
                        backgroundColor: 'transparent',
                        borderWidth: 2,
                        fill: false,
                        tension: 0.35,
                        pointRadius: 2,
                        pointHoverRadius: 5
                    }
                ]
            },
            options: getCommonChartOptions('%', 0, initialCpuMemMax, 20)
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

        // Calculate dynamic scale BEFORE creating new Chart to prevent visual glitches during refresh
        const allInitTrf = [...(initData.ingress || []), ...(initData.egress || [])];
        const maxInitTrf = allInitTrf.length > 0 ? Math.max(...allInitTrf) : 0;
        let initialTrfMax = 100;
        if (maxInitTrf > 100) {
            initialTrfMax = Math.ceil((maxInitTrf * 1.25) / 10) * 10;
        }

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
            options: getCommonChartOptions(' Mbps', 0, initialTrfMax)
        });
    }

    // Apply initial data immediately with dynamic scale identical to device_detail.js
    if (initData && (initData.labels || []).length > 0) {
        applyChartHistory(initData);
    }

    if (window.INITIAL_WAN_SUMMARY && Object.keys(window.INITIAL_WAN_SUMMARY).length > 0) {
        updateWanCard(window.INITIAL_WAN_SUMMARY);
    }
}

function getCommonChartOptions(unit, minVal = 0, initialMax = 50) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
            mode: 'index',
            intersect: false
        },
        plugins: {
            legend: { display: false },
            tooltip: {
                mode: 'index',
                intersect: false,
                backgroundColor: '#1e293b',
                titleColor: '#f8fafc',
                bodyColor: '#cbd5e1',
                borderColor: '#334155',
                borderWidth: 1,
                padding: 10,
                callbacks: {
                    label: function (context) {
                        return ` ${context.dataset.label}: ${context.parsed.y}${unit}`;
                    }
                }
            }
        },
        scales: {
            x: {
                display: true,
                grid: { color: 'rgba(255, 255, 255, 0.04)' },
                ticks: { color: '#64748b', font: { size: 9.5 }, maxTicksLimit: 6 }
            },
            y: {
                min: minVal,
                suggestedMax: initialMax,
                max: initialMax,
                grid: { color: 'rgba(255, 255, 255, 0.04)' },
                ticks: {
                    color: '#64748b',
                    font: { size: 9.5 },
                    maxTicksLimit: 5,
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

            // Immediately render from cache for instant transitions without blanks when offline
            const cachedChart = loadChartHistoryFromStorage(range);
            if (cachedChart && cachedChart.labels && cachedChart.labels.length > 0) {
                applyChartHistory(cachedChart);
            }

            await pollRealtimeStatus();
        });
    });
}

function applyChartHistory(history) {
    if (!history) return;
    lastDashboardHistory = history;

    const navCpuEl = document.getElementById('cpuMemTimelineNav');
    const navTrfEl = document.getElementById('trafficTimelineNav');

    // If live mode: hide navigator, render all live data
    if (currentDashboardRange === 'live') {
        if (navCpuEl) navCpuEl.style.display = 'none';
        if (navTrfEl) navTrfEl.style.display = 'none';
        renderDashboardChartsSlice(history, 0, (history.labels || []).length - 1);
        return;
    }

    // Mode histori: 1h, 12h, 24h -> Inisialisasi Timeline Navigator Slider
    if (!cpuMemTimelineNav && typeof TimelineNavigator !== 'undefined') {
        cpuMemTimelineNav = new TimelineNavigator({
            containerId: 'cpuMemTimelineNav',
            color: '#06b6d4',
            secondaryColor: '#f97316',
            unit: '%',
            onWindowChange: (startIdx, endIdx) => {
                if (lastDashboardHistory) {
                    renderDashboardChartsSlice(lastDashboardHistory, startIdx, endIdx);
                    // Synchronize with traffic slider
                    if (trafficTimelineNav && !trafficTimelineNav.isDragging) {
                        trafficTimelineNav.updateWindowDOM(cpuMemTimelineNav.startFrac, cpuMemTimelineNav.endFrac);
                    }
                }
            }
        });
    }

    if (!trafficTimelineNav && typeof TimelineNavigator !== 'undefined') {
        trafficTimelineNav = new TimelineNavigator({
            containerId: 'trafficTimelineNav',
            color: '#06b6d4',
            secondaryColor: '#f97316',
            unit: ' Mbps',
            onWindowChange: (startIdx, endIdx) => {
                if (lastDashboardHistory) {
                    renderDashboardChartsSlice(lastDashboardHistory, startIdx, endIdx);
                    // Synchronize with cpu/mem slider
                    if (cpuMemTimelineNav && !cpuMemTimelineNav.isDragging) {
                        cpuMemTimelineNav.updateWindowDOM(trafficTimelineNav.startFrac, trafficTimelineNav.endFrac);
                    }
                }
            }
        });
    }

    if (cpuMemTimelineNav && trafficTimelineNav) {
        const preserveFractions = (cpuMemTimelineNav.isDragging || (cpuMemTimelineNav.fullLabels && cpuMemTimelineNav.fullLabels.length > 0))
            ? { start: cpuMemTimelineNav.startFrac, end: cpuMemTimelineNav.endFrac }
            : null;

        cpuMemTimelineNav.setData(history.labels, history.cpu, history.mem, preserveFractions);
        trafficTimelineNav.setData(history.labels, history.ingress, history.egress, preserveFractions);
    } else {
        renderDashboardChartsSlice(history, 0, (history.labels || []).length - 1);
    }
}

function renderDashboardChartsSlice(history, startIdx, endIdx) {
    const allLabels = history.labels || [];
    if (allLabels.length === 0) return;

    const s = Math.max(0, startIdx);
    const e = Math.min(allLabels.length - 1, endIdx);

    const labels = allLabels.slice(s, e + 1);
    const cpuVals = (history.cpu || []).slice(s, e + 1);
    const memVals = (history.mem || []).slice(s, e + 1);
    const inVals = (history.ingress || []).slice(s, e + 1);
    const outVals = (history.egress || []).slice(s, e + 1);

    const visibleCount = labels.length;
    // Adaptive datapoints: when zoom in <= 45 points, render clear circular points (pointRadius: 3).
    // In full range > 85 points, points are disabled for clean and thin lines.
    const dynamicPointRadius = visibleCount <= 45 ? 3 : (visibleCount <= 85 ? 1.5 : 0);
    const hoverPointRadius = dynamicPointRadius > 0 ? dynamicPointRadius + 3 : 5;

    // 1. CPU & Memory Chart (Default 100%, Dynamic if > 100%)
    if (cpuMemChart) {
        cpuMemChart.data.labels = labels;
        cpuMemChart.data.datasets[0].data = cpuVals;
        cpuMemChart.data.datasets[1].data = memVals;
        cpuMemChart.data.datasets[0].pointRadius = dynamicPointRadius;
        cpuMemChart.data.datasets[1].pointRadius = dynamicPointRadius;
        cpuMemChart.data.datasets[0].pointHoverRadius = hoverPointRadius;
        cpuMemChart.data.datasets[1].pointHoverRadius = hoverPointRadius;

        const allVals = [...cpuVals, ...memVals];
        const maxVal = allVals.length > 0 ? Math.max(...allVals) : 0;
        let yMaxVal = 100;
        if (maxVal > 100) {
            yMaxVal = Math.ceil((maxVal * 1.2) / 10) * 10;
        }

        if (cpuMemChart.options.scales && cpuMemChart.options.scales.y) {
            cpuMemChart.options.scales.y.suggestedMax = yMaxVal;
            cpuMemChart.options.scales.y.max = yMaxVal;
        }
        cpuMemChart.update('none');
    }

    // 2. Network Interface Traffic Chart (Default 100 Mbps, Dynamic if > 100 Mbps)
    if (trafficChart) {
        trafficChart.data.labels = labels;
        trafficChart.data.datasets[0].data = inVals;
        trafficChart.data.datasets[1].data = outVals;
        trafficChart.data.datasets[0].pointRadius = dynamicPointRadius;
        trafficChart.data.datasets[1].pointRadius = dynamicPointRadius;
        trafficChart.data.datasets[0].pointHoverRadius = hoverPointRadius;
        trafficChart.data.datasets[1].pointHoverRadius = hoverPointRadius;

        const allTraffic = [...inVals, ...outVals];
        const maxTrf = allTraffic.length > 0 ? Math.max(...allTraffic) : 0;
        let dynamicTrfMax = 100;
        if (maxTrf > 100) {
            dynamicTrfMax = Math.ceil((maxTrf * 1.25) / 10) * 10;
        }

        if (trafficChart.options.scales && trafficChart.options.scales.y) {
            trafficChart.options.scales.y.suggestedMax = dynamicTrfMax;
            trafficChart.options.scales.y.max = dynamicTrfMax;
        }
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
        saveDashboardDataToStorage(data);
        setTimeout(prefetchHistoricalRanges, 1500);
    } catch (error) {
        // Backend server offline/down: apply latest saved data & charts
        handleServerDisconnected(indicator, statusText);
    }
}

function handleServerConnected(indicator, statusText) {
    if (indicator) {
        indicator.classList.remove('is-offline');
        indicator.removeAttribute('title');
    }
    if (statusText) {
        statusText.textContent = 'LIVE POLLING';
    }
}

function handleServerDisconnected(indicator, statusText) {
    if (indicator) {
        indicator.classList.add('is-offline');
        indicator.removeAttribute('title');
    }
    if (statusText) {
        statusText.textContent = 'POLLING STOPPED';
    }

    // Retrieve latest data and charts from local cache
    const cachedData = loadDashboardDataFromStorage();
    const cachedChart = loadChartHistoryFromStorage(currentDashboardRange);

    if (cachedChart && cachedChart.labels && cachedChart.labels.length > 0) {
        applyChartHistory(cachedChart);
    }

    if (cachedData) {
        updateDashboardView(cachedData);
    }
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

    if (chart.options.scales && chart.options.scales.y && chart === cpuMemChart) {
        const allVals = chart.data.datasets.flatMap(ds => ds.data);
        const maxV = allVals.length > 0 ? Math.max(...allVals) : 0;
        const dynamicMax = maxV > 100 ? Math.ceil((maxV * 1.2) / 10) * 10 : 100;
        chart.options.scales.y.max = dynamicMax;
        chart.options.scales.y.suggestedMax = dynamicMax;
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
        if (filterAll) filterAll.textContent = `All (${data.summary.total_devices})`;
        if (filterUp) filterUp.textContent = `Online (${data.summary.devices_online})`;
        if (filterDown) filterDown.textContent = `Offline (${data.summary.devices_offline})`;
    }

    if (data.wan) {
        updateWanCard(data.wan);
    }

    if (data.metrics) {
        // Apply complete real historical data directly from database (matching device_detail.js)
        if (data.history) {
            applyChartHistory(data.history);
        }
        isRangeJustChanged = false;
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

function updateWanCard(wan) {
    if (!wan) return;
    const dlEl = document.getElementById('wanDownloadVal');
    const ulEl = document.getElementById('wanUploadVal');
    const dlProg = document.getElementById('wanDlProgress');
    const ulProg = document.getElementById('wanUlProgress');
    const dlPctEl = document.getElementById('wanDlUtilPct');
    const ulPctEl = document.getElementById('wanUlUtilPct');
    const dlCapEl = document.getElementById('wanDlCapVal');
    const latEl = document.getElementById('wanLatencyVal');
    const lossEl = document.getElementById('wanLossVal');
    const gwLatEl = document.getElementById('wanGwLatencyVal');
    const errEl = document.getElementById('wanErrorsVal');
    const qPill = document.getElementById('wanQualityPill');
    const statusText = document.getElementById('wanStatusText');
    const statusDot = document.getElementById('wanStatusDot');
    const linkBadge = document.getElementById('wanLinkBadge');
    const lastSync = document.getElementById('wanLastSync');

    const dlVal = wan.download_mbps !== undefined ? wan.download_mbps : 0.0;
    const ulVal = wan.upload_mbps !== undefined ? wan.upload_mbps : 0.0;
    const totVal = wan.total_mbps !== undefined ? wan.total_mbps : (Math.round((dlVal + ulVal) * 10) / 10);
    const cap = wan.capacity_mbps || 100;
    const utilPct = wan.utilization_pct !== undefined ? wan.utilization_pct : (cap > 0 ? Math.round((totVal / cap) * 1000) / 10 : 0);
    const dlUtilPct = cap > 0 ? Math.round((dlVal / cap) * 1000) / 10 : 0;
    const ulUtilPct = cap > 0 ? Math.round((ulVal / cap) * 1000) / 10 : 0;

    if (dlEl) dlEl.textContent = dlVal;
    if (ulEl) ulEl.textContent = ulVal;
    if (dlProg) dlProg.style.width = `${Math.min(100, Math.max(0, dlUtilPct))}%`;
    if (ulProg) ulProg.style.width = `${Math.min(100, Math.max(0, ulUtilPct))}%`;

    // Combined Utilization Row below Download & Upload
    const utilCombinedVal = document.getElementById('wanUtilCombinedVal');
    const capValCombined = document.getElementById('wanCapValCombined');
    if (utilCombinedVal) utilCombinedVal.textContent = `${utilPct}%`;
    if (capValCombined) capValCombined.textContent = cap;

    if (latEl && wan.latency_ms !== undefined) latEl.textContent = wan.latency_ms;
    if (lossEl && wan.packet_loss !== undefined) lossEl.textContent = wan.packet_loss;
    if (gwLatEl && wan.gateway_latency_ms !== undefined) gwLatEl.textContent = wan.gateway_latency_ms;
    if (errEl) {
        const rxErr = wan.rx_errors !== undefined ? wan.rx_errors : 0;
        const txErr = wan.tx_errors !== undefined ? wan.tx_errors : 0;
        errEl.textContent = `${rxErr} / ${txErr}`;
        errEl.style.color = ''; // Keep white via CSS (.ping-num)
    }
    if (lastSync && wan.last_updated) lastSync.textContent = wan.last_updated;

    if (qPill) {
        const qLabel = wan.quality_label || (wan.quality_color === 'red' ? 'Abnormal Connection' : 'Normal Connection');
        const qColor = wan.quality_color || (wan.status === 'DOWN' ? 'red' : 'green');
        qPill.textContent = qLabel;
        qPill.className = `wan-q-pill pill-${qColor}`;
    }

    const isUp = wan.status === 'UP';
    if (statusText) {
        statusText.textContent = wan.status || 'UP'; // Exclude '(1 Gbps)' text
    }
    if (statusDot) {
        statusDot.className = `live-dot dot-${isUp ? 'green' : 'red'}`;
    }
    if (linkBadge) {
        linkBadge.className = `wan-badge-status status-${isUp ? 'up' : 'down'}`;
    }
}

/* --------------------------------------------------------------------------
   WAN Actions (Speedtest Real-Time & 24-Hour Polling Logs Modal)
   -------------------------------------------------------------------------- */
let currentWanLogs = [];
let currentWanLogFilter = 'all';

function setupWanActions() {
    const btnSpeedtest = document.getElementById('btnWanSpeedtest');
    const btnSeeLog = document.getElementById('btnWanSeeLog');
    const modalLog = document.getElementById('wanLogModal');
    const btnCloseLog = document.getElementById('btnWanLogClose');
    const btnCloseLogFooter = document.getElementById('btnWanLogCloseFooter');
    const btnRefreshLog = document.getElementById('btnWanLogRefresh');
    const btnExportLog = document.getElementById('btnWanLogExport');

    // Speedtest Modal elements
    const modalSt = document.getElementById('wanSpeedtestModal');
    const btnCloseSt = document.getElementById('btnWanSpeedtestClose');
    const btnCloseStFooter = document.getElementById('btnWanSpeedtestCloseFooter');
    const btnRetestSt = document.getElementById('btnStModalRetest');

    if (btnSpeedtest) {
        btnSpeedtest.addEventListener('click', () => {
            handleWanSpeedtest();
        });
    }

    if (btnRetestSt) {
        btnRetestSt.addEventListener('click', () => {
            handleWanSpeedtest();
        });
    }

    if (btnCloseSt) btnCloseSt.addEventListener('click', closeWanSpeedtestModal);
    if (btnCloseStFooter) btnCloseStFooter.addEventListener('click', closeWanSpeedtestModal);

    if (modalSt) {
        modalSt.addEventListener('click', (e) => {
            if (e.target === modalSt) closeWanSpeedtestModal();
        });
    }

    if (btnSeeLog) {
        btnSeeLog.addEventListener('click', () => {
            openWanLogModal();
        });
    }

    if (btnCloseLog) btnCloseLog.addEventListener('click', closeWanLogModal);
    if (btnCloseLogFooter) btnCloseLogFooter.addEventListener('click', closeWanLogModal);

    if (modalLog) {
        modalLog.addEventListener('click', (e) => {
            if (e.target === modalLog) closeWanLogModal();
        });
    }

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (modalSt && modalSt.style.display !== 'none') closeWanSpeedtestModal();
            if (modalLog && modalLog.style.display !== 'none') closeWanLogModal();
        }
    });

    if (btnRefreshLog) {
        btnRefreshLog.addEventListener('click', () => {
            fetchWanLogs();
        });
    }

    if (btnExportLog) {
        btnExportLog.addEventListener('click', exportWanLogsToCsv);
    }

    // Modal filter buttons
    const filterBtns = document.querySelectorAll('.wan-filter-btn');
    filterBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            filterBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentWanLogFilter = btn.getAttribute('data-filter') || 'all';
            renderWanLogTableRows();
        });
    });
}

async function handleWanSpeedtest() {
    const modal = document.getElementById('wanSpeedtestModal');
    const loadingState = document.getElementById('speedtestLoadingState');
    const resultState = document.getElementById('speedtestResultState');
    const btnRetest = document.getElementById('btnStModalRetest');
    const btnTrigger = document.getElementById('btnWanSpeedtest');

    if (modal) {
        modal.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    }
    if (loadingState) {
        loadingState.style.display = 'flex';
        loadingState.style.flexDirection = 'column';
        loadingState.style.alignItems = 'center';
        loadingState.style.justifyContent = 'center';
    }
    if (resultState) resultState.style.display = 'none';
    if (btnRetest) btnRetest.disabled = true;
    if (btnTrigger) btnTrigger.classList.add('loading');

    try {
        const res = await fetch('/api/wan/speedtest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await res.json();
        if (res.ok && data.status === 'success') {
            const w = data.wan;
            const stDl = document.getElementById('stModalDlVal');
            const stUl = document.getElementById('stModalUlVal');
            const stDlUtil = document.getElementById('stModalDlUtil');
            const stUlUtil = document.getElementById('stModalUlUtil');
            const stDlProg = document.getElementById('stModalDlProgress');
            const stUlProg = document.getElementById('stModalUlProgress');
            const stLat = document.getElementById('stModalLat');
            const stGwLat = document.getElementById('stModalGwLat');
            const stLoss = document.getElementById('stModalLoss');
            const stQPill = document.getElementById('stModalQualityPill');
            const stTs = document.getElementById('stModalTimestamp');

            const dlVal = w.download_mbps !== undefined ? w.download_mbps : 0.0;
            const ulVal = w.upload_mbps !== undefined ? w.upload_mbps : 0.0;
            const totVal = w.total_mbps !== undefined ? w.total_mbps : (Math.round((dlVal + ulVal) * 10) / 10);
            const cap = w.capacity_mbps || 100;
            const utilPct = w.utilization_pct !== undefined ? w.utilization_pct : (cap > 0 ? Math.round((totVal / cap) * 1000) / 10 : 0);
            const dlPct = cap > 0 ? Math.round((dlVal / cap) * 1000) / 10 : 0;
            const ulPct = cap > 0 ? Math.round((ulVal / cap) * 1000) / 10 : 0;

            if (stDl) stDl.textContent = dlVal;
            if (stUl) stUl.textContent = ulVal;
            if (stDlUtil) stDlUtil.textContent = `${dlPct}% Utilisasi`;
            if (stUlUtil) stUlUtil.textContent = `${ulPct}% Utilisasi`;
            if (stDlProg) stDlProg.style.width = `${Math.min(100, Math.max(0, dlPct))}%`;
            if (stUlProg) stUlProg.style.width = `${Math.min(100, Math.max(0, ulPct))}%`;
            if (stLat) stLat.textContent = `${w.latency_ms} ms`;
            if (stGwLat) stGwLat.textContent = `${w.gateway_latency_ms} ms`;
            if (stLoss) stLoss.textContent = `${w.packet_loss}%`;
            if (stQPill) {
                const isDown = w.status === 'DOWN' || w.quality_color === 'red';
                stQPill.textContent = w.quality_label || (isDown ? 'Abnormal Connection' : 'Normal Connection');
                stQPill.className = 'st-m-val';
                stQPill.style.color = '#ffffff';
                stQPill.style.background = 'transparent';
                stQPill.style.border = 'none';
                stQPill.style.boxShadow = 'none';
            }
            if (stTs) {
                const rawTime = w.last_updated || new Date().toLocaleTimeString('id-ID');
                const cleanTime = rawTime.replace(/\s*\(.*?\)/g, '').trim();
                stTs.textContent = cleanTime;
            }

            // NOC Architecture: Do not overwrite main dashboard KPI cards!
            // Dashboard cards display active internal utilization metrics.
            // Speedtest modal specifically measures peak physical bandwidth capacity.

            // Hide loading, show results
            if (loadingState) loadingState.style.display = 'none';
            if (resultState) resultState.style.display = 'block';
        } else {
            alert('Failed to execute speedtest: ' + (data.message || 'Error'));
            closeWanSpeedtestModal();
        }
    } catch (e) {
        console.error('Speedtest error:', e);
        alert('An error occurred while executing real-time speedtest.');
        closeWanSpeedtestModal();
    } finally {
        if (btnRetest) btnRetest.disabled = false;
        if (btnTrigger) btnTrigger.classList.remove('loading');
    }
}

function closeWanSpeedtestModal() {
    const modal = document.getElementById('wanSpeedtestModal');
    if (!modal) return;
    modal.style.display = 'none';
    document.body.style.overflow = '';
}

function openWanLogModal() {
    const modal = document.getElementById('wanLogModal');
    if (!modal) return;
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
    fetchWanLogs();
}

function closeWanLogModal() {
    const modal = document.getElementById('wanLogModal');
    if (!modal) return;
    modal.style.display = 'none';
    document.body.style.overflow = '';
}

async function fetchWanLogs(silent = false) {
    const tbody = document.getElementById('wanLogTableBody');
    if (!silent && tbody) {
        tbody.innerHTML = `
            <tr>
                <td colspan="9" style="text-align: center; padding: 45px 20px;">
                    <div class="speedtest-gauge-wrap" style="display:flex; flex-direction:column; align-items:center; justify-content:center;">
                        <div class="speedtest-spinner"></div>
                        <div class="speedtest-testing-txt" style="margin-top:14px; font-size:14px; font-weight:600; color:#f8fafc;">Loading 24-Hour Polling Logs</div>
                        <div class="speedtest-step-sub" style="font-size:12px; color:#94a3b8; margin-top:4px;">Retrieving telemetry snapshots from database</div>
                    </div>
                </td>
            </tr>
        `;
    }

    try {
        const res = await fetch('/api/wan/logs', { cache: 'no-store' });
        if (res.ok) {
            const data = await res.json();
            currentWanLogs = data.logs || [];
            updateWanLogCounts();
            renderWanLogTableRows();
        } else if (tbody) {
            tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 24px; color: #ef4444;">Failed to load logs (${res.status})</td></tr>`;
        }
    } catch (e) {
        console.error('Error fetching WAN logs:', e);
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 24px; color: #ef4444;">Network error occurred while loading logs.</td></tr>`;
        }
    }
}

function updateWanLogCounts() {
    const countAllEl = document.getElementById('wanLogCountAll');
    const countUpEl = document.getElementById('wanLogCountUp');
    const countIssueEl = document.getElementById('wanLogCountIssue');

    const total = currentWanLogs.length;
    const upCount = currentWanLogs.filter(l => l.status === 'UP' && (l.latency_ms <= 45 && l.packet_loss <= 2.0 && (!l.total_errors || l.total_errors === 0))).length;
    const issueCount = total - upCount;

    if (countAllEl) countAllEl.textContent = total;
    if (countUpEl) countUpEl.textContent = upCount;
    if (countIssueEl) countIssueEl.textContent = issueCount;
}

function renderWanLogTableRows() {
    const tbody = document.getElementById('wanLogTableBody');
    if (!tbody) return;

    let filtered = currentWanLogs;
    if (currentWanLogFilter === 'up') {
        filtered = currentWanLogs.filter(l => l.status === 'UP' && (l.latency_ms <= 45 && l.packet_loss <= 2.0 && (!l.total_errors || l.total_errors === 0)));
    } else if (currentWanLogFilter === 'issue') {
        filtered = currentWanLogs.filter(l => l.status === 'DOWN' || l.latency_ms > 45 || l.packet_loss > 2.0 || (l.total_errors && l.total_errors > 0));
    }

    if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 28px; color: #94a3b8;">No log records found matching this filter.</td></tr>`;
        return;
    }

    const rowsHtml = filtered.map(item => {
        const isDown = item.status === 'DOWN';
        const statusClass = isDown ? 'down' : 'up';
        const statusLabel = isDown ? 'DOWN' : 'UP';

        return `
            <tr>
                <td style="color: #ffffff; font-weight: 500;">${escapeHtml(item.timestamp)}</td>
                <td>
                    <span class="wan-badge-status-sm ${statusClass}">
                        <span class="live-dot dot-${isDown ? 'red' : 'green'}" style="width: 5px; height: 5px;"></span>
                        ${statusLabel}
                    </span>
                </td>
                <td style="color: #ffffff; font-weight: 600;">${item.download_mbps} Mbps</td>
                <td style="color: #ffffff; font-weight: 600;">${item.upload_mbps} Mbps</td>
                <td style="color: #ffffff; font-weight: 600;">${item.total_mbps} Mbps</td>
                <td style="color: #ffffff; font-weight: 500;">${item.latency_ms} ms</td>
                <td style="color: #ffffff; font-weight: 500;">${item.gateway_latency_ms} ms</td>
                <td style="color: #ffffff; font-weight: 500;">${item.packet_loss}%</td>
                <td style="color: #ffffff; font-weight: 500;">${item.rx_errors || 0} / ${item.tx_errors || 0} pkts</td>
            </tr>
        `;
    }).join('');

    tbody.innerHTML = rowsHtml;
}

function exportWanLogsToCsv() {
    if (!currentWanLogs || currentWanLogs.length === 0) {
        alert('No log data available to export.');
        return;
    }

    const headers = ['Timestamp', 'Interface', 'Provider', 'Status', 'Download_Mbps', 'Upload_Mbps', 'Total_Mbps', 'Latency_1.1.1.1_ms', 'Gateway_Latency_ms', 'Packet_Loss_pct', 'Rx_Errors', 'Tx_Errors', 'Total_Errors'];
    const csvRows = [headers.join(',')];

    currentWanLogs.forEach(r => {
        const rx = r.rx_errors || 0;
        const tx = r.tx_errors || 0;
        const tot = r.total_errors !== undefined ? r.total_errors : (rx + tx);
        csvRows.push([
            `"${r.timestamp}"`,
            `"${r.interface}"`,
            `"${r.provider}"`,
            `"${r.status}"`,
            r.download_mbps,
            r.upload_mbps,
            r.total_mbps,
            r.latency_ms,
            r.gateway_latency_ms,
            r.packet_loss,
            rx,
            tx,
            tot
        ].join(','));
    });

    const csvContent = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csvRows.join('\n'));
    const link = document.createElement('a');
    link.setAttribute('href', csvContent);
    const dateStr = new Date().toISOString().slice(0, 10);
    link.setAttribute('download', `agiva_biznet_wan_logs_24h_${dateStr}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function renderDeviceTable(devices) {
    const tbody = document.getElementById('deviceTableBody');
    if (!tbody) return;

    // Permanent sort order by device_id (1, 2, 3) to prevent row jumping
    devices.sort((a, b) => a.id - b.id);

    let html = '';
    devices.forEach(dev => {
        const vendorClass = (dev.vendor || '').toLowerCase().replace(/\s+/g, '-');
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
                <strong>${dev.name}</strong>
            </td>
            <td class="col-ip"><code>${dev.ip}</code></td>
            <td class="col-vendor"><span class="vendor-badge badge-${vendorClass}">${dev.vendor}</span></td>
            <td class="col-site">${dev.site}</td>
            <td class="col-status">${statusBadge}</td>
            <td class="col-metrics">${metricContent}</td>
            <td class="col-uptime">${dev.uptime || 'Unknown'}</td>
            <td class="col-action text-center">
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
                <p style="font-size: 0.9rem; font-weight: 500; color: #94a3b8; margin: 0 0 4px 0;">All Systems Operational</p>
                <span style="font-size: 0.75rem; color: #64748b;">No active alerts requiring mitigation</span>
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
                    <span class="badge-ack-state text-warning">
                        <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.5" style="display:inline-block; vertical-align:middle; margin-right:3px;">
                            <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>Acknowledged</span>
                    <span class="text-muted-xs">${escapeHtml(alert.acknowledged_by || 'Confirmed')}</span>
                ` : `
                    <span class="badge-ack-state text-warning">Pending ACK</span>
                `}
            </div>
        </div>`;
    });
    stream.innerHTML = html;
}

/* --------------------------------------------------------------------------
   SOP PT AGIVA: Alert Acknowledge (ACK) via Web is strictly disabled.
   Acknowledge must ONLY be performed by authorized engineers via Telegram Bot: /ack <alert_id>
   -------------------------------------------------------------------------- */

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
    // Dedicated filter by Vendor Name or Site
    const matches = devices.filter(d =>
        (d.vendor && d.vendor.toLowerCase().includes(query)) ||
        (d.site && d.site.toLowerCase().includes(query))
    );

    if (matches.length > 0) {
        let itemsHtml = '';
        matches.forEach(dev => {
            const vendorClass = (dev.vendor || '').toLowerCase().replace(/\s+/g, '-');
            const vendorInitial = (dev.vendor || 'D')[0].toUpperCase();

            // UP or DOWN status omitted in search bar dropdown
            itemsHtml += `
            <li class="search-dropdown-item" onclick="window.location.href='/device/${dev.id}'">
                <div class="search-item-info">
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
                <span>${matches.length} Devices Found</span>
            </div>
            <ul class="search-dropdown-list">
                ${itemsHtml}
            </ul>
        `;
        dropdown.style.display = 'block';
    } else {
        dropdown.innerHTML = `
            <div class="search-dropdown-header">
                <span>0 Devices Found</span>
            </div>
            <div class="search-dropdown-empty">
                No devices found matching vendor or site "<strong>${escapeHtml(query)}</strong>".
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

let currentDeviceSearch = '';

function applyTableFilters() {
    const activeFilterBtn = document.querySelector('.badge-filter.active');
    const statusFilter = activeFilterBtn ? activeFilterBtn.getAttribute('data-filter') : 'all';
    const q = currentDeviceSearch.trim().toLowerCase();

    const rows = document.querySelectorAll('#deviceTableBody .device-row');
    let visibleCount = 0;

    rows.forEach(row => {
        const rowStatus = row.getAttribute('data-status') || (row.classList.contains('filter-UP') ? 'UP' : 'DOWN');
        const matchesStatus = statusFilter === 'all' || rowStatus === statusFilter;

        let matchesSearch = true;
        if (q) {
            const devId = row.getAttribute('data-id') || (row.id ? row.id.replace('row-dev-', '') : '');
            const devName = (row.getAttribute('data-name') || '').toLowerCase();
            const devIp = (row.getAttribute('data-ip') || '').toLowerCase();
            const devVendor = (row.getAttribute('data-vendor') || '').toLowerCase();
            const devSite = (row.getAttribute('data-site') || '').toLowerCase();
            const devStatus = rowStatus.toLowerCase();

            matchesSearch = devId.includes(q) || ('dev-' + devId).includes(q) || ('#' + devId).includes(q) ||
                devName.includes(q) || devIp.includes(q) ||
                devVendor.includes(q) || devSite.includes(q) ||
                devStatus.includes(q);
        }

        if (matchesStatus && matchesSearch) {
            row.style.display = '';
            visibleCount++;
        } else {
            row.style.display = 'none';
        }
    });

    // Handle empty state feedback in table
    const tbody = document.getElementById('deviceTableBody');
    let emptyRow = document.getElementById('noResultsRow');
    if (visibleCount === 0 && rows.length > 0) {
        let emptyMessage = '';
        if (q) {
            emptyMessage = `No devices found matching "${escapeHtml(currentDeviceSearch)}"`;
        } else {
            emptyMessage = statusFilter === 'DOWN' ? 'No devices currently offline.' :
                statusFilter === 'UP' ? 'No devices currently online.' :
                    'No devices available.';
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

    if (window.location.hash === '#monitored-devices') {
        scrollToDevicesTable();
    }
}




/* --------------------------------------------------------------------------
   Toast Notifications (Disabled in favor of Inline Button Feedback)
   -------------------------------------------------------------------------- */
function showToast(message, type = 'success') {
    // Disabled in favor of Inline Button Feedback
}
