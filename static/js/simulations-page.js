(function () {
    var currentPage = 1;
    var pageSize = 20;
    var totalPages = 1;

    function getFilters() {
        return {
            name: document.getElementById('f-name').value.trim() || null,
            status: document.getElementById('f-status').value || null,
            vehicles_min: document.getElementById('f-veh-min').value || null,
            vehicles_max: document.getElementById('f-veh-max').value || null,
            date_from: document.getElementById('f-date-from').value ? document.getElementById('f-date-from').value + 'T00:00:00' : null,
            date_to: document.getElementById('f-date-to').value ? document.getElementById('f-date-to').value + 'T23:59:59' : null,
        };
    }

    function buildQuery(f) {
        var p = ['page=' + currentPage, 'page_size=' + pageSize];
        if (f.name) p.push('name=' + encodeURIComponent(f.name));
        if (f.status) p.push('status=' + encodeURIComponent(f.status));
        if (f.vehicles_min) p.push('vehicles_min=' + f.vehicles_min);
        if (f.vehicles_max) p.push('vehicles_max=' + f.vehicles_max);
        if (f.date_from) p.push('date_from=' + encodeURIComponent(f.date_from));
        if (f.date_to) p.push('date_to=' + encodeURIComponent(f.date_to));
        return '?' + p.join('&');
    }

    function loadSims() {
        if (!AuthModule.getToken()) return;
        showLoading(true);
        AuthModule.apiFetch('/api/simulation/' + buildQuery(getFilters()))
            .then(function (res) { if (!res.ok) throw new Error('Fetch failed'); return res.json(); })
            .then(function (data) {
                totalPages = data.total_pages || 1;
                render(data.items, data.total, data.page, data.total_pages);
                showLoading(false);
            })
            .catch(function () { showLoading(false); showEmpty(true); });
    }

    function statusBadge(s) {
        var cls = { running: 'badge-running', paused: 'badge-paused', finished: 'badge-finished', idle: 'badge-idle', error: 'badge-error' };
        var labels = { running: 'Запущена', paused: 'Пауза', finished: 'Завершена', idle: 'Ожидание', error: 'Ошибка' };
        return '<span class="badge ' + (cls[s] || '') + '">' + (labels[s] || s) + '</span>';
    }

    function render(sims, total, page, pages) {
        var tbody = document.getElementById('sims-tbody');
        var table = document.getElementById('sims-table');
        var empty = document.getElementById('empty-state');
        var count = document.getElementById('result-count');
        if (count) count.textContent = 'Найдено: ' + (total || 0);
        if (!sims || !sims.length) {
            table.style.display = 'none';
            empty.style.display = '';
            renderPagination(1);
            return;
        }
        table.style.display = ''; empty.style.display = 'none';
        tbody.innerHTML = sims.map(function (s) {
            return '<tr onclick="window.location=\'/static/simulation.html?id=' + s.id + '\'" style="cursor:pointer">'
                + '<td><a href="/static/simulation.html?id=' + s.id + '">' + s.id + '</a></td>'
                + '<td>' + (s.name || '<span style="color:var(--text-dim)">—</span>') + '</td>'
                + '<td>' + statusBadge(s.status) + '</td>'
                + '<td>' + (s.tick || 0) + '</td>'
                + '<td>' + Math.round(s.elapsed_minutes || 0) + ' мин</td>'
                + '<td>' + (s.roads_cleaned_pct || 0) + '%</td>'
                + '<td>' + (s.vehicles_total || 0) + '</td>'
                + '<td>' + (s.streets || []).length + '</td>'
                + '<td>' + fmtDate(s.created_at) + '</td>'
                + '<td>' + fmtDate(s.started_at) + '</td>'
                + '<td>' + fmtDate(s.finished_at) + '</td>'
                + '<td onclick="event.stopPropagation()"><a class="btn-blue" style="padding:2px 8px;font-size:0.8rem;border-radius:6px;color:var(--bg);text-decoration:none;font-weight:600" href="/static/index.html?simulation_id=' + s.id + '">На карту</a></td>'
                + '<td onclick="event.stopPropagation()"><button class="btn-red" style="padding:2px 8px;font-size:0.8rem" onclick="deleteSim(\'' + s.id + '\')">✕</button></td>'
                + '</tr>';
        }).join('');
        renderPagination(pages || 1);
    }

    function renderPagination(pages) {
        var el = document.getElementById('pagination');
        if (!el) return;
        if (pages <= 1) { el.innerHTML = ''; return; }
        var html = '<button onclick="changePage(' + (currentPage - 1) + ')"' + (currentPage <= 1 ? ' disabled' : '') + '>&laquo;</button>';
        var start = Math.max(1, currentPage - 2);
        var end = Math.min(pages, currentPage + 2);
        for (var i = start; i <= end; i++) {
            html += '<button onclick="changePage(' + i + ')"' + (i === currentPage ? ' class="active"' : '') + '>' + i + '</button>';
        }
        html += '<button onclick="changePage(' + (currentPage + 1) + ')"' + (currentPage >= pages ? ' disabled' : '') + '>&raquo;</button>';
        html += '<span class="pagination-info">Стр. ' + currentPage + ' / ' + pages + '</span>';
        el.innerHTML = html;
    }

    window.changePage = function(p) { if (p < 1 || p > totalPages) return; currentPage = p; loadSims(); };

    window.deleteSim = function (id) {
        if (!confirm('Удалить симуляцию?')) return;
        AuthModule.apiFetch('/api/simulation/' + id, { method: 'DELETE' })
            .then(function () { loadSims(); })
            .catch(function () { alert('Ошибка удаления'); });
    };

    function fmtDate(d) { if (!d) return '—'; return new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }); }
    function showLoading(s) { var e = document.getElementById('loading'); if (e) e.style.display = s ? '' : 'none'; }
    function showEmpty(s) { var e = document.getElementById('empty-state'); if (e) e.style.display = s ? '' : 'none'; }

    document.getElementById('btn-filter').addEventListener('click', function () { currentPage = 1; loadSims(); });
    document.getElementById('btn-reset').addEventListener('click', function () {
                ['f-name','f-status','f-veh-min','f-veh-max','f-date-from','f-date-to'].forEach(function(id){ var el=document.getElementById(id); if(el) el.tagName==='SELECT' ? el.selectedIndex=0 : (el.value=''); });
        currentPage = 1; loadSims();
    });

    if (AuthModule.getToken()) loadSims();
})();
