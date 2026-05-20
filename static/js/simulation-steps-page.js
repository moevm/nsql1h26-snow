(function () {
    var currentPage = 1;
    var pageSize = 20;
    var totalPages = 1;

    function getSimId() { return document.getElementById('f-sim-id').value.trim(); }

    function load() {
        if (!AuthModule.getToken()) return;
        showLoading(true);
        var params = ['page=' + currentPage, 'page_size=' + pageSize];
        var simId =  document.getElementById('f-sim-id').value.trim();
        var tMin = document.getElementById('f-tick-min').value;
        var tMax = document.getElementById('f-tick-max').value;
        if (simId) params.push('sim_id=' + simId);
        if (tMin) params.push('tick_min=' + tMin);
        if (tMax) params.push('tick_max=' + tMax);
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
            return '<tr onclick="window.location=\'/static/simulation-step.html?id=' + s.id + '\'" style="cursor:pointer">'
                + '<td style="font-size:0.75rem;color:var(--text-dim)"><a href="/static/simulation-step.html?id=' + s.id + '">' + s.id + '</a></td>'
                + '<td>' + s.tick + '</td>'
                + '<td>' + (s.roads_cleaned || 0) + '%</td>'
                + '<td>' + (s.snow_collected || 0) + '</td>'
                + '<td>' + (s.fuel_spent || 0) + '</td>'
                + '<td>' + (s.breakdowns || 0) + '</td>'
                + '<td>' + fmtDate(s.time_created) + '</td>'
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
        ['f-sim-id', 'f-tick-min', 'f-tick-max'].forEach(function(id) { var e = document.getElementById(id); if (e) e.value = ''; });
        currentPage = 1; load();
    });

    var urlParams = new URLSearchParams(window.location.search);
    var simIdParam = urlParams.get('sim_id');
    if (simIdParam) {
        document.getElementById('f-sim-id').value = simIdParam;
    }
    if (AuthModule.getToken()) load();
})();
