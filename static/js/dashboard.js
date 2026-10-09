/**
 * Dashboard JavaScript - PT Agiva Indonesia Network Automation
 * Supports BOTH:
 * 1. Offline file:// direct double-click (simulates real-time chart animation)
 * 2. Online http:// server mode (polls /api/status live JSON endpoint)
 */

let cpuMemChart = null;
let trafficChart = null;
const MAX_CHART_POINTS = 14;

document.addEventListener('DOMContentLoaded', () => {
    initCharts();
    setupTableFilters();
    setupSearchFilter();

    // Polling interval (every 4 seconds)
    setInterval(pollRealtimeStatus, 4000);
});

/* --------------------------------------------------------------------------
   Chart.js Initialization
   -------------------------------------------------------------------------- */
function initCharts() {
    const defaultLabels = ['11:20', '11:22', '11:24', '11:26', '11:28', '11:30', '11:32', '11:34', '11:36', '11:38'];

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
                labels: [...defaultLabels],
                datasets: [
                    {
                        label: 'CPU (%)',
                        data: [28, 35, 42, 38, 55, 62, 48, 52, 45, 38],
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
                        data: [42, 44, 45, 46, 48, 50, 49, 51, 52, 50],
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
            options: getCommonChartOptions('%', 0, 100)
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
                labels: [...defaultLabels],
                datasets: [
                    {
                        label: 'Ingress (Mbps)',
                        data: [85, 120, 95, 160, 210, 140, 190, 230, 180, 210],
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
                        data: [45, 60, 50, 90, 115, 80, 105, 130, 95, 120],
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
            options: getCommonChartOptions(' Mbps', 0, null)
        });
    }
}

function getCommonChartOptions(unit, minVal, maxVal) {
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
                    font: { family: "'JetBrains Mono', monospace", size: 10 },
                    callback: (val) => `${val}${unit}`
                }
            }
        }
    };
}

/* --------------------------------------------------------------------------
   Real-Time Polling & Offline Fallback Simulation
   -------------------------------------------------------------------------- */
async function pollRealtimeStatus() {
    // If opened directly from Windows Explorer (file:// protocol)
    if (window.location.protocol === 'file:') {
        simulateOfflineLiveMetrics();
        return;
    }

    try {
        const response = await fetch('/api/status');
        if (!response.ok) {
            simulateOfflineLiveMetrics();
            return;
        }

        const data = await response.json();
        updateDashboardView(data);
    } catch (error) {
        // Fallback to smooth client-side animation if server is offline
        simulateOfflineLiveMetrics();
    }
}

function simulateOfflineLiveMetrics() {
    const now = new Date();
    const timeLabel = now.toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

    // Generate slight oscillation for CPU (30 - 65%) & Traffic (120 - 260 Mbps)
    const newCpu = Math.round(35 + Math.random() * 25);
    const newMem = Math.round(48 + Math.random() * 6);
    const newTrf = Math.round(150 + Math.random() * 90);

    pushChartData(cpuMemChart, timeLabel, [newCpu, newMem]);
    pushChartData(trafficChart, timeLabel, [newTrf, Math.round(newTrf * 0.55)]);

    // Update progress bars on table
    document.querySelectorAll('.device-row').forEach(row => {
        if (row.classList.contains('filter-UP')) {
            const cpuBar = row.querySelector('.fill-cpu');
            const memBar = row.querySelector('.fill-mem');
            const vals = row.querySelectorAll('.mini-val');
            if (cpuBar && vals[0]) {
                const c = Math.max(12, Math.min(92, Math.round(parseInt(vals[0].textContent) + (Math.random() * 6 - 3))));
                cpuBar.style.width = c + '%';
                vals[0].textContent = c + '%';
            }
        }
    });
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
    }

    if (data.metrics) {
        const timeLabel = data.timestamp;
        pushChartData(cpuMemChart, timeLabel, [data.metrics.avg_cpu, data.metrics.avg_mem]);
        pushChartData(trafficChart, timeLabel, [data.metrics.total_traffic, Math.round(data.metrics.total_traffic * 0.58)]);
    }
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
function setupTableFilters() {
    const filterButtons = document.querySelectorAll('.badge-filter');
    filterButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            filterButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const filterValue = btn.getAttribute('data-filter');
            const rows = document.querySelectorAll('.device-row');

            rows.forEach(row => {
                if (filterValue === 'all') {
                    row.style.display = '';
                } else if (row.classList.contains(`filter-${filterValue}`)) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        });
    });
}

function setupSearchFilter() {
    const searchInput = document.getElementById('globalSearch');
    if (!searchInput) return;

    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase().trim();
        const rows = document.querySelectorAll('.device-row');

        rows.forEach(row => {
            const text = row.textContent.toLowerCase();
            row.style.display = text.includes(query) ? '' : 'none';
        });
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
