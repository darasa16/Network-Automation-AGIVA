/**
 * Global Navigation & Search Bar Handler - PT Agiva Indonesia
 * Synchronizes search bar behavior across all pages (Device Detail, Alerts, Backups, Telegram).
 */

(function () {
    let navDevices = window.NAV_DEVICES || [];

    function escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    async function ensureNavDevices() {
        if (navDevices && navDevices.length > 0) return navDevices;
        try {
            const res = await fetch('/api/status');
            if (res.ok) {
                const data = await res.json();
                if (data.devices) {
                    navDevices = data.devices;
                    window.NAV_DEVICES = navDevices;
                }
            }
        } catch (e) {
            console.debug('Failed to fetch devices for global search', e);
        }
        return navDevices;
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

        const devices = navDevices || [];
        // Filter khusus berdasarkan Nama Vendor atau Site (sinkron dengan Dashboard utama)
        const matches = devices.filter(d =>
            (d.vendor && d.vendor.toLowerCase().includes(query)) ||
            (d.site && d.site.toLowerCase().includes(query))
        );

        if (matches.length > 0) {
            let itemsHtml = '';
            matches.forEach(dev => {
                const vendorClass = (dev.vendor || '').toLowerCase();
                const vendorInitial = (dev.vendor || 'D')[0].toUpperCase();

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

    function setupGlobalSearch() {
        const searchInput = document.getElementById('globalSearch');
        const clearBtn = document.getElementById('clearSearchBtn');
        const dropdown = document.getElementById('searchResultsDropdown');
        if (!searchInput) return;

        ensureNavDevices();

        searchInput.addEventListener('input', () => {
            const query = searchInput.value.toLowerCase().trim();
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
                searchInput.focus();
            });
        }

        document.addEventListener('click', (e) => {
            if (!e.target.closest('.nav-search')) {
                if (dropdown) dropdown.style.display = 'none';
            }
        });

        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (dropdown) dropdown.style.display = 'none';
                searchInput.blur();
            } else if (e.key === 'Enter') {
                const query = searchInput.value.toLowerCase().trim();
                const devices = navDevices || [];
                const firstMatch = devices.find(d =>
                    (d.vendor && d.vendor.toLowerCase().includes(query)) ||
                    (d.site && d.site.toLowerCase().includes(query))
                );
                if (firstMatch) {
                    window.location.href = `/device/${firstMatch.id}`;
                }
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupGlobalSearch);
    } else {
        setupGlobalSearch();
    }
})();
