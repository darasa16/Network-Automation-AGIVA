/**
 * Global Navigation & Omni-Search (Command Palette) Handler - PT Agiva Indonesia
 * Pattern 3: Universal Omni-Search across Devices, Alerts, Backups, and Quick Navigation.
 */

(function () {
    let debounceTimer = null;
    let selectedIndex = -1;
    let currentResults = [];

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    async function performSearch(query) {
        const dropdown = document.getElementById('searchResultsDropdown');
        if (!dropdown) return;

        if (!query) {
            dropdown.style.display = 'none';
            dropdown.innerHTML = '';
            currentResults = [];
            selectedIndex = -1;
            return;
        }

        try {
            const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
            if (!res.ok) throw new Error('Search failed');
            const data = await res.json();
            renderDropdown(data, query);
        } catch (err) {
            console.error('Omni-search error:', err);
        }
    }

    function renderDropdown(data, query) {
        const dropdown = document.getElementById('searchResultsDropdown');
        if (!dropdown) return;

        const categories = data.categories || {};
        const devices = categories.devices || [];
        const alerts = categories.alerts || [];
        const incidents = categories.incidents || [];
        const backups = categories.backups || [];
        const telegram = categories.telegram || [];
        const navItems = categories.navigation || [];

        currentResults = [];
        selectedIndex = -1;

        if (data.total_results === 0) {
            dropdown.innerHTML = `
                <div class="search-dropdown-empty">
                    <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="#64748b" stroke-width="1.8" style="margin: 0 auto 8px; display: block;">
                        <circle cx="11" cy="11" r="8"></circle>
                        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                    </svg>
                    No devices, alerts, incidents, backups, or commands found matching "<strong>${escapeHtml(query)}</strong>"
                </div>
                <div class="search-dropdown-footer">
                    <span>Press <kbd class="search-kbd-key">ESC</kbd> to close</span>
                </div>
            `;
            dropdown.style.display = 'block';
            return;
        }

        let html = '<div class="search-dropdown-list">';

        // 1. Devices Section
        if (devices.length > 0) {
            html += `
                <div class="search-group-header">
                    <span>Network Devices</span>
                </div>
            `;
            const topDevs = devices.slice(0, 5);
            topDevs.forEach(dev => {
                const itemIdx = currentResults.length;
                currentResults.push(dev.url);
                const isUp = dev.status === 'UP';
                const statusBadge = isUp 
                    ? '<span class="status-badge badge-up" style="font-size: 10px; padding: 2px 7px;"><span class="badge-dot-green"></span> UP</span>'
                    : '<span class="status-badge badge-down" style="font-size: 10px; padding: 2px 7px;"><span class="badge-dot-red"></span> DOWN</span>';
                
                html += `
                    <div class="search-dropdown-item" data-index="${itemIdx}" onclick="window.navigateToSearchResult('${dev.url}')">
                        <div class="search-item-left">
                            <div class="search-item-icon-box search-icon-device">
                                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                                    <rect x="2" y="2" width="20" height="8" rx="2" ry="2"></rect>
                                    <rect x="2" y="14" width="20" height="8" rx="2" ry="2"></rect>
                                    <line x1="6" y1="6" x2="6.01" y2="6"></line>
                                    <line x1="6" y1="18" x2="6.01" y2="18"></line>
                                </svg>
                            </div>
                            <div class="search-item-text">
                                <div class="search-item-title">${escapeHtml(dev.name)}</div>
                                <div class="search-item-desc">
                                    <span class="vendor-badge badge-${(dev.vendor || '').toLowerCase().replace(/\s+/g, '-')}" style="padding: 1px 6px; font-size: 9.5px;">${escapeHtml(dev.vendor)}</span>
                                    <span>•</span>
                                    <span>Site: ${escapeHtml(dev.site)}</span>
                                    <span>•</span>
                                    <code style="color: #38bdf8; font-size: 11px;">${escapeHtml(dev.ip)}</code>
                                </div>
                            </div>
                        </div>
                        <div class="search-item-right">
                            ${statusBadge}
                        </div>
                    </div>
                `;
            });
            html += `
                <a class="search-view-all-cta" href="/#monitored-devices">
                    <span>Lihat semua perangkat di Dashboard</span>
                    <span class="cta-arrow">&rarr;</span>
                </a>
            `;
        }

        // 2. Active Alerts Section
        if (alerts.length > 0) {
            html += `
                <div class="search-group-header">
                    <span>Active Alerts (Action Required)</span>
                </div>
            `;
            const topAlerts = alerts.slice(0, 5);
            topAlerts.forEach(a => {
                const itemIdx = currentResults.length;
                currentResults.push(a.url);
                const isCrit = a.severity === 'CRITICAL';
                const iconClass = isCrit ? 'search-icon-alert-crit' : 'search-icon-alert-warn';
                const sevBadge = isCrit
                    ? '<span class="alert-severity-badge badge-crit" style="font-size: 9.5px; padding: 1px 6px;">CRIT</span>'
                    : '<span class="alert-severity-badge badge-warn" style="font-size: 9.5px; padding: 1px 6px;">WARN</span>';

                html += `
                    <div class="search-dropdown-item" data-index="${itemIdx}" onclick="window.navigateToSearchResult('${a.url}')">
                        <div class="search-item-left">
                            <div class="search-item-icon-box ${iconClass}">
                                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                                    <line x1="12" y1="9" x2="12" y2="13"></line>
                                    <line x1="12" y1="17" x2="12.01" y2="17"></line>
                                </svg>
                            </div>
                            <div class="search-item-text">
                                <div class="search-item-title">${escapeHtml(a.type)} - ${escapeHtml(a.device_name)}</div>
                                <div class="search-item-desc">
                                    <span>${escapeHtml(a.message)}</span>
                                    <span>•</span>
                                    <span>${escapeHtml(a.triggered_at)}</span>
                                </div>
                            </div>
                        </div>
                        <div class="search-item-right">
                            ${sevBadge}
                        </div>
                    </div>
                `;
            });
            html += `
                <a class="search-view-all-cta" href="/alerts?search=${encodeURIComponent(query)}#alertsTable">
                    <span>Lihat & Filter semua alert aktif di Alerts</span>
                    <span class="cta-arrow">&rarr;</span>
                </a>
            `;
        }

        // 3. Incident Log & Cooldown History Section
        if (incidents.length > 0) {
            html += `
                <div class="search-group-header">
                    <span>Incident Log & Cooldown History</span>
                </div>
            `;
            const topIncidents = incidents.slice(0, 5);
            topIncidents.forEach(inc => {
                const itemIdx = currentResults.length;
                currentResults.push(inc.url);
                const isCrit = inc.severity === 'CRITICAL';
                const isCooldown = inc.status === 'AUTO_COOLDOWN';
                const isResolved = inc.status === 'RESOLVED_ALERT';
                
                let statusBadge = '';
                if (isCooldown) {
                    statusBadge = '<span class="status-badge" style="background: rgba(234, 179, 8, 0.15); color: #facc15; border: 1px solid rgba(234, 179, 8, 0.3); font-size: 9.5px; padding: 1px 6px;">COOLDOWN</span>';
                } else if (isResolved) {
                    statusBadge = '<span class="status-badge badge-up" style="font-size: 9.5px; padding: 1px 6px;">RESOLVED</span>';
                } else {
                    statusBadge = isCrit
                        ? '<span class="alert-severity-badge badge-crit" style="font-size: 9.5px; padding: 1px 6px;">CRIT</span>'
                        : '<span class="alert-severity-badge badge-warn" style="font-size: 9.5px; padding: 1px 6px;">WARN</span>';
                }

                const iconClass = isCooldown ? 'search-icon-cooldown' : (isCrit ? 'search-icon-alert-crit' : 'search-icon-incident');

                html += `
                    <div class="search-dropdown-item" data-index="${itemIdx}" onclick="window.navigateToSearchResult('${inc.url}')">
                        <div class="search-item-left">
                            <div class="search-item-icon-box ${iconClass}">
                                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path>
                                    <polyline points="9 12 11 14 15 10"></polyline>
                                </svg>
                            </div>
                            <div class="search-item-text">
                                <div class="search-item-title">${escapeHtml(inc.code)} • ${escapeHtml(inc.type)} - ${escapeHtml(inc.device_name)}</div>
                                <div class="search-item-desc">
                                    <span>Peak: ${escapeHtml(inc.peak_metric)}</span>
                                    <span>•</span>
                                    <span>Duration: ${escapeHtml(inc.duration)}</span>
                                    <span>•</span>
                                    <span>Started: ${escapeHtml(inc.started_at)}</span>
                                </div>
                            </div>
                        </div>
                        <div class="search-item-right">
                            ${statusBadge}
                        </div>
                    </div>
                `;
            });
            html += `
                <a class="search-view-all-cta" href="/alerts?search=${encodeURIComponent(query)}#incidentsTable">
                    <span>Lihat & Filter semua riwayat insiden / cooldown di Incident Log</span>
                    <span class="cta-arrow">&rarr;</span>
                </a>
            `;
        }

        // 4. Backups Section
        if (backups.length > 0) {
            html += `
                <div class="search-group-header">
                    <span>Configuration Backups</span>
                </div>
            `;
            const topBackups = backups.slice(0, 5);
            topBackups.forEach(b => {
                const itemIdx = currentResults.length;
                currentResults.push(b.url);

                html += `
                    <div class="search-dropdown-item" data-index="${itemIdx}" onclick="window.navigateToSearchResult('${b.url}')">
                        <div class="search-item-left">
                            <div class="search-item-icon-box search-icon-backup">
                                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path>
                                    <polyline points="17 21 17 13 7 13 7 21"></polyline>
                                    <polyline points="7 3 7 8 15 8"></polyline>
                                </svg>
                            </div>
                            <div class="search-item-text">
                                <div class="search-item-title">${escapeHtml(b.file_name)}</div>
                                <div class="search-item-desc">
                                    <span style="background: rgba(232, 165, 118, 0.15); color: var(--color-copper); border: 1px solid rgba(232, 165, 118, 0.3); border-radius: 4px; padding: 0 5px; font-size: 9px; font-weight: 600;">${escapeHtml(b.category || 'CONFIG')}</span>
                                    <span>•</span>
                                    <span>${escapeHtml(b.device_name)}</span>
                                    <span>•</span>
                                    <span>Site: ${escapeHtml(b.site || '-')}</span>
                                    <span>•</span>
                                    <span>${escapeHtml(b.date)}</span>
                                    <span>•</span>
                                    <span>${escapeHtml(b.size)}</span>
                                </div>
                            </div>
                        </div>
                        <div class="search-item-right">
                            <span class="status-badge badge-up" style="font-size: 10px; padding: 1px 6px;">${escapeHtml(b.status)}</span>
                        </div>
                    </div>
                `;
            });
            html += `
                <a class="search-view-all-cta" href="/backups?search=${encodeURIComponent(query)}#backupsTable">
                    <span>Lihat & Filter semua file di Backups</span>
                    <span class="cta-arrow">&rarr;</span>
                </a>
            `;
        }

        // 4. Telegram Section
        if (telegram.length > 0) {
            html += `
                <div class="search-group-header">
                    <span>Telegram Bot Integration</span>
                </div>
            `;
            // Keep all matching whitelist engineer entries (small admin count as requested), slice other telegram items to top 5
            const whitelistItems = telegram.filter(t => t.is_whitelist || (t.url && t.url.includes('whitelist-row')));
            const otherTgItems = telegram.filter(t => !t.is_whitelist && (!t.url || !t.url.includes('whitelist-row'))).slice(0, 5);
            const displayTelegram = [...whitelistItems, ...otherTgItems];

            displayTelegram.forEach(t => {
                const itemIdx = currentResults.length;
                currentResults.push(t.url);
                const badge = t.status === 'ACTIVE' 
                    ? '<span class="status-badge badge-up" style="font-size: 10px; padding: 2px 7px;"><span class="badge-dot-green"></span> ACTIVE</span>'
                    : (t.status === 'COMMAND' 
                        ? '<span class="vendor-badge badge-aruba" style="font-size: 9.5px; padding: 1px 6px;">BOT CMD</span>'
                        : (t.status === 'SENT'
                            ? '<span class="status-badge badge-up" style="font-size: 10px; padding: 2px 7px;"><span class="badge-dot-green"></span> SENT</span>'
                            : '<span class="status-badge badge-down" style="font-size: 10px; padding: 2px 7px;">INACTIVE</span>'));

                html += `
                    <div class="search-dropdown-item" data-index="${itemIdx}" onclick="window.navigateToSearchResult('${t.url}')">
                        <div class="search-item-left">
                            <div class="search-item-icon-box search-icon-telegram">
                                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                                    <line x1="22" y1="2" x2="11" y2="13"></line>
                                    <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                                </svg>
                            </div>
                            <div class="search-item-text">
                                <div class="search-item-title">${escapeHtml(t.title)}</div>
                                <div class="search-item-desc">${escapeHtml(t.desc)}</div>
                            </div>
                        </div>
                        <div class="search-item-right">
                            ${badge}
                        </div>
                    </div>
                `;
            });
            html += `
                <a class="search-view-all-cta" href="/telegram?search=${encodeURIComponent(query)}#tgLogsTable">
                    <span>Lihat & Filter semua log di Telegram</span>
                    <span class="cta-arrow">&rarr;</span>
                </a>
            `;
        }

        // 5. Navigation Section
        if (navItems.length > 0) {
            html += `
                <div class="search-group-header">
                    <span>Navigation Menu</span>
                </div>
            `;
            navItems.forEach(n => {
                const itemIdx = currentResults.length;
                currentResults.push(n.url);

                html += `
                    <div class="search-dropdown-item" data-index="${itemIdx}" onclick="window.navigateToSearchResult('${n.url}')">
                        <div class="search-item-left">
                            <div class="search-item-icon-box search-icon-nav">
                                <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                                    <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
                                    <polyline points="2 17 12 22 22 17"></polyline>
                                    <polyline points="2 12 12 17 22 12"></polyline>
                                </svg>
                            </div>
                            <div class="search-item-text">
                                <div class="search-item-title">${escapeHtml(n.title)}</div>
                                <div class="search-item-desc">${escapeHtml(n.desc)}</div>
                            </div>
                        </div>
                    </div>
                `;
            });
        }

        html += '</div>';

        // Keyboard guidance footer
        html += `
            <div class="search-dropdown-footer">
                <div class="search-kbd-guide">
                    <kbd class="search-kbd-key">↑</kbd> <kbd class="search-kbd-key">↓</kbd> Navigate
                    <span style="margin: 0 4px;">•</span>
                    <kbd class="search-kbd-key">↵</kbd> Select
                </div>
                <div>
                    <kbd class="search-kbd-key">ESC</kbd> Close
                </div>
            </div>
        `;

        dropdown.innerHTML = html;
        dropdown.style.display = 'block';

        // Auto select first item
        if (currentResults.length > 0) {
            setSelectedIndex(0);
        }
    }

    function setSelectedIndex(idx) {
        const items = document.querySelectorAll('.search-dropdown-item');
        if (items.length === 0) return;

        items.forEach(el => el.classList.remove('is-selected'));
        if (idx >= 0 && idx < items.length) {
            selectedIndex = idx;
            items[idx].classList.add('is-selected');
            items[idx].scrollIntoView({ block: 'nearest' });
        } else {
            selectedIndex = -1;
        }
    }

    function setupOmniSearch() {
        const searchInput = document.getElementById('globalSearch');
        const clearBtn = document.getElementById('clearSearchBtn');
        const dropdown = document.getElementById('searchResultsDropdown');
        if (!searchInput) return;

        // Typing with Debounce
        searchInput.addEventListener('input', () => {
            const query = searchInput.value.trim();
            if (clearBtn) clearBtn.style.display = query ? 'flex' : 'none';

            clearTimeout(debounceTimer);
            if (!query) {
                if (dropdown) dropdown.style.display = 'none';
                return;
            }
            debounceTimer = setTimeout(() => {
                performSearch(query);
            }, 180);
        });

        // Focus & Blur
        searchInput.addEventListener('focus', () => {
            const query = searchInput.value.trim();
            if (query) {
                performSearch(query);
            }
        });

        if (clearBtn) {
            clearBtn.addEventListener('click', () => {
                searchInput.value = '';
                clearBtn.style.display = 'none';
                if (dropdown) dropdown.style.display = 'none';
                searchInput.focus();
            });
        }

        // Close on Click Outside
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.nav-search')) {
                if (dropdown) dropdown.style.display = 'none';
            }
        });

        // Keyboard Navigation (Arrows, Enter, Escape)
        searchInput.addEventListener('keydown', (e) => {
            const items = document.querySelectorAll('.search-dropdown-item');
            if (e.key === 'Escape') {
                if (dropdown) dropdown.style.display = 'none';
                searchInput.blur();
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (items.length > 0) {
                    const next = (selectedIndex + 1) % items.length;
                    setSelectedIndex(next);
                }
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (items.length > 0) {
                    const prev = (selectedIndex - 1 + items.length) % items.length;
                    setSelectedIndex(prev);
                }
            } else if (e.key === 'Enter') {
                e.preventDefault();
                if (selectedIndex >= 0 && selectedIndex < currentResults.length) {
                    window.navigateToSearchResult(currentResults[selectedIndex]);
                } else if (currentResults.length > 0) {
                    window.navigateToSearchResult(currentResults[0]);
                }
            }
        });
    }

    // Navigation and Target Highlighting Logic
    function triggerHighlightForId(targetId, retries = 35) {
        if (!targetId) return;

        targetId = String(targetId).replace(/^#/, '');

        // 1. Exact pagination and table target check
        // Special handling for backups paginated rows
        if (targetId.startsWith('backup-row-') || targetId.startsWith('backup-')) {
            if (typeof window.checkTargetBackupPage === 'function') {
                window.checkTargetBackupPage(targetId);
                if (typeof window.renderBackupsTable === 'function') {
                    window.renderBackupsTable();
                }
            }
        }

        // Special handling for telegram whitelist paginated rows
        if (targetId.startsWith('whitelist-row-') || targetId.startsWith('whitelist-')) {
            if (typeof window.checkTargetWhitelistPage === 'function') {
                window.checkTargetWhitelistPage(targetId);
                if (typeof window.renderWhitelistTable === 'function') {
                    window.renderWhitelistTable();
                }
            }
        }

        // Special handling for telegram paginated logs
        if (targetId.startsWith('msglog-row-') || targetId.startsWith('msglog-')) {
            if (typeof window.checkTargetLogPage === 'function') {
                window.checkTargetLogPage(targetId);
                if (typeof window.renderLogsTable === 'function') {
                    window.renderLogsTable();
                }
            }
        }

        // Special handling for paginated alerts
        if (targetId.startsWith('alert-row-') || targetId.startsWith('alert-')) {
            if (typeof window.checkTargetAlertPage === 'function') {
                window.checkTargetAlertPage(targetId);
                if (typeof window.renderAlertsTable === 'function') {
                    window.renderAlertsTable();
                }
            }
        }

        // Special handling for paginated incident logs
        if (targetId.startsWith('inc-row-') || targetId.startsWith('incident-row-') || targetId.startsWith('inc-')) {
            if (typeof window.checkTargetIncidentPage === 'function') {
                window.checkTargetIncidentPage(targetId);
                if (typeof window.renderIncidentsTable === 'function') {
                    window.renderIncidentsTable();
                }
            }
        }

        const el = document.getElementById(targetId);
        if (!el) {
            if (retries > 0) {
                setTimeout(() => triggerHighlightForId(targetId, retries - 1), 60);
            }
            return;
        }

        // If row itself was hidden by inline style
        const row = el.tagName.toLowerCase() === 'tr' ? el : el.closest('tr');
        if (row && row.style.display === 'none') {
            row.style.display = '';
        }

        // 2. Clear any existing highlights
        document.querySelectorAll('.search-target-highlight').forEach(n => n.classList.remove('search-target-highlight'));

        // 3. Center element in viewport (taking fixed navbar into account)
        const scrollTarget = () => {
            const navbar = document.querySelector('.navbar');
            const navHeight = navbar ? navbar.offsetHeight : 70;
            const elRect = el.getBoundingClientRect();
            const targetY = window.pageYOffset + elRect.top - (window.innerHeight / 2) + (elRect.height / 2);

            window.scrollTo({
                top: Math.max(0, targetY),
                behavior: 'smooth'
            });

            // Ensure horizontal scroll inside container if overflowed
            const container = el.closest('.table-responsive');
            if (container) {
                const elLeft = el.offsetLeft;
                if (elLeft < container.scrollLeft || elLeft > container.scrollLeft + container.clientWidth) {
                    container.scrollTo({ left: Math.max(0, elLeft - 40), behavior: 'smooth' });
                }
            }
        };

        requestAnimationFrame(() => {
            scrollTarget();
            setTimeout(scrollTarget, 160);
        });

        // 4. Trigger Agiva Copper Highlight Animation
        void el.offsetWidth; // Force CSS reflow
        el.classList.add('search-target-highlight');

        // 5. Keep highlight active for animation duration, then remove class
        setTimeout(() => {
            el.classList.remove('search-target-highlight');
        }, 3600);
    }

    window.triggerHighlightForId = triggerHighlightForId;

    window.scrollToTableTop = function(elementId) {
        requestAnimationFrame(() => {
            const el = document.getElementById(elementId);
            if (!el) return;
            const navbar = document.querySelector('.navbar');
            const navOffset = (navbar ? navbar.offsetHeight : 70) + 16;
            const targetY = el.getBoundingClientRect().top + window.pageYOffset - navOffset;
            window.scrollTo({ top: Math.max(0, targetY), behavior: 'smooth' });
        });
    };

    function handleTargetHashHighlight() {
        const hash = window.location.hash;
        if (!hash || hash.length < 2) return;
        const targetId = hash.substring(1);
        triggerHighlightForId(targetId);
    }

    window.navigateToSearchResult = function(url) {
        if (!url) return;
        const currentPath = window.location.pathname.replace(/\/$/, '') || '/';
        const parts = url.split('#');
        const targetPath = parts[0].replace(/\/$/, '') || '/';
        const targetHash = parts[1] || '';

        const dropdown = document.getElementById('searchResultsDropdown');
        if (dropdown) dropdown.style.display = 'none';

        const searchInput = document.getElementById('globalSearch');
        if (searchInput) {
            searchInput.value = '';
            searchInput.blur();
        }

        const clearBtn = document.getElementById('clearSearchBtn');
        if (clearBtn) clearBtn.style.display = 'none';

        const isSamePage = (targetPath === currentPath) ||
            ((targetPath === '/' || targetPath === '') && (currentPath === '/' || currentPath === '/index.html')) ||
            (targetPath === '/telegram' && currentPath === '/telegram.html') ||
            (targetPath === '/alerts' && currentPath === '/alerts.html') ||
            (targetPath === '/backups' && currentPath === '/backups.html');

        if (isSamePage) {
            if (targetHash) {
                if (window.location.hash !== '#' + targetHash) {
                    window.location.hash = '#' + targetHash;
                }
                triggerHighlightForId(targetHash);
            }
        } else {
            window.location.href = url;
        }
    };

    // Hash change event listener (for browser back/forward or hash changes)
    window.addEventListener('hashchange', handleTargetHashHighlight);

    // Page Load Handlers
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            setupOmniSearch();
            handleTargetHashHighlight();
        });
    } else {
        setupOmniSearch();
        handleTargetHashHighlight();
    }

    // Also trigger on full window load (after all stylesheets/fonts loaded)
    window.addEventListener('load', () => {
        handleTargetHashHighlight();
    });
})();
