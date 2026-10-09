/**
 * Device Detail JavaScript - PT Agiva Indonesia Network Automation
 * Supports both offline file:// double-click and online API polling.
 */

let deviceCpuChart = null;
let deviceTrafficChart = null;

document.addEventListener('DOMContentLoaded', () => {
    fetchDeviceMetrics();
});

async function fetchDeviceMetrics() {
    // If opened via file:// directly
    if (window.location.protocol === 'file:') {
        renderWithMockMetrics();
        return;
    }

    try {
        const devId = typeof CURRENT_DEVICE_ID !== 'undefined' ? CURRENT_DEVICE_ID : 1;
        const res = await fetch(`/api/device/${devId}/metrics`);
        if (!res.ok) {
            renderWithMockMetrics();
            return;
        }

        const data = await res.json();
        renderDeviceCharts(data);
    } catch (err) {
        renderWithMockMetrics();
    }
}

function renderWithMockMetrics() {
    const mockData = {
        labels: ['00:00', '02:00', '04:00', '06:00', '08:00', '10:00', '12:00', '14:00', '16:00', '18:00', '20:00', '22:00', 'Now'],
        cpu: [18, 22, 19, 25, 45, 62, 58, 74, 52, 48, 38, 35, 34.5],
        memory: [42, 42, 43, 44, 46, 48, 50, 52, 51, 49, 48, 48, 48.2],
        traffic: [60, 45, 30, 85, 180, 240, 210, 290, 260, 210, 175, 140, 145.2]
    };
    renderDeviceCharts(mockData);
}

function renderDeviceCharts(data) {
    const ctxCpu = document.getElementById('deviceCpuMemChart');
    if (ctxCpu) {
        const gradientCpu = ctxCpu.getContext('2d').createLinearGradient(0, 0, 0, 220);
        gradientCpu.addColorStop(0, 'rgba(16, 185, 129, 0.4)');
        gradientCpu.addColorStop(1, 'rgba(16, 185, 129, 0.0)');

        const gradientMem = ctxCpu.getContext('2d').createLinearGradient(0, 0, 0, 220);
        gradientMem.addColorStop(0, 'rgba(245, 158, 11, 0.3)');
        gradientMem.addColorStop(1, 'rgba(245, 158, 11, 0.0)');

        if (deviceCpuChart) deviceCpuChart.destroy();

        deviceCpuChart = new Chart(ctxCpu, {
            type: 'line',
            data: {
                labels: data.labels,
                datasets: [
                    {
                        label: 'CPU (%)',
                        data: data.cpu,
                        borderColor: '#10b981',
                        backgroundColor: gradientCpu,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.3,
                        pointRadius: 3
                    },
                    {
                        label: 'Memory (%)',
                        data: data.memory,
                        borderColor: '#f59e0b',
                        backgroundColor: gradientMem,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.3,
                        pointRadius: 3
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b' } },
                    y: { min: 0, max: 100, grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b', callback: v => `${v}%` } }
                }
            }
        });
    }

    const ctxTraffic = document.getElementById('deviceTrafficChart');
    if (ctxTraffic) {
        const gradientCyan = ctxTraffic.getContext('2d').createLinearGradient(0, 0, 0, 220);
        gradientCyan.addColorStop(0, 'rgba(6, 182, 212, 0.4)');
        gradientCyan.addColorStop(1, 'rgba(6, 182, 212, 0.0)');

        if (deviceTrafficChart) deviceTrafficChart.destroy();

        deviceTrafficChart = new Chart(ctxTraffic, {
            type: 'line',
            data: {
                labels: data.labels,
                datasets: [
                    {
                        label: 'Throughput (Mbps)',
                        data: data.traffic,
                        borderColor: '#06b6d4',
                        backgroundColor: gradientCyan,
                        borderWidth: 2,
                        fill: true,
                        tension: 0.3,
                        pointRadius: 3
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b' } },
                    y: { min: 0, grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#64748b', callback: v => `${v}M` } }
                }
            }
        });
    }
}
