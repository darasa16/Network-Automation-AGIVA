/**
 * Device Detail JavaScript - PT Agiva Indonesia Network Automation
 * Real-time metric polling, manual refresh interaction, and live chart synchronization.
 */

let chartCpuInstance = null;
let chartMemoryInstance = null;
let chartPacketBuffersInstance = null;
let chartTxDropsInstance = null;
let chartMessageBuffersInstance = null;
let chartRxErrorsInstance = null;
let deviceTrafficChart = null;
let currentFilter = 'all';
let currentSearch = '';
let currentDeviceRange = 'live';

document.addEventListener('DOMContentLoaded', () => {
    initPortControls();
    initTimeRangeSelector();
    fetchDeviceMetrics(false);
    // Real-time polling every 5 seconds
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
            <div style="font-size: 13px; font-weight: 500; color: #f8fafc;">${message}</div>
        </div>
        <button onclick="this.parentElement.remove()" style="background:none; border:none; color:#94a3b8; cursor:pointer; font-size:16px;">&times;</button>
    `;

    container.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'slideOutRight 0.3s forwards ease-in';
        setTimeout(() => toast.remove(), 300);
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
            if (isManual) {
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = originalBtnHtml;
                }
                showToast('Gagal memperbarui data: Endpoint metrik tidak merespon.', 'warning');
            }
            return;
        }

        const data = await res.json();
        updateConnectionStatus(true);

        // Update Quick Stat & Resource values dynamically
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
        }
        if (data.current_packet_buffers !== undefined) {
            const pbEl = document.getElementById('valPacketBuffers');
            if (pbEl) pbEl.textContent = `${data.current_packet_buffers}%`;
        }
        if (data.current_tx_drops !== undefined) {
            const tdEl = document.getElementById('valTxDrops');
            if (tdEl) tdEl.textContent = `${data.current_tx_drops} Drops`;
        }
        if (data.current_message_buffers !== undefined) {
            const mbEl = document.getElementById('valMessageBuffers');
            if (mbEl) mbEl.textContent = `${data.current_message_buffers}%`;
        }
        if (data.current_rx_errors !== undefined) {
            const reEl = document.getElementById('valRxErrors');
            if (reEl) reEl.textContent = `${data.current_rx_errors} Errors`;
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

        if (isManual) {
            if (btn) {
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
        }
    } catch (err) {
        updateConnectionStatus(false);
        if (isManual) {
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = originalBtnHtml;
            }
            showToast('Gagal menghubungi backend server.', 'warning');
        }
    }
}

function renderMiniResourceChart(canvasId, existingChart, labels, dataPoints, colorHex, unit = '%', isInteger = false) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return null;

    const maxVal = dataPoints.length > 0 ? Math.max(...dataPoints) : 0;
    const computedMax = isInteger
        ? Math.max(Math.ceil(maxVal * 1.25), 5)
        : Math.min(Math.max(Math.ceil(maxVal * 1.25), 10), 100);

    if (existingChart) {
        existingChart.data.labels = labels;
        existingChart.data.datasets[0].data = dataPoints;
        if (existingChart.data.datasets[0].borderColor !== colorHex) {
            existingChart.data.datasets[0].borderColor = colorHex;
            const ctx = canvas.getContext('2d');
            const gradient = ctx.createLinearGradient(0, 0, 0, 90);
            gradient.addColorStop(0, colorHex + '40');
            gradient.addColorStop(1, colorHex + '00');
            existingChart.data.datasets[0].backgroundColor = gradient;
        }
        if (existingChart.options.scales && existingChart.options.scales.y) {
            existingChart.options.scales.y.suggestedMax = computedMax;
        }
        existingChart.update('none');
        return existingChart;
    }

    const ctx = canvas.getContext('2d');
    const gradient = ctx.createLinearGradient(0, 0, 0, 90);
    gradient.addColorStop(0, colorHex + '40'); // ~25% opacity
    gradient.addColorStop(1, colorHex + '00'); // 0% opacity

    return new Chart(canvas, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                data: dataPoints,
                borderColor: colorHex,
                backgroundColor: gradient,
                borderWidth: 2,
                fill: true,
                tension: 0.35,
                pointRadius: 2.5,
                pointHoverRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (c) => ` ${c.parsed.y}${unit}`
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
                    min: 0,
                    suggestedMax: computedMax,
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: {
                        color: '#64748b',
                        font: { size: 9.5 },
                        callback: (v) => isInteger ? v : `${v}${unit}`
                    }
                }
            }
        }
    });
}

function renderDeviceCharts(data) {
    const labels = data.labels || [];
    const cpuVals = data.cpu || [];
    const memVals = data.memory || [];
    const pbVals = data.packet_buffers || cpuVals.map(() => 31.0);
    const tdVals = data.tx_drops || cpuVals.map(() => 0);
    const mbVals = data.message_buffers || cpuVals.map(() => 22.0);
    const reVals = data.rx_errors || cpuVals.map(() => 0);

    // 1. CPU Utilization (Emerald #10b981)
    chartCpuInstance = renderMiniResourceChart('chartCpu', chartCpuInstance, labels, cpuVals, '#10b981', '%');

    // 2. Memory Utilization (Amber #f59e0b)
    chartMemoryInstance = renderMiniResourceChart('chartMemory', chartMemoryInstance, labels, memVals, '#f59e0b', '%');

    // 3. Packet Buffers (Cyan #06b6d4)
    chartPacketBuffersInstance = renderMiniResourceChart('chartPacketBuffers', chartPacketBuffersInstance, labels, pbVals, '#06b6d4', '%');

    // 4. TX Drops (Rose #f43f5e)
    chartTxDropsInstance = renderMiniResourceChart('chartTxDrops', chartTxDropsInstance, labels, tdVals, '#f43f5e', ' drops', true);

    // 5. Message Buffers (Purple #a855f7)
    chartMessageBuffersInstance = renderMiniResourceChart('chartMessageBuffers', chartMessageBuffersInstance, labels, mbVals, '#a855f7', '%');

    // 6. RX Errors (Vivid Orange #f97316)
    chartRxErrorsInstance = renderMiniResourceChart('chartRxErrors', chartRxErrorsInstance, labels, reVals, '#f97316', ' errors', true);

    // 7. Aggregated Throughput Chart (IN & OUT) - Diagram Batang (Bar Chart)
    const ctxTraffic = document.getElementById('deviceTrafficChart');
    if (ctxTraffic) {
        const trafficIn = data.traffic_in || data.traffic || [];
        const trafficOut = data.traffic_out || [];

        // Recreate if existing instance is not a bar chart
        if (deviceTrafficChart && deviceTrafficChart.config.type !== 'bar') {
            deviceTrafficChart.destroy();
            deviceTrafficChart = null;
        }

        const allVals = [...trafficIn, ...trafficOut];
        const maxVal = allVals.length > 0 ? Math.max(...allVals) : 50;
        const suggestedYMax = Math.max(Math.ceil(maxVal * 1.25), 50);

        if (deviceTrafficChart) {
            deviceTrafficChart.data.labels = labels;
            if (deviceTrafficChart.data.datasets.length > 0) {
                deviceTrafficChart.data.datasets[0].data = trafficIn;
            }
            if (deviceTrafficChart.data.datasets.length > 1) {
                deviceTrafficChart.data.datasets[1].data = trafficOut;
            }
            if (deviceTrafficChart.options.scales.y) {
                deviceTrafficChart.options.scales.y.suggestedMax = suggestedYMax;
            }
            deviceTrafficChart.update('none');
        } else {
            const gradientCyan = ctxTraffic.getContext('2d').createLinearGradient(0, 0, 0, 180);
            gradientCyan.addColorStop(0, 'rgba(6, 182, 212, 0.85)');
            gradientCyan.addColorStop(1, 'rgba(6, 182, 212, 0.2)');

            const gradientGreen = ctxTraffic.getContext('2d').createLinearGradient(0, 0, 0, 180);
            gradientGreen.addColorStop(0, 'rgba(16, 185, 129, 0.85)');
            gradientGreen.addColorStop(1, 'rgba(16, 185, 129, 0.2)');

            const datasets = [
                {
                    label: 'Rx',
                    data: trafficIn,
                    borderColor: '#06b6d4',
                    backgroundColor: gradientCyan,
                    borderWidth: 1.5,
                    borderRadius: 4,
                    borderSkipped: false,
                    hoverBackgroundColor: '#06b6d4'
                },
                {
                    label: 'Tx',
                    data: trafficOut,
                    borderColor: '#10b981',
                    backgroundColor: gradientGreen,
                    borderWidth: 1.5,
                    borderRadius: 4,
                    borderSkipped: false,
                    hoverBackgroundColor: '#10b981'
                }
            ];

            deviceTrafficChart = new Chart(ctxTraffic, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: datasets
                },
                options: {
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
                            backgroundColor: '#18142c',
                            titleColor: '#cbd5e1',
                            bodyColor: '#cbd5e1',
                            borderColor: 'rgba(232, 165, 118, 0.3)',
                            borderWidth: 1,
                            padding: 10,
                            cornerRadius: 6,
                            callbacks: {
                                label: (ctx) => ` ${ctx.dataset.label}: ${ctx.parsed.y} Mbps`
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255, 255, 255, 0.04)' },
                            ticks: { color: '#64748b', font: { size: 10 } },
                            categoryPercentage: 0.65,
                            barPercentage: 0.85
                        },
                        y: {
                            min: 0,
                            suggestedMax: suggestedYMax,
                            grid: { color: 'rgba(255, 255, 255, 0.04)' },
                            ticks: {
                                color: '#64748b',
                                font: { size: 10 },
                                callback: v => `${v}M`
                            }
                        }
                    }
                }
            });
        }
    }
}
