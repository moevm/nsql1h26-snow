(function () {
    var params = new URLSearchParams(window.location.search);
    var stepId = params.get('id');
    var currentStep = null;
    var leafletMap = null;
    var routeLayers = [];
    var vehicleMarkers = [];
    var ROUTE_COLORS = ['#d90429','#f77f00','#ffbe0b','#2a9d8f','#3a86ff','#8338ec'];

    function addContrastPolyline(latlngs, color, weight) {
        return L.layerGroup([
            L.polyline(latlngs, { color: '#111827', weight: weight + 5, opacity: 0.9, lineCap: 'round', lineJoin: 'round' }),
            L.polyline(latlngs, { color: '#f8fafc', weight: weight + 2, opacity: 0.92, lineCap: 'round', lineJoin: 'round' }),
            L.polyline(latlngs, { color: color, weight: weight, opacity: 1, lineCap: 'round', lineJoin: 'round' }),
        ]).addTo(leafletMap);
    }

    function drawRoadGraph() {
        AuthModule.apiFetch('/api/routes/graph')
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
                    }).addTo(leafletMap);
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
                    }).addTo(leafletMap);
                });
            })
            .catch(function () {});
    }

    function loadStep() {
        if (!AuthModule.getToken() || !stepId) return;
        AuthModule.apiFetch('/api/simulation-steps/' + stepId)
            .then(function(r) { if (!r.ok) throw new Error(); return r.json(); })
            .then(function(s) {
                currentStep = s;
                document.getElementById('step-title').textContent = 'Шаг симуляции — тик ' + s.tick;
                if (s.simulation_id) {
                    var backLink = document.getElementById('back-to-sim');
                    if (backLink) {
                        backLink.href = '/static/simulation.html?id=' + s.simulation_id;
                        backLink.textContent = '← К симуляции ' + s.simulation_id;
                    }
                }
                document.getElementById('step-attrs').innerHTML = [
                    field('ID', s.id),
                    field('Тик', s.tick),
                    field('Индекс шага', s.step_index != null ? s.step_index : '—'),
                    field('% дорог убрано', (s.roads_cleaned || 0) + '%'),
                    field('Снег (м³)', s.snow_collected),
                    field('Топливо (л)', s.fuel_spent),
                    field('Поломки', s.breakdowns),
                    field('Симуляция', s.simulation_id ? '<a href="/static/simulation.html?id=' + s.simulation_id + '">' + s.simulation_id + '</a>' : '—'),
                    field('Время создания', fmtDate(s.time_created)),
                ].join('');

                var simStateCard = document.getElementById('sim-state-card');
                var aggregatesNode = document.getElementById('sim-state-aggregates');
                var eventsTbody = document.getElementById('events-tbody');
                var eventsEmpty = document.getElementById('events-empty');
                var eventsTable = document.getElementById('events-table');
                if (s.sim_state) {
                    try {
                        var state = typeof s.sim_state === 'string' ? JSON.parse(s.sim_state) : s.sim_state;
                        var events = state.events || [];
                        aggregatesNode.innerHTML = [
                            field('В пути', state.vehicles_en_route || 0),
                            field('Убирают', state.vehicles_cleaning || 0),
                            field('На разгрузке', state.vehicles_dumping || 0),
                            field('На заправке', state.vehicles_refueling || 0),
                            field('В ремонте', state.vehicles_maintenance || 0),
                            field('Средн. топливо', (state.avg_fuel_pct || 0) + '%'),
                            field('Средн. снег', (state.avg_snow_load_pct || 0) + '%')
                        ].join('');
                        if (events.length) {
                            simStateCard.style.display = '';
                            eventsTable.style.display = '';
                            eventsEmpty.style.display = 'none';
                            var eventLabels = {
                                assigned_task: 'Назначена задача',
                                arrived_task: 'Прибыл к задаче',
                                segment_cleaned: 'Сегмент убран',
                                snow_full: 'Полный кузов',
                                dumped_snow: 'Снег выгружен',
                                low_fuel: 'Низкое топливо',
                                refueled: 'Заправлен',
                                breakdown: 'Поломка',
                                maintenance_started: 'Начат ремонт',
                                repaired: 'Отремонтирован',
                                returned_to_parking: 'Возврат на стоянку'
                            };
                            eventsTbody.innerHTML = events.map(function(e) {
                                return '<tr>'
                                    + '<td>' + e.vehicle_id + '</td>'
                                    + '<td>' + (eventLabels[e.event] || e.event) + '</td>'
                                    + '<td>' + (e.status || '—') + '</td>'
                                    + '<td>' + ((e.target_type || '—') + (e.target_id ? ' / ' + e.target_id : '')) + '</td>'
                                    + '<td>' + (e.road || '—') + '</td>'
                                    + '</tr>';
                            }).join('');
                        } else {
                            simStateCard.style.display = '';
                            eventsTable.style.display = 'none';
                            eventsEmpty.style.display = '';
                        }
                    } catch(ex) { simStateCard.style.display = 'none'; }
                } else {
                    simStateCard.style.display = 'none';
                }

                if (!leafletMap) {
                    leafletMap = L.map('step-map').setView([59.9730, 30.3180], 12);
                    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap' }).addTo(leafletMap);
                    drawRoadGraph();
                }

                if (s.simulation_id) {
                    loadRoutes(s.simulation_id);
                }

                loadVehicles();
            })
            .catch(function() { document.getElementById('step-title').textContent = 'Шаг не найден'; });
    }

    function loadRoutes(simId) {
        AuthModule.apiFetch('/api/simulation/' + simId + '/routes')
            .then(function(r) { return r.ok ? r.json() : []; })
            .then(function(routes) {
                routeLayers.forEach(function(l) { leafletMap.removeLayer(l); });
                routeLayers = [];
                var allBounds = [];
                routes.forEach(function(route, i) {
                    var pathNodes = [];
                    if (route.path_nodes_json) {
                        try { pathNodes = JSON.parse(route.path_nodes_json); } catch(e) {}
                    }
                    if (pathNodes.length >= 2) {
                        var color = ROUTE_COLORS[i % ROUTE_COLORS.length];
                        var latlngs = pathNodes.map(function(n) { return [n.lat, n.lng]; });
                        var line = addContrastPolyline(latlngs, color, 6)
                            .bindPopup(route.label || ('Маршрут ' + (i + 1)));
                        routeLayers.push(line);
                        allBounds = allBounds.concat(latlngs);
                    }
                });
                if (allBounds.length) {
                    leafletMap.fitBounds(allBounds, { padding: [30, 30] });
                }
            })
            .catch(function() {});
    }

    function loadVehicles() {
        AuthModule.apiFetch('/api/simulation-steps/' + stepId + '/vehicles')
            .then(function(r) { return r.ok ? r.json() : []; })
            .then(function(vehicles) {
                vehicleMarkers.forEach(function(m) { leafletMap.removeLayer(m); });
                vehicleMarkers = [];
                var tbody = document.getElementById('vehicles-tbody');
                var empty = document.getElementById('vehicles-empty');
                var table = document.getElementById('vehicles-table');
                if (!vehicles || !vehicles.length) {
                    table.style.display = 'none';
                    empty.style.display = '';
                    return;
                }
                table.style.display = ''; empty.style.display = 'none';
                tbody.innerHTML = vehicles.map(function(v) {
                    var statusColors = { broken: '#f38ba8', cleaning: '#a6e3a1', idle: '#89b4fa', refueling: '#f9e2af', dumping: '#fab387', maintenance: '#cba6f7', en_route: '#94e2d5', off_route: '#f59e0b' };
                    var color = statusColors[v.status] || '#cba6f7';
                    if (v.lat && v.lng && leafletMap) {
                        var marker = L.circleMarker([v.lat, v.lng], {
                            radius: 5, color: color, fillColor: color, fillOpacity: 0.9
                        }).addTo(leafletMap).bindPopup(
                            '<b>' + v.id + '</b><br>'
                            + (v.vehicle_type || '') + ' — ' + (v.status || '') + '<br>'
                            + 'Топливо: ' + (v.fuel_level != null ? v.fuel_level.toFixed(1) : '—') + ' л<br>'
                            + 'Снег: ' + (v.snow_loaded_m3 != null ? v.snow_loaded_m3.toFixed(2) : '—') + ' м³<br>'
                            + 'Цель: ' + ((v.target_type || '—') + (v.target_id ? ' / ' + v.target_id : ''))
                        );
                        vehicleMarkers.push(marker);
                    }
                    return '<tr onclick="window.location=\'/static/vehicle-state.html?id=' + v.id + '\'" style="cursor:pointer">'
                        + '<td>' + (v.vehicle_index != null ? v.vehicle_index : '—') + '</td>'
                        + '<td><a href="/static/vehicle-state.html?id=' + v.id + '">' + v.id + '</a></td>'
                        + '<td>' + (v.vehicle_type || '—') + '</td>'
                        + '<td>' + (v.status || '—') + '</td>'
                        + '<td>' + (v.fuel_level != null ? v.fuel_level.toFixed(1) : '—') + '</td>'
                        + '<td>' + (v.snow_loaded_m3 != null ? v.snow_loaded_m3.toFixed(2) : '—') + ' / ' + (v.snow_capacity_m3 != null ? v.snow_capacity_m3.toFixed(1) : '—') + '</td>'
                        + '<td>' + (v.speed_kmh != null ? v.speed_kmh.toFixed(1) : '—') + ' км/ч</td>'
                        + '<td>' + ((v.target_type || '—') + (v.target_id ? ' / ' + v.target_id : '')) + '</td>'
                        + '<td>' + (v.progress_m != null ? v.progress_m.toFixed(1) : '—') + ' м</td>'
                        + '<td>' + (v.current_road || '—') + '</td>'
                        + '</tr>';
                }).join('');
            })
            .catch(function() {});
    }

    document.getElementById('btn-edit').addEventListener('click', function() {
        if (!currentStep) return;
        document.getElementById('e-roads').value = currentStep.roads_cleaned || 0;
        document.getElementById('e-snow').value = currentStep.snow_collected || 0;
        document.getElementById('e-fuel').value = currentStep.fuel_spent || 0;
        document.getElementById('e-breaks').value = currentStep.breakdowns || 0;
        document.getElementById('view-card').style.display = 'none';
        document.getElementById('edit-card').style.display = '';
    });
    document.getElementById('btn-cancel').addEventListener('click', function() {
        document.getElementById('view-card').style.display = '';
        document.getElementById('edit-card').style.display = 'none';
    });
    document.getElementById('btn-save').addEventListener('click', function() {
        var updates = {
            roads_cleaned: parseFloat(document.getElementById('e-roads').value),
            snow_collected: parseFloat(document.getElementById('e-snow').value),
            fuel_spent: parseFloat(document.getElementById('e-fuel').value),
            breakdowns: parseInt(document.getElementById('e-breaks').value),
        };
        AuthModule.apiFetch('/api/simulation-steps/' + stepId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates)
        })
            .then(function(r) {
                if (!r.ok) throw new Error();
                document.getElementById('view-card').style.display = '';
                document.getElementById('edit-card').style.display = 'none';
                loadStep();
            })
            .catch(function() { alert('Ошибка сохранения'); });
    });
    document.getElementById('btn-delete').addEventListener('click', function() {
        if (!confirm('Удалить шаг симуляции?')) return;
        AuthModule.apiFetch('/api/simulation-steps/' + stepId, { method: 'DELETE' })
            .then(function() { history.back(); })
            .catch(function() { alert('Ошибка удаления'); });
    });

    function field(label, value) {
        return '<div class="field"><span>' + label + '</span><span class="value">' + (value != null ? value : '—') + '</span></div>';
    }
    function fmtDate(d) {
        if (!d) return '—';
        return new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' });
    }

    if (AuthModule.getToken()) loadStep();
})();
