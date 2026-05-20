(function () {
    var currentPage = 1;
    var pageSize = 20;
    var totalPages = 1;

    function getFilters() {
        return {
            label: document.getElementById('f-label').value.trim() || null,
            distance_min: document.getElementById('f-dist-min').value || null,
            distance_max: document.getElementById('f-dist-max').value || null,
            streets_min: document.getElementById('f-streets-min').value || null,
            streets_max: document.getElementById('f-streets-max').value || null,
            date_from: document.getElementById('f-date-from').value ? document.getElementById('f-date-from').value + 'T00:00:00' : null,
            date_to: document.getElementById('f-date-to').value ? document.getElementById('f-date-to').value + 'T23:59:59' : null,
        };
    }

    function buildQuery(f) {
        var p = ['page=' + currentPage, 'page_size=' + pageSize];
        if (f.label) p.push('label=' + encodeURIComponent(f.label));
        if (f.distance_min) p.push('distance_min=' + f.distance_min);
        if (f.distance_max) p.push('distance_max=' + f.distance_max);
        if (f.streets_min) p.push('streets_min=' + f.streets_min);
        if (f.streets_max) p.push('streets_max=' + f.streets_max);
        if (f.date_from) p.push('date_from=' + encodeURIComponent(f.date_from));
        if (f.date_to) p.push('date_to=' + encodeURIComponent(f.date_to));
        return '?' + p.join('&');
    }

    function loadRoutes() {
        if (!AuthModule.getToken()) return;
        showLoading(true); hideError();
        AuthModule.apiFetch('/api/routes-crud/' + buildQuery(getFilters()))
            .then(function (res) {
                if (!res.ok) return res.text().then(function (t) { throw new Error(t || 'HTTP ' + res.status); });
                return res.json();
            })
            .then(function (data) {
                totalPages = data.total_pages || 1;
                render(data.items, data.total, data.page, data.total_pages);
                showLoading(false);
            })
            .catch(function (err) { showLoading(false); showError(err && err.message ? err.message : 'Ошибка'); });
    }

    function render(routes, total, page, pages) {
        var tbody = document.getElementById('routes-tbody');
        var table = document.getElementById('routes-table');
        var empty = document.getElementById('empty-state');
        var count = document.getElementById('result-count');
        if (count) count.textContent = 'Найдено: ' + (total || 0);
        if (!routes || !routes.length) {
            table.style.display = 'none';
            empty.style.display = '';
            renderPagination(1);
            return;
        }
        table.style.display = ''; empty.style.display = 'none';
        tbody.innerHTML = routes.map(function (r) {
            return '<tr onclick="window.location=\'/static/route.html?id=' + r.id + '\'" style="cursor:pointer">'
                + '<td style="font-size:0.75rem;color:var(--text-dim)">' + r.id + '</td>'
                + '<td><a href="/static/route.html?id=' + r.id + '">' + esc(r.label || '—') + '</a></td>'
                + '<td>' + (r.distance_m / 1000).toFixed(2) + ' км</td>'
                + '<td>' + (r.streets || []).length + '</td>'
                + '<td>' + fmtDate(r.created_at) + '</td>'
                + '<td>' + fmtDate(r.started_at) + '</td>'
                + '<td>' + fmtDate(r.finished_at) + '</td>'
                + '<td onclick="event.stopPropagation()"><button class="btn-red" style="padding:2px 8px;font-size:0.8rem" onclick="deleteRoute(\'' + r.id + '\')">✕</button></td>'
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

    window.changePage = function(p) { if (p < 1 || p > totalPages) return; currentPage = p; loadRoutes(); };

    window.deleteRoute = function (id) {
        if (!confirm('Удалить маршрут?')) return;
        AuthModule.apiFetch('/api/routes-crud/' + id, { method: 'DELETE' })
            .then(function () { loadRoutes(); })
            .catch(function () { alert('Ошибка удаления'); });
    };

    function esc(s) { return s ? String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : ''; }
    function fmtDate(d) { if (!d) return '—'; return new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }); }
    function showLoading(s) { var e = document.getElementById('loading'); if (e) e.style.display = s ? '' : 'none'; }
    function showError(m) { var e = document.getElementById('error-state'); var t = document.getElementById('routes-table'); var em = document.getElementById('empty-state'); if (t) t.style.display='none'; if (em) em.style.display='none'; if (e) { e.textContent=m; e.style.display=''; } }
    function hideError() { var e = document.getElementById('error-state'); if (e) e.style.display = 'none'; }

    document.getElementById('btn-filter').addEventListener('click', function () { currentPage = 1; loadRoutes(); });
    document.getElementById('btn-reset').addEventListener('click', function () {
        ['f-label','f-dist-min','f-dist-max','f-streets-min','f-streets-max','f-date-from','f-date-to'].forEach(function(id){ var el=document.getElementById(id); if(el) el.value=''; });
        currentPage = 1; loadRoutes();
    });

    if (AuthModule.getToken()) loadRoutes();
    window.addEventListener('pageshow', function (e) { if (e.persisted && AuthModule.getToken()) loadRoutes(); });
})();
