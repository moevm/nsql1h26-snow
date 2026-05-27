(function () {
    var currentPage = 1;
    var pageSize = 20;
    var totalPages = 1;
    var TYPE_LABELS = { parking: 'Парковка', snow_polygon: 'Снегоплавильня', service_station: 'Сервисная станция' };

    function getFilters() {
        return {
            point_id_filter: document.getElementById('f-point-id').value.trim() || null,
            name: document.getElementById('f-name').value.trim() || null,
            type: document.getElementById('f-type').value || null,
            description: document.getElementById('f-desc').value.trim() || null,
            lat_min: document.getElementById('f-lat-min').value || null,
            lat_max: document.getElementById('f-lat-max').value || null,
            lng_min: document.getElementById('f-lng-min').value || null,
            lng_max: document.getElementById('f-lng-max').value || null,
            capacity_min: document.getElementById('f-cap-min').value || null,
            capacity_max: document.getElementById('f-cap-max').value || null,
            only_infrastructure: document.getElementById('f-infra').checked ? 'true' : 'false',
            created_at_from: document.getElementById('f-created-from').value || null,
            created_at_to: document.getElementById('f-created-to').value || null,
            updated_at_from: document.getElementById('f-upd-from').value || null,
            updated_at_to: document.getElementById('f-upd-to').value || null,
            page: currentPage,
            page_size: pageSize,
        };
    }

    function buildQuery(f) {
        var p = [];
        Object.keys(f).forEach(function(k) {
            if (f[k] !== null && f[k] !== undefined) p.push(k + '=' + encodeURIComponent(f[k]));
        });
        return p.length ? '?' + p.join('&') : '';
    }

    function loadPoints() {
        if (!AuthModule.getToken()) return;
        showLoading(true);
        hideError();
        AuthModule.apiFetch('/api/objects/' + buildQuery(getFilters()))
            .then(function (res) {
                if (!res.ok) return res.text().then(function (t) { throw new Error(t || 'HTTP ' + res.status); });
                return res.json();
            })
            .then(function (data) {
                totalPages = data.total_pages || 1;
                render(data.items, data.total, data.page, data.total_pages);
                showLoading(false);
            })
            .catch(function (err) {
                showLoading(false);
                showError(err && err.message ? err.message : 'Ошибка загрузки');
            });
    }

    function render(points, total, page, pages) {
        var tbody = document.getElementById('points-tbody');
        var table = document.getElementById('points-table');
        var empty = document.getElementById('empty-state');
        var count = document.getElementById('result-count');
        if (count) count.textContent = 'Найдено: ' + (total || 0);
        if (!points || !points.length) {
            table.style.display = 'none';
            empty.style.display = '';
            renderPagination(1);
            return;
        }
        table.style.display = '';
        empty.style.display = 'none';
        tbody.innerHTML = points.map(function (p) {
            var displayName = p.name || '—';
            return '<tr onclick="window.location=\'/static/point.html?id=' + p.id + '\'" style="cursor:pointer">'
                + '<td style="font-size:0.75rem;color:var(--text-dim)">' + p.id.substring(0, 8) + '…</td>'
                + '<td><a href="/static/point.html?id=' + p.id + '">' + esc(displayName) + '</a></td>'
                + '<td>' + (p.is_infrastructure) + '</td>'
                + '<td>' + (TYPE_LABELS[p.type] || p.type || '—') + '</td>'
                + '<td>' + (p.lat != null ? p.lat.toFixed(5) : '—') + '</td>'
                + '<td>' + (p.lng != null ? p.lng.toFixed(5) : '—') + '</td>'
                + '<td>' + (p.capacity != null ? p.capacity : '—') + '</td>'
                + '<td>' + esc(p.description || '—') + '</td>'
                + '<td>' + fmtDate(p.created_at) + '</td>'
                + '<td>' + fmtDate(p.updated_at) + '</td>'
                + '<td onclick="event.stopPropagation()"><button class="btn-red" style="padding:2px 8px;font-size:0.8rem" onclick="deletePoint(\'' + p.id + '\')">✕</button></td>'
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

    window.changePage = function(p) {
        if (p < 1 || p > totalPages) return;
        currentPage = p;
        loadPoints();
    };

    window.deletePoint = function (id) {
        if (!confirm('Удалить точку?')) return;
        AuthModule.apiFetch('/api/objects/' + id, { method: 'DELETE' })
            .then(function () { loadPoints(); })
            .catch(function () { alert('Ошибка удаления'); });
    };

    function esc(s) { return s ? String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : ''; }
    function fmtDate(d) { if (!d) return '—'; return new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }); }
    function showLoading(s) { var e = document.getElementById('loading'); if (e) e.style.display = s ? '' : 'none'; }
    function showError(m) { var e = document.getElementById('error-state'); var t = document.getElementById('points-table'); var em = document.getElementById('empty-state'); if (t) t.style.display = 'none'; if (em) em.style.display = 'none'; if (e) { e.textContent = m; e.style.display = ''; } }
    function hideError() { var e = document.getElementById('error-state'); if (e) e.style.display = 'none'; }

    document.getElementById('btn-filter').addEventListener('click', function () { currentPage = 1; loadPoints(); });
    document.getElementById('btn-reset').addEventListener('click', function () {
        ['f-point-id','f-name','f-type','f-desc','f-lat-min','f-lat-max','f-lng-min','f-lng-max',
         'f-cap-min','f-cap-max',
         'f-created-from','f-created-to','f-upd-from','f-upd-to'].forEach(function(id) {
            var el = document.getElementById(id);
            if (el) el.tagName === 'SELECT' ? el.selectedIndex = 0 : (el.value = '');
        });
        var infra = document.getElementById('f-infra');
        if (infra) infra.checked = true;
        currentPage = 1;
        loadPoints();
    });

    document.getElementById('btn-create').addEventListener('click', function () {
        document.getElementById('modal-create').style.display = 'flex';
    });
    document.getElementById('btn-cancel-create').addEventListener('click', function () {
        document.getElementById('modal-create').style.display = 'none';
    });
    document.getElementById('btn-save-create').addEventListener('click', function () {
        var body = {
            name: document.getElementById('c-name').value.trim() || null,
            type: document.getElementById('c-type').value || null,
            lat: parseFloat(document.getElementById('c-lat').value),
            lng: parseFloat(document.getElementById('c-lng').value),
            capacity: document.getElementById('c-capacity').value ? parseInt(document.getElementById('c-capacity').value) : null,
            description: document.getElementById('c-desc').value.trim() || null,
        };
        AuthModule.apiFetch('/api/objects/', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) })
            .then(function (res) {
                if (!res.ok) return res.text().then(function(t){throw new Error(t);});
                document.getElementById('modal-create').style.display = 'none';
                document.getElementById('c-name').value = '';
                document.getElementById('c-desc').value = '';
                loadPoints();
            })
            .catch(function (err) { alert('Ошибка: ' + (err.message || err)); });
    });

    if (AuthModule.getToken()) loadPoints();

    TableStatsModule.init({
        endpoint: '/api/objects/',
        getFilters: getFilters,
        extractItems: function (r) { return r.items || []; },
        attributes: [
            { key: 'type', label: 'Тип', type: 'categorical' },
            { key: 'capacity', label: 'Вместимость', type: 'numeric' },
            { key: 'lat', label: 'Широта', type: 'numeric' },
            { key: 'lng', label: 'Долгота', type: 'numeric' },
            { key: 'created_at', label: 'Создан', type: 'date' },
            { key: 'updated_at', label: 'Изменён', type: 'date' },
            { key: 'name', label: 'Название', type: 'categorical' },
            { key: 'is_infrastructure', label: 'Инфраструктура', type: 'categorical' },
            { key: 'id', label: 'ID', type: 'categorical' },
        ],
    });
})();
