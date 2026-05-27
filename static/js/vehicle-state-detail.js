(function () {
    var params = new URLSearchParams(window.location.search);
    var vsId = params.get('id');
    var currentData = null;
    var leafletMap = null;
    var historyPage = 1;
    var historyPageSize = 20;
    var historyTotalPages = 1;

    var historyPaginator = PaginationModule.create('vs-history-pagination', {
        onPageChange: function (p) { historyPage = p; loadHistory(); },
        onPageSizeChange: function (s) { historyPageSize = s; historyPage = 1; loadHistory(); },
    });

    function load() {
        if (!AuthModule.getToken() || !vsId) return;
        AuthModule.apiFetch('/api/vehicle-states/' + vsId)
            .then(function(r) { if (!r.ok) throw new Error(); return r.json(); })
            .then(function(v) {
                currentData = v;
                document.getElementById('vs-title').textContent = 'Машина: ' + v.id;
                if (v.simulation_id) {
                    var back = document.getElementById('back-link');
                    if (back) {
                        back.href = '/static/simulation.html?id=' + v.simulation_id;
                        back.textContent = '← К симуляции ' + v.simulation_id;
                    }
                }
                document.getElementById('vs-attrs').innerHTML = [
                    field('ID', v.id),
                    field('Тип', v.vehicle_type),
                    field('Статус', v.status),
                    field('Широта', v.lat != null ? v.lat.toFixed(6) : '—'),
                    field('Долгота', v.lng != null ? v.lng.toFixed(6) : '—'),
                    field('Топливо (л)', v.fuel_level != null ? v.fuel_level.toFixed(1) : '—'),
                    field('Снег (м³)', v.snow_loaded_m3),
                    field('Текущая скорость (км/ч)', v.speed_kmh != null ? v.speed_kmh.toFixed(1) : '—'),
                    field('Скорость движения (км/ч)', v.travel_speed_kmh != null ? v.travel_speed_kmh.toFixed(1) : '—'),
                    field('Скорость уборки (км/ч)', v.cleaning_speed_kmh != null ? v.cleaning_speed_kmh.toFixed(1) : '—'),
                    field('Бак (л)', v.fuel_capacity_l != null ? v.fuel_capacity_l.toFixed(1) : '—'),
                    field('Вместимость снега (м³)', v.snow_capacity_m3 != null ? v.snow_capacity_m3.toFixed(1) : '—'),
                    field('Шанс поломки', v.breakdown_probability != null ? v.breakdown_probability : '—'),
                    field('Ремонт остался (мин)', v.repair_remaining_min != null ? v.repair_remaining_min.toFixed(1) : '—'),
                    field('Цель', (v.target_type ? v.target_type + ' / ' : '') + (v.target_id ? '<a href="/static/point.html?id=' + v.target_id + '">' + v.target_id + '</a>' : '—')),
                    field('Прогресс уборки сегмента (м)', v.progress_m != null ? v.progress_m.toFixed(1) : '—'),
                    field('Ребро', v.current_edge || '—'),
                    field('Дистанция (км)', v.distance_travelled_km != null ? v.distance_travelled_km.toFixed(2) : '—'),
                    field('Текущая убираемая дорога', (function() {
                        if (!v.current_road) return '—';
                        var parts = v.current_road.split('->');
                        if (parts.length === 2 && parts[0] && parts[1]) {
                            return '<a href="/static/point.html?id=' + parts[0] + '">' + parts[0] + '</a> → <a href="/static/point.html?id=' + parts[1] + '">' + parts[1] + '</a>';
                        }
                        return v.current_road;
                    })()),
                    field('Последний тик', v.tick != null ? v.tick : '—'),
                    field('Последний шаг', v.step_id ? '<a href="/static/simulation-step.html?id=' + v.step_id + '">' + v.step_id + '</a>' : '—'),
                    field('Симуляция', v.simulation_id ? '<a href="/static/simulation.html?id=' + v.simulation_id + '">' + v.simulation_id + '</a>' : '—'),
                    field('Создан', fmtDate(v.created_at)),
                    field('Изменён', fmtDate(v.updated_at)),
                ].join('');

                if (v.lat && v.lng) {
                    if (!leafletMap) {
                        leafletMap = L.map('vs-map').setView([v.lat, v.lng], 15);
                        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap' }).addTo(leafletMap);
                    }
                    var color = v.status === 'broken' ? '#f38ba8'
                        : v.status === 'cleaning' ? '#a6e3a1'
                            : v.status === 'off_route' ? '#f59e0b'
                                : '#89b4fa';
                    L.circleMarker([v.lat, v.lng], { radius: 10, color: color, fillColor: color, fillOpacity: 0.9 })
                        .addTo(leafletMap)
                        .bindPopup(v.id + ' — ' + (v.status || ''))
                        .openPopup();
                }
                loadHistory();
            })
            .catch(function() { document.getElementById('vs-title').textContent = 'Не найдено'; });
    }

    function loadHistory() {
        var q = '?page=' + historyPage + '&page_size=' + historyPageSize;
        AuthModule.apiFetch('/api/vehicle-states/' + vsId + '/history' + q)
            .then(function (r) { return r.ok ? r.json() : { items: [], total: 0, total_pages: 1 }; })
            .then(function (data) {
                historyTotalPages = data.total_pages || 1;
                var items = data.items || [];
                var table = document.getElementById('vs-history-table');
                var tbody = document.getElementById('vs-history-tbody');
                var empty = document.getElementById('vs-history-empty');
                historyPaginator.render(historyPage, historyTotalPages, data.total, historyPageSize);
                if (!items.length) {
                    table.style.display = 'none';
                    empty.style.display = '';
                    return;
                }
                table.style.display = '';
                empty.style.display = 'none';
                tbody.innerHTML = items.map(function (item) {
                    var targetCell = (item.target_type ? item.target_type + ' / ' : '') + (item.target_id ? '<a href="/static/point.html?id=' + item.target_id + '">' + item.target_id + '</a>' : '—');
                    var roadCell = (function() {
                        if (!item.current_road) return '—';
                        var parts = item.current_road.split('->');
                        if (parts.length === 2 && parts[0] && parts[1]) {
                            return '<a href="/static/point.html?id=' + parts[0] + '">' + parts[0] + '</a> → <a href="/static/point.html?id=' + parts[1] + '">' + parts[1] + '</a>';
                        }
                        return item.current_road;
                    })();
                    return '<tr onclick="window.location=\'/static/simulation-step.html?id=' + item.step_id + '\'" style="cursor:pointer">'
                        + '<td>' + (item.tick != null ? item.tick : '—') + '</td>'
                        + '<td>' + (item.status || '—') + '</td>'
                        + '<td>' + (item.lat != null ? item.lat.toFixed(5) : '—') + '</td>'
                        + '<td>' + (item.lng != null ? item.lng.toFixed(5) : '—') + '</td>'
                        + '<td>' + (item.fuel_level != null ? item.fuel_level.toFixed(1) : '—') + '</td>'
                        + '<td>' + (item.snow_loaded_m3 != null ? item.snow_loaded_m3.toFixed(2) : '—') + '</td>'
                        + '<td>' + (item.speed_kmh != null ? item.speed_kmh.toFixed(1) : '—') + '</td>'
                        + '<td>' + (item.repair_remaining_min != null ? item.repair_remaining_min.toFixed(1) : '—') + '</td>'
                        + '<td>' + targetCell + '</td>'
                        + '<td>' + (item.progress_m != null ? item.progress_m.toFixed(1) : '—') + '</td>'
                        + '<td>' + (item.distance_travelled_km != null ? item.distance_travelled_km.toFixed(2) : '—') + '</td>'
                        + '<td><a href="/static/simulation-step.html?id=' + item.step_id + '">' + item.step_id + '</a></td>'
                        + '</tr>';
                }).join('');
            })
            .catch(function () {});
    }

    document.getElementById('btn-edit').addEventListener('click', function() {
        if (!currentData) return;
        document.getElementById('e-status').value = currentData.status || '';
        document.getElementById('e-fuel').value = currentData.fuel_level || 0;
        document.getElementById('e-snow').value = currentData.snow_loaded_m3 || 0;
        document.getElementById('e-road').value = currentData.current_road || '';
        document.getElementById('view-card').style.display = 'none';
        document.getElementById('edit-card').style.display = '';
    });
    document.getElementById('btn-cancel').addEventListener('click', function() {
        document.getElementById('view-card').style.display = '';
        document.getElementById('edit-card').style.display = 'none';
    });
    document.getElementById('btn-save').addEventListener('click', function() {
        var updates = {
            status: document.getElementById('e-status').value.trim(),
            fuel_level: parseFloat(document.getElementById('e-fuel').value),
            snow_loaded_m3: parseFloat(document.getElementById('e-snow').value),
            current_road: document.getElementById('e-road').value.trim() || null,
        };
        AuthModule.apiFetch('/api/vehicle-states/' + vsId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates)
        })
            .then(function(r) {
                if (!r.ok) throw new Error();
                document.getElementById('view-card').style.display = '';
                document.getElementById('edit-card').style.display = 'none';
                load();
            })
            .catch(function() { alert('Ошибка'); });
    });

    function field(label, value) {
        return '<div class="field"><span>' + label + '</span><span class="value">' + (value != null ? value : '—') + '</span></div>';
    }
    function fmtDate(d) { if (!d) return '—'; return new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }); }

    if (AuthModule.getToken()) load();
})();
