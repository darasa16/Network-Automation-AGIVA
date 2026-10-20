/**
 * Timeline Navigator (Mini-Map / Range Slider / Brush)
 * PT Agiva Indonesia - Network Operations Automation
 *
 * Implements an Overview + Detail timeline navigator for Chart.js.
 * Displays 100% pure raw data in a mini sparkline with an interactive
 * draggable & resizable brush window. Slices the main chart dynamically
 * to prevent dot crowding while preserving raw anomaly/spike visibility.
 *
 * Fully supports Touch (Lenovo Flex 7) and Mouse input.
 */

class TimelineNavigator {
    constructor(options) {
        this.container = typeof options.container === 'string'
            ? document.getElementById(options.container)
            : options.container;

        if (!options.container && options.containerId) {
            this.container = document.getElementById(options.containerId);
        }

        this.color = options.color || '#06b6d4';
        this.secondaryColor = options.secondaryColor || '#10b981';
        this.onWindowChange = options.onWindowChange || (() => {});
        this.unit = options.unit || '';

        this.fullLabels = [];
        this.fullData = [];
        this.fullSecondaryData = [];

        // Window fractions (0.0 to 1.0)
        this.startFrac = 0.0;
        this.endFrac = 1.0;
        this.minWindowFrac = 0.04; // Minimum window: ~4% of range (at least 5-10 points)

        // Dragging state
        this.isDragging = false;
        this.dragTarget = null; // 'window', 'left', 'right'
        this.startX = 0;
        this.initialStartFrac = 0.0;
        this.initialEndFrac = 1.0;

        this.initDOM();
        this.bindEvents();
    }

    initDOM() {
        if (!this.container) return;

        this.container.classList.add('timeline-nav-wrapper');
        this.container.innerHTML = `
            <div class="timeline-nav-header">
                <span class="timeline-nav-title">
                    <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" style="display:inline-block; vertical-align:middle; margin-right:4px;">
                        <circle cx="11" cy="11" r="8"></circle>
                        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                    </svg>
                    Timeline Navigator (Mini-Map Riil)
                </span>
                <div class="timeline-nav-quick-actions">
                    <button type="button" class="nav-zoom-btn btn-zoom-all" title="Tampilkan seluruh rentang 100%">100%</button>
                    <button type="button" class="nav-zoom-btn btn-zoom-50" title="Zoom 50% rentang">50%</button>
                    <button type="button" class="nav-zoom-btn btn-zoom-25" title="Fokus 25% rentang">25%</button>
                </div>
            </div>
            <div class="timeline-nav-track">
                <canvas class="timeline-nav-canvas"></canvas>
                <div class="timeline-nav-curtain curtain-left"></div>
                <div class="timeline-nav-brush">
                    <div class="timeline-nav-handle handle-left" title="Tarik untuk memperluas / mempersempit batas kiri">
                        <span class="handle-bar"></span>
                    </div>
                    <div class="timeline-nav-window" title="Geser ke kiri / kanan untuk menyisir waktu kejadian"></div>
                    <div class="timeline-nav-handle handle-right" title="Tarik untuk memperluas / mempersempit batas kanan">
                        <span class="handle-bar"></span>
                    </div>
                </div>
                <div class="timeline-nav-curtain curtain-right"></div>
            </div>
            <div class="timeline-nav-footer">
                <span class="timeline-nav-time label-start">--:--</span>
                <span class="timeline-nav-info label-info">Geser slider untuk zoom detail kejadian mentah</span>
                <span class="timeline-nav-time label-end">--:--</span>
            </div>
        `;

        this.track = this.container.querySelector('.timeline-nav-track');
        this.canvas = this.container.querySelector('.timeline-nav-canvas');
        this.curtainLeft = this.container.querySelector('.curtain-left');
        this.curtainRight = this.container.querySelector('.curtain-right');
        this.brush = this.container.querySelector('.timeline-nav-brush');
        this.brushWindow = this.container.querySelector('.timeline-nav-window');
        this.handleLeft = this.container.querySelector('.handle-left');
        this.handleRight = this.container.querySelector('.handle-right');

        this.labelStart = this.container.querySelector('.label-start');
        this.labelInfo = this.container.querySelector('.label-info');
        this.labelEnd = this.container.querySelector('.label-end');

        // Quick zoom buttons
        const btnAll = this.container.querySelector('.btn-zoom-all');
        const btn50 = this.container.querySelector('.btn-zoom-50');
        const btn25 = this.container.querySelector('.btn-zoom-25');

        if (btnAll) btnAll.addEventListener('click', () => this.setWindow(0, 1));
        if (btn50) btn50.addEventListener('click', () => this.setWindow(Math.max(0, this.endFrac - 0.5), this.endFrac));
        if (btn25) btn25.addEventListener('click', () => this.setWindow(Math.max(0, this.endFrac - 0.25), this.endFrac));
    }

    bindEvents() {
        if (!this.track) return;

        // Mouse Down
        const onStart = (e, target) => {
            e.preventDefault();
            e.stopPropagation();
            this.isDragging = true;
            this.dragTarget = target;
            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            this.startX = clientX;
            this.initialStartFrac = this.startFrac;
            this.initialEndFrac = this.endFrac;
            document.body.classList.add('nav-dragging-active');
        };

        this.handleLeft.addEventListener('mousedown', (e) => onStart(e, 'left'));
        this.handleRight.addEventListener('mousedown', (e) => onStart(e, 'right'));
        this.brushWindow.addEventListener('mousedown', (e) => onStart(e, 'window'));

        // Touch for Lenovo Flex 7
        this.handleLeft.addEventListener('touchstart', (e) => onStart(e, 'left'), { passive: false });
        this.handleRight.addEventListener('touchstart', (e) => onStart(e, 'right'), { passive: false });
        this.brushWindow.addEventListener('touchstart', (e) => onStart(e, 'window'), { passive: false });

        // Click track outside window to jump
        this.track.addEventListener('click', (e) => {
            if (this.isDragging) return;
            const rect = this.track.getBoundingClientRect();
            const clickFrac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
            const curWidth = this.endFrac - this.startFrac;
            let newStart = clickFrac - (curWidth / 2);
            let newEnd = clickFrac + (curWidth / 2);

            if (newStart < 0) {
                newStart = 0;
                newEnd = curWidth;
            } else if (newEnd > 1) {
                newEnd = 1;
                newStart = 1 - curWidth;
            }
            this.setWindow(newStart, newEnd);
        });

        // Global Move & Up
        const onMove = (e) => {
            if (!this.isDragging) return;
            e.preventDefault();
            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            const rect = this.track.getBoundingClientRect();
            const deltaFrac = (clientX - this.startX) / rect.width;

            if (this.dragTarget === 'window') {
                const width = this.initialEndFrac - this.initialStartFrac;
                let newStart = this.initialStartFrac + deltaFrac;
                let newEnd = this.initialEndFrac + deltaFrac;

                if (newStart < 0) {
                    newStart = 0;
                    newEnd = width;
                } else if (newEnd > 1) {
                    newEnd = 1;
                    newStart = 1 - width;
                }
                this.updateWindowDOM(newStart, newEnd);
                this.notifyChange();
            } else if (this.dragTarget === 'left') {
                let newStart = Math.min(this.initialStartFrac + deltaFrac, this.initialEndFrac - this.minWindowFrac);
                newStart = Math.max(0, newStart);
                this.updateWindowDOM(newStart, this.initialEndFrac);
                this.notifyChange();
            } else if (this.dragTarget === 'right') {
                let newEnd = Math.max(this.initialEndFrac + deltaFrac, this.initialStartFrac + this.minWindowFrac);
                newEnd = Math.min(1, newEnd);
                this.updateWindowDOM(this.initialStartFrac, newEnd);
                this.notifyChange();
            }
        };

        const onEnd = () => {
            if (!this.isDragging) return;
            this.isDragging = false;
            this.dragTarget = null;
            document.body.classList.remove('nav-dragging-active');
            this.notifyChange(true); // Final committed change
        };

        window.addEventListener('mousemove', onMove);
        window.addEventListener('mouseup', onEnd);
        window.addEventListener('touchmove', onMove, { passive: false });
        window.addEventListener('touchend', onEnd);
        window.addEventListener('resize', () => {
            this.drawSparkline();
            this.updateWindowDOM(this.startFrac, this.endFrac);
        });
    }

    /**
     * Feed full raw series into the navigator
     */
    setData(labels, primaryData, secondaryData = [], defaultFractions = null) {
        this.fullLabels = labels || [];
        this.fullData = primaryData || [];
        this.fullSecondaryData = secondaryData || [];

        if (this.fullLabels.length === 0) {
            this.container.style.display = 'none';
            return;
        }

        this.container.style.display = 'flex';

        if (defaultFractions) {
            this.startFrac = defaultFractions.start;
            this.endFrac = defaultFractions.end;
        } else {
            // Default window selection:
            // For large sets (> 60 points, like 12h or 24h), focus on the last ~25%-35% window by default
            // so individual dots are instantly visible and not crowded, while the sparkline shows all.
            const total = this.fullLabels.length;
            if (total > 60) {
                const visibleTarget = Math.min(40, total);
                const frac = visibleTarget / total;
                this.startFrac = Math.max(0, 1 - frac);
                this.endFrac = 1.0;
            } else {
                this.startFrac = 0.0;
                this.endFrac = 1.0;
            }
        }

        this.drawSparkline();
        this.updateWindowDOM(this.startFrac, this.endFrac);
        this.notifyChange();
    }

    setWindow(startFrac, endFrac) {
        this.updateWindowDOM(startFrac, endFrac);
        this.notifyChange(true);
    }

    updateWindowDOM(start, end) {
        this.startFrac = Math.max(0, Math.min(1, start));
        this.endFrac = Math.max(this.startFrac + this.minWindowFrac, Math.min(1, end));

        const leftPct = (this.startFrac * 100).toFixed(2);
        const widthPct = ((this.endFrac - this.startFrac) * 100).toFixed(2);
        const rightPct = (100 - (this.endFrac * 100)).toFixed(2);

        if (this.curtainLeft) this.curtainLeft.style.width = `${leftPct}%`;
        if (this.brush) {
            this.brush.style.left = `${leftPct}%`;
            this.brush.style.width = `${widthPct}%`;
        }
        if (this.curtainRight) this.curtainRight.style.width = `${rightPct}%`;

        // Update timestamps
        const total = this.fullLabels.length;
        if (total > 0) {
            const startIdx = Math.min(total - 1, Math.round(this.startFrac * (total - 1)));
            const endIdx = Math.min(total - 1, Math.round(this.endFrac * (total - 1)));
            const count = endIdx - startIdx + 1;

            if (this.labelStart) this.labelStart.textContent = this.fullLabels[0] || '';
            if (this.labelEnd) this.labelEnd.textContent = this.fullLabels[total - 1] || '';
            if (this.labelInfo) {
                const startLbl = this.fullLabels[startIdx];
                const endLbl = this.fullLabels[endIdx];
                this.labelInfo.innerHTML = `Menampilkan: <strong>${startLbl} – ${endLbl}</strong> <span class="nav-pt-count">(${count} titik mentah)</span>`;
            }
        }
    }

    notifyChange(isFinal = false) {
        const total = this.fullLabels.length;
        if (total === 0) return;

        const startIdx = Math.min(total - 1, Math.round(this.startFrac * (total - 1)));
        const endIdx = Math.min(total - 1, Math.round(this.endFrac * (total - 1)));

        if (typeof this.onWindowChange === 'function') {
            this.onWindowChange(startIdx, endIdx, isFinal);
        }
    }

    drawSparkline() {
        if (!this.canvas || !this.track) return;

        const rect = this.track.getBoundingClientRect();
        if (rect.width === 0) return;

        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;

        const ctx = this.canvas.getContext('2d');
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, rect.width, rect.height);

        const data = this.fullData;
        const total = data.length;
        if (total < 2) return;

        let maxVal = Math.max(...data);
        if (this.fullSecondaryData.length > 0) {
            maxVal = Math.max(maxVal, ...this.fullSecondaryData);
        }
        if (maxVal <= 0) maxVal = 1;

        const padTop = 3;
        const padBottom = 2;
        const h = rect.height - padTop - padBottom;
        const step = rect.width / (total - 1);

        // Helper to draw an area + line sparkline
        const drawSeries = (series, strokeCol, fillCol) => {
            ctx.beginPath();
            ctx.moveTo(0, rect.height - padBottom);

            for (let i = 0; i < total; i++) {
                const x = i * step;
                const norm = Math.min(1, Math.max(0, (series[i] || 0) / maxVal));
                const y = (rect.height - padBottom) - (norm * h);
                if (i === 0) {
                    ctx.lineTo(x, y);
                } else {
                    ctx.lineTo(x, y);
                }
            }

            ctx.lineTo(rect.width, rect.height - padBottom);
            ctx.closePath();
            ctx.fillStyle = fillCol;
            ctx.fill();

            // Line stroke
            ctx.beginPath();
            for (let i = 0; i < total; i++) {
                const x = i * step;
                const norm = Math.min(1, Math.max(0, (series[i] || 0) / maxVal));
                const y = (rect.height - padBottom) - (norm * h);
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.strokeStyle = strokeCol;
            ctx.lineWidth = 1.2;
            ctx.stroke();
        };

        if (this.fullSecondaryData.length > 0) {
            drawSeries(this.fullSecondaryData, this.secondaryColor, 'rgba(16, 185, 129, 0.18)');
        }
        drawSeries(data, this.color, 'rgba(6, 182, 212, 0.28)');
    }
}
