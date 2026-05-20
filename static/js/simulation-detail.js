(function () {
    var params = new URLSearchParams(window.location.search);
    var simId = params.get('id');
    var stepsPage = 1;
    var stepsTotalPages = 1;
    var GRAPH_COLORS = ['#d90429', '#f77f00', '#ffbe0b', '#2a9d8f', '#3a86ff', '#8338ec'];

    function addContrastPolyline(map, latlngs, color, weight) {
        return L.layerGroup([
            L.polyline(latlngs, { color: '#111827', weight: weight + 5, opacity: 0.9, lineCap: 'round', lineJoin: 'round' }),
            L.polyline(latlngs, { color: '#f8fafc', weight: weight + 2, opacity: 0.92, lineCap: 'round', lineJoin: 'round' }),
            L.polyline(latlngs, { color: color, weight: weight, opacity: 1, lineCap: 'round', lineJoin: 'round' }),
        ]).addTo(map);
    }

    function drawRoadGraph(map) {
        return AuthModule.apiFetch('/api/routes/graph')
            .then(function (r) { return r.ok ? r.json() : []; })
            .then(function (roads) {
                var nodesById = {};
                (roads || []).forEach(function (road) {
                    var coords = Array.isArray(road.geometry) && road.geometry.length >= 2
                        ? road.geometry.map(function (p) { return [p[0], p[1]]; })
                        : [[road.src_lat, road.src_lng], [road.dst_lat, road.dst_lng]];
                    L.polyline(coords, {
                        color: road.cleaned ? '#94a3b8' : '#0f766e',
                        weight: 2,
                        opacity: road.cleaned ? 0.28 : 0.45,
                        lineCap: 'round',
                        interactive: false,
                    }).addTo(map);
                    nodesById[road.src] = [road.src_lat, road.src_lng];
                    nodesById[road.dst] = [road.dst_lat, road.dst_lng];
                });
                Object.keys(nodesById).forEach(function (nodeId) {
                    L.circleMarker(nodesById[nodeId], {
                        radius: 2,
                        color: '#f8fafc',
                        weight: 1,
                        fillColor: '#111827',
                        fillOpacity: 0.92,
                        opacity: 0.95,
                        interactive: false,
                    }).addTo(map);
                });
            })
            .catch(function () {});
    }

    function loadSim() {
        if (!AuthModule.getToken() || !simId) return;

        AuthModule.apiFetch('/api/simulation/' + simId + '/details')
            .then(function (res) {
                if (!res.ok) throw new Error('Not found');
                return res.json();
            })
            .then(function (d) {
                var openBtn = document.getElementById('btn-open-on-map');
                if (openBtn) {
                    openBtn.href = '/static/index.html?simulation_id=' + encodeURIComponent(d.id);
                }
                document.getElementById('sim-title').textContent = d.name || ('Симуляция: ' + d.id);

                var statusLabels = { running: 'Запущена', paused: 'Пауза', finished: 'Завершена', idle: 'Ожидание', error: 'Ошибка' };

                document.getElementById('sim-state-attrs').innerHTML = [
                    field('ID', d.id),
                    field('Название', d.name || '—'),
                    field('Статус', statusLabels[d.status] || d.status),
                    field('Тик', d.tick),
                    field('Время (мин)', Math.round(d.elapsed_minutes)),
                    field('Техника активна', d.vehicles_active),
                    field('В пути', d.vehicles_en_route || 0),
                    field('Убирают', d.vehicles_cleaning || 0),
                    field('На разгрузке', d.vehicles_dumping || 0),
                    field('На заправке', d.vehicles_refueling || 0),
                    field('Сломаны', d.vehicles_broken),
                    field('В ремонте', d.vehicles_maintenance || 0),
                    field('Убрано дорог', d.roads_cleaned_pct + '%'),
                    field('Снег (м³)', d.snow_collected_m3),
                    field('Топливо (л)', d.fuel_spent_l || 0),
                    field('Средн. топливо', (d.avg_fuel_pct || 0) + '%'),
                    field('Средн. снег', (d.avg_snow_load_pct || 0) + '%'),
                    field('Создан', fmtDate(d.created_at)),
                    field('Начало', fmtDate(d.started_at)),
                    field('Конец', fmtDate(d.finished_at)),
                ].join('');

                var p = d.params || {};
                document.getElementById('sim-params-attrs').innerHTML = [
                    field('Ускорение', (p.speed_multiplier || 1) + 'x'),
                    field('Тик модели', (p.tick_duration_min || 5) + ' мин'),
                    field('Снегопад', (p.snowfall_cm || 0) + ' см'),
                    field('Порог заправки', (p.refuel_threshold_pct || 15) + '%'),
                    field('Порог разгрузки', (p.dump_threshold_pct || 90) + '%'),
                    field('Снегоплавильня', (p.snow_melt_rate_m3_per_tick || 10) + ' м³/тик'),
                    field('Дорог всего', d.roads_total || '—'),
                ].join('');

                var streetsList = document.getElementById('sim-streets');
                streetsList.innerHTML = (d.streets || []).map(function (s) {
                    return '<li>' + s + '</li>';
                }).join('') || '<li style="color:var(--text-dim)">Нет данных об улицах</li>';

                AuthModule.apiFetch('/api/statistics/' + simId)
                    .then(function (r) { return r.ok ? r.json() : null; })
                    .then(function (st) {
                        if (!st) {
                            document.getElementById('sim-stats-attrs').innerHTML = '<div class="field"><span>Нет данных</span><span></span></div>';
                            return;
                        }
                        document.getElementById('sim-stats-attrs').innerHTML = [
                            field('Общее время', Math.round(st.total_time_min) + ' мин'),
                            field('Топливо', st.fuel_spent_l + ' л'),
                            field('Поломки', st.breakdowns),
                            field('Стоимость ремонта', st.repair_cost_rub + ' руб'),
                            field('Эффективность', st.efficiency),
                        ].join('');
                    })
                    .catch(function () {
                        document.getElementById('sim-stats-attrs').innerHTML = '<div class="field"><span>Статистика недоступна</span><span></span></div>';
                    });

                if (d.route_coords && d.route_coords.length > 0) {
                    var firstPoint = d.route_coords[0][0];
                    var map = L.map('sim-map').setView([firstPoint.lat, firstPoint.lng], 12);
                    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                        attribution: '&copy; OpenStreetMap'
                    }).addTo(map);
                    drawRoadGraph(map);

                    var allLatLngs = [];
                    d.route_coords.forEach(function (coords, i) {
                        var latlngs = coords.map(function (c) { return [c.lat, c.lng]; });
                        allLatLngs = allLatLngs.concat(latlngs);
                        addContrastPolyline(map, latlngs, GRAPH_COLORS[i % GRAPH_COLORS.length], 6);
                    });
                    if (allLatLngs.length) map.fitBounds(allLatLngs, { padding: [30, 30] });
                } else {
                    document.getElementById('sim-map').innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim)">Данные маршрутов недоступны для исторических симуляций</div>';
                }

                loadSimRoutes();
                loadSimVehicles();
                loadSteps(1);
            })
            .catch(function () {
                document.getElementById('sim-title').textContent = 'Симуляция не найдена';
            });
    }

    function loadSimRoutes() {
        AuthModule.apiFetch('/api/simulation/' + simId + '/routes')
            .then(function (r) { return r.ok ? r.json() : []; })
            .then(function (routes) {
                var tbody = document.getElementById('sim-routes-tbody');
                var empty = document.getElementById('sim-routes-empty');
                var table = document.getElementById('sim-routes-table');
                if (!routes || !routes.length) {
                    if (table) table.style.display = 'none';
                    if (empty) empty.style.display = '';
                    return;
                }
                if (table) table.style.display = '';
                if (empty) empty.style.display = 'none';
                tbody.innerHTML = routes.map(function (r) {
                    return '<tr onclick="window.location=\'/static/route.html?id=' + r.id + '\'" style="cursor:pointer">'
                        + '<td><a href="/static/route.html?id=' + r.id + '">' + r.id + '</a></td>'
                        + '<td>' + (r.label || '—') + '</td>'
                        + '<td>' + ((r.distance_m || 0) / 1000).toFixed(2) + ' км</td>'
                        + '<td>' + fmtDate(r.created_at) + '</td>'
                        + '</tr>';
                }).join('');
            })
            .catch(function () {});
    }

    function loadSteps(page) {
        stepsPage = page || 1;
        AuthModule.apiFetch('/api/simulation/' + simId + '/steps?page=' + stepsPage + '&page_size=20')
            .then(function (r) { return r.ok ? r.json() : { items: [], total_pages: 1 }; })
            .then(function (d) {
                stepsTotalPages = d.total_pages || 1;
                var tbody = document.getElementById('sim-steps-tbody');
                var empty = document.getElementById('sim-steps-empty');
                var table = document.getElementById('sim-steps-table');
                if (!(d.items || []).length) {
                    if (table) table.style.display = 'none';
                    if (empty) empty.style.display = '';
                    return;
                }
                if (table) table.style.display = '';
                if (empty) empty.style.display = 'none';
                tbody.innerHTML = (d.items || []).map(function (s) {
                    return '<tr onclick="window.location=\'/static/simulation-step.html?id=' + s.id + '\'" style="cursor:pointer">'
                        + '<td><a href="/static/simulation-step.html?id=' + s.id + '">' + s.tick + '</a></td>'
                        + '<td>' + (s.roads_cleaned || 0) + '%</td>'
                        + '<td>' + (s.snow_collected || 0) + '</td>'
                        + '<td>' + (s.fuel_spent || 0) + '</td>'
                        + '<td>' + (s.breakdowns || 0) + '</td>'
                        + '<td>' + fmtDate(s.time_created) + '</td>'
                        + '</tr>';
                }).join('');
                var pag = document.getElementById('steps-pagination');
                if (pag && stepsTotalPages > 1) {
                    pag.innerHTML = '<button onclick="window._loadSteps(' + (stepsPage - 1) + ')"' + (stepsPage <= 1 ? ' disabled' : '') + '>&laquo;</button>'
                        + '<span class="pagination-info"> Стр. ' + stepsPage + ' / ' + stepsTotalPages + ' </span>'
                        + '<button onclick="window._loadSteps(' + (stepsPage + 1) + ')"' + (stepsPage >= stepsTotalPages ? ' disabled' : '') + '>&raquo;</button>';
                } else if (pag) {
                    pag.innerHTML = '';
                }
            })
            .catch(function () {});
    }

    function loadSimVehicles() {
        AuthModule.apiFetch('/api/vehicle-states/?sim_id=' + encodeURIComponent(simId) + '&page=1&page_size=500')
            .then(function (r) { return r.ok ? r.json() : { items: [] }; })
            .then(function (d) {
                var items = d.items || [];
                var tbody = document.getElementById('sim-vehicles-tbody');
                var empty = document.getElementById('sim-vehicles-empty');
                var table = document.getElementById('sim-vehicles-table');
                if (!items.length) {
                    table.style.display = 'none';
                    empty.style.display = '';
                    return;
                }
                table.style.display = '';
                empty.style.display = 'none';
                tbody.innerHTML = items.map(function (v) {
                    return '<tr onclick="window.location=\'/static/vehicle-state.html?id=' + v.id + '\'" style="cursor:pointer">'
                        + '<td><a href="/static/vehicle-state.html?id=' + v.id + '">' + v.id + '</a></td>'
                        + '<td>' + (v.vehicle_type || '—') + '</td>'
                        + '<td>' + (v.status || '—') + '</td>'
                        + '<td>' + (v.fuel_level != null ? v.fuel_level.toFixed(1) : '—') + '</td>'
                        + '<td>' + (v.snow_loaded_m3 != null ? v.snow_loaded_m3.toFixed(2) : '—') + '</td>'
                        + '<td>' + (v.tick != null ? v.tick : '—') + '</td>'
                        + '</tr>';
                }).join('');
            })
            .catch(function () {});
    }

    window._loadSteps = loadSteps;

    var deleteBtn = document.getElementById('btn-delete');
    if (deleteBtn) {
        deleteBtn.addEventListener('click', function () {
            if (!confirm('Удалить симуляцию?')) return;
            AuthModule.apiFetch('/api/simulation/' + simId, { method: 'DELETE' })
                .then(function () { window.location.href = '/static/simulations.html'; })
                .catch(function () { alert('Ошибка удаления'); });
        });
    }

    var editNameBtn = document.getElementById('btn-edit-name');
    if (editNameBtn) {
        editNameBtn.addEventListener('click', function () {
            var nameInput = document.getElementById('e-sim-name');
            var titleEl = document.getElementById('sim-title');
            if (nameInput) nameInput.value = titleEl ? titleEl.textContent : '';
            var card = document.getElementById('rename-card');
            if (card) card.style.display = card.style.display === 'none' ? '' : 'none';
        });
    }
    var cancelRenameBtn = document.getElementById('btn-cancel-rename');
    if (cancelRenameBtn) {
        cancelRenameBtn.addEventListener('click', function () {
            var card = document.getElementById('rename-card');
            if (card) card.style.display = 'none';
        });
    }
    var saveNameBtn = document.getElementById('btn-save-name');
    if (saveNameBtn) {
        saveNameBtn.addEventListener('click', function () {
            var newName = document.getElementById('e-sim-name').value.trim();
            AuthModule.apiFetch('/api/simulation/' + simId, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newName })
            })
                .then(function (r) {
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    var titleEl = document.getElementById('sim-title');
                    if (titleEl) titleEl.textContent = newName || ('Симуляция: ' + simId);
                    var card = document.getElementById('rename-card');
                    if (card) card.style.display = 'none';
                })
                .catch(function () { alert('Ошибка сохранения'); });
        });
    }

    function field(label, value) {
        return '<div class="field"><span>' + label + '</span><span class="value">' + (value != null ? value : '—') + '</span></div>';
    }

    function fmtDate(d) {
        if (!d) return '—';
        return new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
    }

    if (AuthModule.getToken()) loadSim();
})();
