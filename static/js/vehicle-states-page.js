(function () {
    var currentPage = 1;
    var pageSize = 20;
    var totalPages = 1;

    function buildQuery() {
        var p = ['page=' + currentPage, 'page_size=' + pageSize];
        var simId = document.getElementById('f-sim-id').value.trim();
        var status = document.getElementById('f-status').value;
        var vtype = document.getElementById('f-type').value;
        if (simId) p.push('sim_id=' + encodeURIComponent(simId));
        if (status) p.push('status=' + encodeURIComponent(status));
        if (vtype) p.push('vehicle_type=' + encodeURIComponent(vtype));
        return '?' + p.join('&');
    }

    function load() {
        if (!AuthModule.getToken()) return;
        showLoading(true);
        AuthModule.apiFetch('/api/vehicle-states/' + buildQuery())
            .then(function(r) { if (!r.ok) throw new Error(); return r.json(); })
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
        var tbody = document.getElementById('vs-tbody');
        var table = document.getElementById('vs-table');
        var empty = document.getElementById('empty-state');
        if (!items || !items.length) {
            table.style.display = 'none';
            empty.style.display = '';
            tbody.innerHTML = '';
            return;
        }
        table.style.display = ''; empty.style.display = 'none';
        tbody.innerHTML = items.map(function(v) {
            return '<tr onclick="window.location=\'/static/vehicle-state.html?id=' + v.id + '\'" style="cursor:pointer">'
                + '<td><a href="/static/vehicle-state.html?id=' + v.id + '">' + v.id + '</a></td>'
                + '<td>' + (v.simulation_id ? '<a href="/static/simulation.html?id=' + v.simulation_id + '">' + v.simulation_id + '</a>' : '—') + '</td>'
                + '<td>' + (v.vehicle_type || '—') + '</td>'
                + '<td>' + (v.status || '—') + '</td>'
                + '<td>' + (v.lat != null ? v.lat.toFixed(5) : '—') + '</td>'
                + '<td>' + (v.lng != null ? v.lng.toFixed(5) : '—') + '</td>'
                + '<td>' + (v.fuel_level != null ? v.fuel_level.toFixed(1) : '—') + '</td>'
                + '<td>' + (v.snow_loaded_m3 != null ? v.snow_loaded_m3 : '—') + '</td>'
                + '<td>' + (v.distance_travelled_km != null ? v.distance_travelled_km.toFixed(2) : '—') + ' км</td>'
                + '<td>' + (v.tick != null ? v.tick : '—') + '</td>'
                + '</tr>';
        }).join('');
    }

    function renderPagination(pages) {
        var el = document.getElementById('pagination');
        if (!el || pages <= 1) { if (el) el.innerHTML = ''; return; }
        var html = '<button onclick="changePage(' + (currentPage - 1) + ')"' + (currentPage <= 1 ? ' disabled' : '') + '>&laquo;</button>'
            + '<span class="pagination-info">Стр. ' + currentPage + ' / ' + pages + '</span>'
            + '<button onclick="changePage(' + (currentPage + 1) + ')"' + (currentPage >= pages ? ' disabled' : '') + '>&raquo;</button>';
        el.innerHTML = html;
    }

    window.changePage = function(p) { if (p < 1 || p > totalPages) return; currentPage = p; load(); };

    function showLoading(s) { var e = document.getElementById('loading'); if (e) e.style.display = s ? '' : 'none'; }

    document.getElementById('btn-filter').addEventListener('click', function() { currentPage = 1; load(); });
    document.getElementById('btn-reset').addEventListener('click', function() {
        ['f-sim-id'].forEach(function(id) { var e = document.getElementById(id); if (e) e.value = ''; });
        ['f-status', 'f-type'].forEach(function(id) { var e = document.getElementById(id); if (e) e.selectedIndex = 0; });
        currentPage = 1; load();
    });

    var urlParams = new URLSearchParams(window.location.search);
    var simParam = urlParams.get('sim_id');
    if (simParam) document.getElementById('f-sim-id').value = simParam;
    if (AuthModule.getToken()) load();
})();
