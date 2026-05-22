(function () {
    var currentPage = 1;
    var pageSize = 20;
    var totalPages = 1;

    function getSimId() { return document.getElementById('f-sim-id').value.trim(); }

    function load() {
        if (!AuthModule.getToken()) return;
        showLoading(true);
        var params = ['page=' + currentPage, 'page_size=' + pageSize];
        var stepOwnId = document.getElementById('f-step-own-id').value.trim();
        var simId = document.getElementById('f-sim-id').value.trim();
        var tMin = document.getElementById('f-tick-min').value;
        var tMax = document.getElementById('f-tick-max').value;
        var createdFrom = document.getElementById('f-created-from').value;
        var createdTo = document.getElementById('f-created-to').value;
        var updFrom = document.getElementById('f-upd-from').value;
        var updTo = document.getElementById('f-upd-to').value;
        var enRouteMin = document.getElementById('f-en-route-min').value;
        var enRouteMax = document.getElementById('f-en-route-max').value;
        var cleaningMin = document.getElementById('f-cleaning-min').value;
        var cleaningMax = document.getElementById('f-cleaning-max').value;
        var dumpingMin = document.getElementById('f-dumping-min').value;
        var dumpingMax = document.getElementById('f-dumping-max').value;
        var maintenanceMin = document.getElementById('f-maintenance-min').value;
        var maintenanceMax = document.getElementById('f-maintenance-max').value;
        var avgFuelMin = document.getElementById('f-avg-fuel-min').value;
        var avgFuelMax = document.getElementById('f-avg-fuel-max').value;
        var avgSnowMin = document.getElementById('f-avg-snow-min').value;
        var avgSnowMax = document.getElementById('f-avg-snow-max').value;
        if (stepOwnId) params.push('step_own_id=' + encodeURIComponent(stepOwnId));
        if (simId) params.push('sim_id=' + simId);
        if (tMin) params.push('tick_min=' + tMin);
        if (tMax) params.push('tick_max=' + tMax);
        if (createdFrom) params.push('created_at_from=' + encodeURIComponent(createdFrom));
        if (createdTo) params.push('created_at_to=' + encodeURIComponent(createdTo));
        if (updFrom) params.push('updated_at_from=' + encodeURIComponent(updFrom));
        if (updTo) params.push('updated_at_to=' + encodeURIComponent(updTo));
        if (enRouteMin) params.push('vs_en_route_min=' + enRouteMin);
        if (enRouteMax) params.push('vs_en_route_max=' + enRouteMax);
        if (cleaningMin) params.push('vs_cleaning_min=' + cleaningMin);
        if (cleaningMax) params.push('vs_cleaning_max=' + cleaningMax);
        if (dumpingMin) params.push('vs_dumping_min=' + dumpingMin);
        if (dumpingMax) params.push('vs_dumping_max=' + dumpingMax);
        if (maintenanceMin) params.push('vs_maintenance_min=' + maintenanceMin);
        if (maintenanceMax) params.push('vs_maintenance_max=' + maintenanceMax);
        if (avgFuelMin) params.push('avg_fuel_min=' + avgFuelMin);
        if (avgFuelMax) params.push('avg_fuel_max=' + avgFuelMax);
        if (avgSnowMin) params.push('avg_snow_min=' + avgSnowMin);
        if (avgSnowMax) params.push('avg_snow_max=' + avgSnowMax);
        AuthModule.apiFetch('/api/simulation-steps/?' + params.join('&'))
            .then(function(r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
            .then(function(d) {
                totalPages = d.total_pages || 1;
                renderTable(d.items, d.total);
                renderPagination(totalPages);
                showLoading(false);
            })
            .catch(function() { showLoading(false); });
    }

    function renderTable(items, total) {
        var count = document.getElementById('result-count');
        if (count) count.textContent = 'Найдено: ' + (total || 0);
        var tbody = document.getElementById('steps-tbody');
        var table = document.getElementById('steps-table');
        var empty = document.getElementById('empty-state');
        if (!items || !items.length) {
            table.style.display = 'none';
            empty.style.display = '';
            tbody.innerHTML = '';
            return;
        }
        table.style.display = ''; empty.style.display = 'none';
        tbody.innerHTML = items.map(function(s) {
            var ss = {};
            try { ss = JSON.parse(s.sim_state || '{}'); } catch(e) {}
            return '<tr onclick="window.location=\'/static/simulation-step.html?id=' + s.id + '\'" style="cursor:pointer">'
                + '<td style="font-size:0.75rem;color:var(--text-dim)"><a href="/static/simulation-step.html?id=' + s.id + '">' + s.id + '</a></td>'
                + '<td>' + (s.simulation_id ? '<a href="/static/simulation.html?id=' + s.simulation_id + '" onclick="event.stopPropagation()">' + s.simulation_id + '</a>' : '—') + '</td>'
                + '<td>' + s.tick + '</td>'
                + '<td>' + (s.roads_cleaned || 0) + '%</td>'
                + '<td>' + (s.snow_collected || 0) + '</td>'
                + '<td>' + (s.fuel_spent || 0) + '</td>'
                + '<td>' + (s.breakdowns || 0) + '</td>'
                + '<td>' + (ss.vehicles_en_route != null ? ss.vehicles_en_route : '—') + '</td>'
                + '<td>' + (ss.vehicles_cleaning != null ? ss.vehicles_cleaning : '—') + '</td>'
                + '<td>' + (ss.vehicles_dumping != null ? ss.vehicles_dumping : '—') + '</td>'
                + '<td>' + (ss.vehicles_maintenance != null ? ss.vehicles_maintenance : '—') + '</td>'
                + '<td>' + (ss.avg_fuel_pct != null ? ss.avg_fuel_pct : '—') + '</td>'
                + '<td>' + (ss.avg_snow_load_pct != null ? ss.avg_snow_load_pct : '—') + '</td>'
                + '<td>' + fmtDate(s.created_at) + '</td>'
                + '<td>' + fmtDate(s.updated_at) + '</td>'
                + '</tr>';
        }).join('');
    }

    function renderPagination(pages) {
        var el = document.getElementById('pagination');
        if (!el || pages <= 1) { if (el) el.innerHTML = ''; return; }
        var html = '<button onclick="changePage(' + (currentPage - 1) + ')"' + (currentPage <= 1 ? ' disabled' : '') + '>&laquo;</button>';
        html += '<span class="pagination-info">Стр. ' + currentPage + ' / ' + pages + '</span>';
        html += '<button onclick="changePage(' + (currentPage + 1) + ')"' + (currentPage >= pages ? ' disabled' : '') + '>&raquo;</button>';
        el.innerHTML = html;
    }

    window.changePage = function(p) { if (p < 1 || p > totalPages) return; currentPage = p; load(); };

    function showLoading(s) { var e = document.getElementById('loading'); if (e) e.style.display = s ? '' : 'none'; }
    function fmtDate(d) { if (!d) return '—'; return new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }); }

    document.getElementById('btn-filter').addEventListener('click', function() { currentPage = 1; load(); });
    document.getElementById('btn-reset').addEventListener('click', function() {
        ['f-step-own-id','f-sim-id','f-tick-min','f-tick-max','f-created-from','f-created-to','f-upd-from','f-upd-to',
         'f-en-route-min','f-en-route-max','f-cleaning-min','f-cleaning-max','f-dumping-min','f-dumping-max',
         'f-maintenance-min','f-maintenance-max','f-avg-fuel-min','f-avg-fuel-max','f-avg-snow-min','f-avg-snow-max'].forEach(function(id) { var e = document.getElementById(id); if (e) e.value = ''; });
        currentPage = 1; load();
    });

    var urlParams = new URLSearchParams(window.location.search);
    var simIdParam = urlParams.get('sim_id');
    if (simIdParam) {
        document.getElementById('f-sim-id').value = simIdParam;
    }
    if (AuthModule.getToken()) load();
})();
