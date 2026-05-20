(function () {
    var params = new URLSearchParams(window.location.search);
    var routeId = params.get('id');
    var currentData = null;
    var leafletMap = null;
    var pickMode = false;
    var pickMarker = null;
    var pointsPage = 1;
    var pointsTotalPages = 1;
    var POINTS_PAGE_SIZE = 20;

    function loadRoute() {
        if (!AuthModule.getToken() || !routeId) return;
        AuthModule.apiFetch('/api/routes-crud/' + routeId)
            .then(function (res) { if (!res.ok) throw new Error('Not found'); return res.json(); })
            .then(function (r) {
                currentData = r;
                document.getElementById('route-title').textContent = r.label || ('Маршрут ' + r.id);
                document.getElementById('route-attrs').innerHTML = [
                    field('ID', r.id),
                    field('Название', r.label || '—'),
                    field('Расстояние', (r.distance_m / 1000).toFixed(2) + ' км'),
                    field('Узлов', (r.path_nodes || []).length),
                    field('Начало', r.start.lat.toFixed(5) + ', ' + r.start.lng.toFixed(5)),
                    field('Конец', r.end.lat.toFixed(5) + ', ' + r.end.lng.toFixed(5)),
                    field('Создан', fmtDate(r.created_at)),
                    field('Начало работ', fmtDate(r.started_at)),
                    field('Конец работ', fmtDate(r.finished_at)),
                ].join('');
                document.getElementById('route-streets').innerHTML = (r.streets || []).map(function (s) {
                    return '<li>' + esc(s) + '</li>';
                }).join('') || '<li style="color:var(--text-dim)">Нет данных</li>';

                if (!leafletMap) {
                    leafletMap = L.map('route-map').setView([r.start.lat, r.start.lng], 13);
                    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap' }).addTo(leafletMap);

                    leafletMap.on('click', function (e) {
                        if (!pickMode) return;
                        var lat = e.latlng.lat, lng = e.latlng.lng;
                        document.getElementById('wp-lat').value = lat.toFixed(6);
                        document.getElementById('wp-lng').value = lng.toFixed(6);
                        if (pickMarker) leafletMap.removeLayer(pickMarker);
                        pickMarker = L.circleMarker([lat, lng], {
                            radius: 8, color: '#f9e2af', fillColor: '#f9e2af', fillOpacity: 0.9
                        }).addTo(leafletMap).bindPopup('Выбранная точка').openPopup();
                        setPickMode(false);
                    });
                }

                var pathNodes = (r.path_nodes && r.path_nodes.length >= 2)
                    ? r.path_nodes
                    : [{ lat: r.start.lat, lng: r.start.lng }, { lat: r.end.lat, lng: r.end.lng }];
                if (leafletMap._routeLine) leafletMap.removeLayer(leafletMap._routeLine);
                var line = L.polyline(pathNodes.map(function (n) { return [n.lat, n.lng]; }), { color: '#89b4fa', weight: 4 }).addTo(leafletMap);
                leafletMap._routeLine = line;
                leafletMap.fitBounds(line.getBounds(), { padding: [50, 50] });
            })
            .then(function () {
                loadRoutePoints();
                loadWaypoints();
            })
            .catch(function () { document.getElementById('route-title').textContent = 'Маршрут не найден'; });
    }


    function loadRoutePoints(page) {
        page = page || pointsPage;
        AuthModule.apiFetch('/api/routes-crud/' + routeId + '/points?page=' + page + '&page_size=' + POINTS_PAGE_SIZE)
            .then(function (r) { return r.ok ? r.json() : { items: [], total: 0, total_pages: 1, page: 1 }; })
            .then(function (data) {
                var points = data.items || [];
                pointsPage = data.page || page;
                pointsTotalPages = data.total_pages || 1;
                var tbody = document.getElementById('route-points-tbody');
                var empty = document.getElementById('route-points-empty');
                var table = document.getElementById('route-points-table');
                if (!points.length) {
                    if (table) table.style.display = 'none';
                    if (empty) empty.style.display = '';
                    renderPointsPagination();
                    return;
                }
                if (table) table.style.display = '';
                if (empty) empty.style.display = 'none';
                tbody.innerHTML = points.map(function (p) {
                    return '<tr onclick="window.location=\'/static/point.html?id=' + p.id + '\'" style="cursor:pointer">'
                        + '<td>' + p.index + '</td>'
                        + '<td><a href="/static/point.html?id=' + p.id + '">' + p.id.substring(0, 8) + '…</a></td>'
                        + '<td>' + (p.lat != null ? p.lat.toFixed(5) : '—') + '</td>'
                        + '<td>' + (p.lng != null ? p.lng.toFixed(5) : '—') + '</td>'
                        + '<td>' + (p.object_type || '—') + '</td>'
                        + '</tr>';
                }).join('');
                renderPointsPagination();
            })
            .catch(function () {});
    }

    function renderPointsPagination() {
        var el = document.getElementById('route-points-pagination');
        if (!el) return;
        if (pointsTotalPages <= 1) { el.innerHTML = ''; return; }
        el.innerHTML =
            '<button onclick="changePointsPage(' + (pointsPage - 1) + ')"' + (pointsPage <= 1 ? ' disabled' : '') + '>&laquo;</button>'
            + '<span class="pagination-info">Стр. ' + pointsPage + ' / ' + pointsTotalPages + '</span>'
            + '<button onclick="changePointsPage(' + (pointsPage + 1) + ')"' + (pointsPage >= pointsTotalPages ? ' disabled' : '') + '>&raquo;</button>';
    }

    window.changePointsPage = function (p) {
        if (p < 1 || p > pointsTotalPages) return;
        pointsPage = p;
        loadRoutePoints(p);
    };


    function loadWaypoints() {
        AuthModule.apiFetch('/api/routes-crud/' + routeId + '/waypoints')
            .then(function (r) { return r.ok ? r.json() : []; })
            .then(function (waypoints) {
                var tbody = document.getElementById('waypoints-tbody');
                var empty = document.getElementById('waypoints-empty');
                var table = document.getElementById('waypoints-table');
                if (!waypoints || !waypoints.length) {
                    if (table) table.style.display = 'none';
                    if (empty) empty.style.display = '';
                    return;
                }
                if (table) table.style.display = '';
                if (empty) empty.style.display = 'none';
                var roleLabels = { start: 'Старт', waypoint: 'Промежуточная', end: 'Финиш' };
                tbody.innerHTML = waypoints.map(function (w) {
                    return '<tr>'
                        + '<td>' + w.index + '</td>'
                        + '<td><a href="/static/point.html?id=' + w.id + '">' + w.id.substring(0, 8) + '…</a></td>'
                        + '<td>' + (w.lat != null ? w.lat.toFixed(5) : '—') + '</td>'
                        + '<td>' + (w.lng != null ? w.lng.toFixed(5) : '—') + '</td>'
                        + '<td>' + (roleLabels[w.role] || w.role) + '</td>'
                        + '</tr>';
                }).join('');
                if (leafletMap) {
                    waypoints.forEach(function (w) {
                        if (w.lat && w.lng) {
                            var colors = { start: '#a6e3a1', waypoint: '#f9e2af', end: '#f38ba8' };
                            L.circleMarker([w.lat, w.lng], {
                                radius: 7, color: colors[w.role] || '#89b4fa',
                                fillColor: colors[w.role] || '#89b4fa', fillOpacity: 0.9
                            }).addTo(leafletMap).bindPopup((roleLabels[w.role] || w.role) + ': ' + w.id);
                        }
                    });
                }
            })
            .catch(function () {});
    }

    function setPickMode(active) {
        pickMode = active;
        var btn = document.getElementById('btn-pick-on-map');
        var hint = document.getElementById('wp-pick-hint');
        if (btn) btn.textContent = active ? 'Отмена' : 'Выбрать на карте';
        if (btn) btn.className = active ? 'btn-red' : 'btn-blue';
        if (btn) btn.style.cssText = 'padding:3px 10px;font-size:0.8rem';
        if (hint) hint.style.display = active ? '' : 'none';
        if (leafletMap) leafletMap.getContainer().style.cursor = active ? 'crosshair' : '';
    }

    document.getElementById('btn-pick-on-map').addEventListener('click', function () {
        setPickMode(!pickMode);
    });

    document.getElementById('btn-edit').addEventListener('click', function () {
        if (!currentData) return;
        document.getElementById('e-label').value = currentData.label || '';
        document.getElementById('view-card').style.display = 'none';
        document.getElementById('edit-card').style.display = '';
    });

    document.getElementById('btn-cancel-edit').addEventListener('click', function () {
        document.getElementById('view-card').style.display = '';
        document.getElementById('edit-card').style.display = 'none';
    });

    document.getElementById('btn-save').addEventListener('click', function () {
        var updates = { label: document.getElementById('e-label').value.trim() };
        if (!updates.label) { alert('Введите название'); return; }
        AuthModule.apiFetch('/api/routes-crud/' + routeId, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify(updates) })
            .then(function (res) {
                if (!res.ok) throw new Error('HTTP ' + res.status);
                document.getElementById('view-card').style.display = '';
                document.getElementById('edit-card').style.display = 'none';
                loadRoute();
            })
            .catch(function () { alert('Ошибка сохранения'); });
    });

    document.getElementById('btn-delete').addEventListener('click', function () {
        if (!confirm('Удалить маршрут?')) return;
        AuthModule.apiFetch('/api/routes-crud/' + routeId, { method: 'DELETE' })
            .then(function () { window.location.href = '/static/routes.html'; })
            .catch(function () { alert('Ошибка'); });
    });

    document.getElementById('btn-add-waypoint').addEventListener('click', function () {
        var lat = parseFloat(document.getElementById('wp-lat').value);
        var lng = parseFloat(document.getElementById('wp-lng').value);
        var role = document.getElementById('wp-role').value;
        if (isNaN(lat) || isNaN(lng)) { alert('Введите координаты или выберите точку на карте'); return; }
        AuthModule.apiFetch('/api/routes-crud/' + routeId + '/waypoint', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lat: lat, lng: lng, role: role })
        })
            .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
            .then(function () {
                document.getElementById('wp-lat').value = '';
                document.getElementById('wp-lng').value = '';
                if (pickMarker) { leafletMap.removeLayer(pickMarker); pickMarker = null; }
                loadRoute();
            })
            .catch(function () { alert('Ошибка добавления точки'); });
    });

    function field(label, value) { return '<div class="field"><span>' + esc(label) + '</span><span class="value">' + esc(String(value != null ? value : '—')) + '</span></div>'; }
    function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
    function fmtDate(d) { if (!d) return '—'; return new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }); }

    if (AuthModule.getToken()) loadRoute();
})();
