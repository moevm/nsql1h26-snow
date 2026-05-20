var App = (function () {
    var cleaningTasks = [];
    var routeStartPoint = null;
    var routeWaypoints = [];
    var simPaused = false;
    var currentSimulationStatus = null;
    var ROUTES_REFRESH_KEY = 'snow_routes_refresh';
    var initialSimulationId = new URLSearchParams(window.location.search).get('simulation_id');
    var vehicleConfigs = [];

    function defaultVehicleConfig(index) {
        return {
            type: 'tractor',
            label: 'Трактор ' + (index + 1),
            initial_status: 'idle',
            count: 1,
            speed_kmh: 10,
            capacity_m3: 10,
            fuel_capacity_l: 100,
            fuel_consumption_l_per_km: 0.4,
            breakdown_probability: 0.02,
            repair_time_min: 60,
        };
    }

    function normalizeVehicleConfigs() {
        if (!vehicleConfigs.length) {
            vehicleConfigs = [defaultVehicleConfig(0)];
        }
        vehicleConfigs = vehicleConfigs.map(function (cfg, index) {
            return {
                type: 'tractor',
                label: 'Трактор ' + (index + 1),
                initial_status: cfg.initial_status || 'idle',
                count: 1,
                speed_kmh: cfg.speed_kmh != null ? cfg.speed_kmh : 10,
                capacity_m3: cfg.capacity_m3 != null ? cfg.capacity_m3 : 10,
                fuel_capacity_l: cfg.fuel_capacity_l != null ? cfg.fuel_capacity_l : 100,
                fuel_consumption_l_per_km: cfg.fuel_consumption_l_per_km != null ? cfg.fuel_consumption_l_per_km : 0.4,
                breakdown_probability: cfg.breakdown_probability != null ? cfg.breakdown_probability : 0.02,
                repair_time_min: cfg.repair_time_min != null ? cfg.repair_time_min : 60,
            };
        });
    }

    function toast(message, type) {
        type = type || 'info';
        var container = document.getElementById('toast-container');
        if (!container) return;
        var el = document.createElement('div');
        el.className = 'toast toast-' + type;
        el.textContent = message;
        container.appendChild(el);
        setTimeout(function () { el.classList.add('toast-visible'); }, 10);
        setTimeout(function () {
            el.classList.remove('toast-visible');
            setTimeout(function () { container.removeChild(el); }, 300);
        }, 3500);
    }

    function login() {
        var u = document.getElementById('username').value;
        var p = document.getElementById('password').value;
        AuthModule.login(u, p)
            .then(function () {
                window.location.reload();
            })
            .catch(function () {
                toast('Ошибка авторизации', 'error');
            });
    }

    function checkAuth() {
        AuthModule.ensureSession().then(function (session) {
            if (session) loadStaticObjects();
        });
    }

    function loadStaticObjects() {
        MapModule.clearObjectMarkers();
        var list = document.getElementById('objects-list');
        list.innerHTML = '';

        AuthModule.apiFetch('/api/objects/')
            .then(function (r) {
                if (!r.ok) throw new Error('Fetch failed');
                return r.json();
            })
            .then(function (data) {
                var objects = Array.isArray(data) ? data : (data.items || []);
                objects.forEach(function (obj) {
                    MapModule.addObjectMarker(obj);
                    appendObjectListItem(obj);
                });
            })
            .catch(function (e) { console.error('loadStaticObjects', e); });
    }

    function appendObjectListItem(obj) {
        var list = document.getElementById('objects-list');
        var el = document.createElement('div');
        el.className = 'list-item';
        var label = obj.type === 'parking' ? '🅿️'
            : obj.type === 'snow_polygon' ? '🏔️' : '🔧';
        el.innerHTML = '<span>' + label + ' ' + obj.name + '</span>';
        list.appendChild(el);
    }

    function searchAddress() {
        var input = document.getElementById('address-input');
        var query = input.value.trim();
        if (!query) { toast('Введите адрес', 'error'); return; }

        var resultsDiv = document.getElementById('address-results');
        resultsDiv.style.display = 'block';
        resultsDiv.innerHTML = '<div class="hint">Поиск…</div>';

        MapModule.searchAddress(query, function (err, results) {
            if (err || !results || results.length === 0) {
                resultsDiv.innerHTML = '<div class="hint">Ничего не найдено</div>';
                return;
            }
            resultsDiv.innerHTML = '';
            results.forEach(function (r) {
                var item = document.createElement('div');
                item.className = 'address-item';
                item.textContent = r.display_name.substring(0, 80);
                item.addEventListener('click', function () {
                    var lat = parseFloat(r.lat);
                    var lng = parseFloat(r.lon);
                    MapModule.setSelectedPoint(lat, lng);
                    MapModule.panTo(lat, lng, 16);
                    resultsDiv.style.display = 'none';
                });
                resultsDiv.appendChild(item);
            });
        });
    }

    function setRouteStart() {
        var pt = MapModule.getSelectedPoint();
        if (!pt) {
            toast('Сначала кликните на карту или найдите адрес', 'error');
            return;
        }
        routeStartPoint = { lat: pt.lat, lng: pt.lng };
        routeWaypoints = [];
        redrawWaypointsList();
        document.getElementById('route-start-display').textContent =
            pt.lat.toFixed(5) + ', ' + pt.lng.toFixed(5);
        setStatus('Начало задано! Добавьте промежуточные точки или нажмите «Конец»', '#a6e3a1');
    }

    function addRouteWaypoint() {
        if (!routeStartPoint) { toast('Сначала задайте начальную точку', 'error'); return; }
        var pt = MapModule.getSelectedPoint();
        if (!pt) { toast('Выберите точку на карте', 'error'); return; }
        routeWaypoints.push({ lat: pt.lat, lng: pt.lng });
        redrawWaypointsList();
        MapModule.addWaypointMarker(pt.lat, pt.lng, routeWaypoints.length);
        setStatus('Добавлена точка ' + routeWaypoints.length + '. Выберите следующую или нажмите «Конец»', '#f9e2af');
    }

    function removeRouteWaypoint(index) {
        routeWaypoints.splice(index, 1);
        MapModule.clearWaypointMarkers();
        routeWaypoints.forEach(function (wp, i) { MapModule.addWaypointMarker(wp.lat, wp.lng, i + 1); });
        redrawWaypointsList();
    }

    function redrawWaypointsList() {
        var list = document.getElementById('waypoints-list');
        if (!list) return;
        list.innerHTML = routeWaypoints.map(function (wp, i) {
            return '<div class="list-item" style="font-size:0.82rem">'
                + '<span>📍 ' + (i + 1) + ': ' + wp.lat.toFixed(4) + ', ' + wp.lng.toFixed(4) + '</span>'
                + '<button class="del-btn" onclick="App.removeRouteWaypoint(' + i + ')">✕</button>'
                + '</div>';
        }).join('');
    }

    function setRouteEnd() {
        if (!AuthModule.getToken()) { toast('Сначала войдите', 'error'); return; }
        if (!routeStartPoint) { toast('Сначала задайте начальную точку', 'error'); return; }

        var pt = MapModule.getSelectedPoint();
        if (!pt) { toast('Выберите конечную точку на карте', 'error'); return; }

        var endPoint = { lat: pt.lat, lng: pt.lng };
        var label = document.getElementById('route-label').value || ('Маршрут ' + (cleaningTasks.length + 1));

        setStatus('Построение маршрута через ' + (routeWaypoints.length + 2) + ' точки...', '#f9e2af');

        var body = {
            label: label,
            start: routeStartPoint,
            end: endPoint,
            waypoints: routeWaypoints.map(function (wp) { return { lat: wp.lat, lng: wp.lng, role: 'waypoint' }; }),
        };

        AuthModule.apiFetch('/api/routes-crud/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        })
            .then(function (resp) {
                if (!resp.ok) return resp.json().then(function (e) { throw new Error(e.detail || 'Route error'); });
                return resp.json();
            })
            .then(function (saved) {
                var coords = saved.path_nodes || [];
                var task = {
                    start: routeStartPoint,
                    end: endPoint,
                    label: label,
                    coords: coords,
                    distance_m: saved.distance_m || 0,
                    road_count: (saved.streets || []).length,
                    db_id: saved.id,
                };
                cleaningTasks.push(task);
                if (coords.length) MapModule.addTaskRoute(coords, cleaningTasks.length - 1);
                appendTaskListItem(task, cleaningTasks.length - 1);
                setStatus('✓ ' + label + ': ' + (saved.distance_m / 1000).toFixed(1) + ' км', '#a6e3a1');
                updateRouteTotal();
                routeStartPoint = null;
                routeWaypoints = [];
                MapModule.clearWaypointMarkers();
                redrawWaypointsList();
                document.getElementById('route-start-display').textContent = '—';
                document.getElementById('route-label').value = '';
                localStorage.setItem(ROUTES_REFRESH_KEY, JSON.stringify({ id: saved.id, ts: Date.now() }));
                toast('Маршрут «' + label + '» сохранён', 'success');
            })
            .catch(function (e) {
                console.error('[App] setRouteEnd error:', e);
                setStatus('✗ ' + e.message, '#f38ba8');
                toast(e.message, 'error');
            });
    }

    function removeTask(index) {
        cleaningTasks.splice(index, 1);
        redrawTaskList();
        MapModule.clearTaskRoutes();
        cleaningTasks.forEach(function (t, i) { MapModule.addTaskRoute(t.coords, i); });
        updateRouteTotal();
    }

    function clearAllTasks() {
        cleaningTasks = [];
        routeWaypoints = [];
        routeStartPoint = null;
        MapModule.clearTaskRoutes();
        MapModule.clearWaypointMarkers();
        redrawTaskList();
        redrawWaypointsList();
        updateRouteTotal();
        document.getElementById('route-status').textContent = '';
        document.getElementById('route-start-display').textContent = '—';
    }

    function leaveSimulation() {
        SimModule.leave();
        simPaused = false;
        currentSimulationStatus = null;
        MapModule.clearVehicles();
        MapModule.clearSimulationRoutes();
        MapModule.clearTaskRoutes();
        cleaningTasks.forEach(function (task, idx) {
            if (task.coords && task.coords.length) {
                MapModule.addTaskRoute(task.coords, idx);
            }
        });
        var statePanel = document.getElementById('sim-state-panel');
        var chartsPanel = document.getElementById('charts-panel');
        if (statePanel) statePanel.style.display = 'none';
        if (chartsPanel) chartsPanel.style.display = 'none';
        updateSimulationControls();
        updateClearTasksButtonUi();
        toast('Выход из симуляции на карте', 'info');
    }

    function updateRouteTotal() {
        var el = document.getElementById('route-total');
        el.textContent = cleaningTasks.length
            ? 'Маршрутов: ' + cleaningTasks.length + ', дорог: ' + cleaningTasks.reduce(function (s, t) { return s + t.road_count; }, 0)
            : '';
    }

    function appendTaskListItem(task, index) {
        var list = document.getElementById('tasks-list');
        var el = document.createElement('div');
        el.className = 'list-item';
        el.id = 'task-' + index;
        var span = document.createElement('span');
        span.textContent = '🛣️ ' + task.label + ' (' + (task.distance_m / 1000).toFixed(1) + ' км, ' + task.road_count + ' дорог)';
        var btn = document.createElement('button');
        btn.className = 'del-btn';
        btn.textContent = '✕';
        btn.addEventListener('click', function () { removeTask(index); });
        el.appendChild(span);
        el.appendChild(btn);
        list.appendChild(el);
    }

    function redrawTaskList() {
        var list = document.getElementById('tasks-list');
        list.innerHTML = '';
        cleaningTasks.forEach(function (t, i) { appendTaskListItem(t, i); });
    }

    function setStatus(text, color) {
        var el = document.getElementById('route-status');
        el.textContent = text;
        el.style.color = color || '';
    }

    function renderVehicleConfigRows() {
        normalizeVehicleConfigs();
        var tbody = document.getElementById('vehicle-config-tbody');
        if (!tbody) return;
        tbody.innerHTML = vehicleConfigs.map(function (cfg, index) {
            return '<tr data-index="' + index + '">'
                + '<td>' + cfg.label + '</td>'
                + '<td><select data-field="initial_status"><option value="idle"' + (cfg.initial_status === 'idle' ? ' selected' : '') + '>Ожидание</option><option value="en_route"' + (cfg.initial_status === 'en_route' ? ' selected' : '') + '>В пути</option><option value="off_route"' + (cfg.initial_status === 'off_route' ? ' selected' : '') + '>Вне маршрута</option><option value="cleaning"' + (cfg.initial_status === 'cleaning' ? ' selected' : '') + '>Уборка</option><option value="dumping"' + (cfg.initial_status === 'dumping' ? ' selected' : '') + '>Разгрузка</option><option value="refueling"' + (cfg.initial_status === 'refueling' ? ' selected' : '') + '>Заправка</option><option value="broken"' + (cfg.initial_status === 'broken' ? ' selected' : '') + '>Сломана</option><option value="maintenance"' + (cfg.initial_status === 'maintenance' ? ' selected' : '') + '>Ремонт</option></select></td>'
                + '<td><input data-field="speed_kmh" type="number" step="1" min="1" value="' + cfg.speed_kmh + '" /></td>'
                + '<td><input data-field="capacity_m3" type="number" step="0.5" min="0.1" value="' + cfg.capacity_m3 + '" /></td>'
                + '<td><input data-field="fuel_capacity_l" type="number" step="1" min="1" value="' + cfg.fuel_capacity_l + '" /></td>'
                + '<td><input data-field="fuel_consumption_l_per_km" type="number" step="0.05" min="0.01" value="' + cfg.fuel_consumption_l_per_km + '" /></td>'
                + '<td><input data-field="breakdown_probability" type="number" step="0.01" min="0" max="1" value="' + cfg.breakdown_probability + '" /></td>'
                + '<td><input data-field="repair_time_min" type="number" step="5" min="0" value="' + cfg.repair_time_min + '" /></td>'
                + '<td><button class="btn-red" type="button" onclick="App.removeVehicleConfigRow(' + index + ')">✕</button></td>'
                + '</tr>';
        }).join('');
    }

    function persistVehicleConfigRows() {
        var rows = Array.from(document.querySelectorAll('#vehicle-config-tbody tr'));
        vehicleConfigs = rows.map(function (row, index) {
            function read(field, fallback) {
                var input = row.querySelector('[data-field="' + field + '"]');
                if (!input) return fallback;
                if (input.tagName === 'SELECT') return input.value || fallback;
                return parseFloat(input.value) || fallback;
            }
            return {
                type: 'tractor',
                label: 'Трактор ' + (index + 1),
                initial_status: read('initial_status', 'idle'),
                count: 1,
                speed_kmh: read('speed_kmh', 10),
                capacity_m3: read('capacity_m3', 10),
                fuel_capacity_l: read('fuel_capacity_l', 100),
                fuel_consumption_l_per_km: read('fuel_consumption_l_per_km', 0.4),
                breakdown_probability: read('breakdown_probability', 0.02),
                repair_time_min: read('repair_time_min', 60),
            };
        });
        normalizeVehicleConfigs();
        updateVehicleConfigSummary();
    }

    function updateVehicleConfigSummary() {
        var summary = document.getElementById('vehicle-config-summary');
        if (!summary) return;
        normalizeVehicleConfigs();
        var avgSpeed = vehicleConfigs.length
            ? vehicleConfigs.reduce(function (sum, cfg) { return sum + cfg.speed_kmh; }, 0) / vehicleConfigs.length
            : 0;
        var avgCapacity = vehicleConfigs.length
            ? vehicleConfigs.reduce(function (sum, cfg) { return sum + cfg.capacity_m3; }, 0) / vehicleConfigs.length
            : 0;
        summary.textContent = vehicleConfigs.length + ' машин, средняя скорость ' + avgSpeed.toFixed(1) + ' км/ч, средняя вместимость ' + avgCapacity.toFixed(1) + ' м³';
    }

    function openVehicleConfigModal() {
        renderVehicleConfigRows();
        loadLiveVehicles();
        var modal = document.getElementById('vehicle-config-modal');
        if (modal) modal.style.display = 'block';
    }

    function loadLiveVehicles() {
        var token = AuthModule.getToken();
        var section = document.getElementById('live-vehicles-section');
        var tbody = document.getElementById('live-vehicles-tbody');
        if (!section || !tbody) return;

        if (!SimModule.simId() || !token) {
            section.style.display = 'none';
            return;
        }

        SimModule.getVehicles(token).then(function (vehicles) {
            if (!vehicles || !vehicles.length) {
                section.style.display = 'none';
                return;
            }
            section.style.display = '';
            var statusLabels = {
                idle: '⏸ Ожидание',
                en_route: '🚛 В пути',
                off_route: '🚛 Вне маршр.',
                cleaning: '🧹 Уборка',
                dumping: '🏔 Разгрузка',
                refueling: '⛽ Заправка',
                broken: '💥 Сломана',
                maintenance: '🔧 Ремонт',
            };
            var statusColors = {
                idle: '#94a3b8',
                en_route: '#f59e0b',
                off_route: '#f59e0b',
                cleaning: '#a6e3a1',
                dumping: '#06b6d4',
                refueling: '#facc15',
                broken: '#f38ba8',
                maintenance: '#7c3aed',
            };
            tbody.innerHTML = vehicles.map(function (v) {
                var fuelPct = v.fuel_capacity_l > 0 ? (v.fuel_level / v.fuel_capacity_l * 100).toFixed(0) : '—';
                var snowPct = v.snow_capacity_m3 > 0 ? (v.snow_loaded_m3 / v.snow_capacity_m3 * 100).toFixed(0) : '—';
                var color = statusColors[v.status] || '#94a3b8';
                return '<tr>'
                    + '<td style="font-size:0.78rem">' + v.id.split('-').slice(-2).join('-') + '</td>'
                    + '<td style="color:' + color + ';font-weight:600">' + (statusLabels[v.status] || v.status) + '</td>'
                    + '<td>' + fuelPct + '%</td>'
                    + '<td>' + snowPct + '%</td>'
                    + '<td style="font-size:0.78rem">' + (v.current_road || '—') + '</td>'
                    + '<td style="font-size:0.78rem">' + (v.target_type || '—') + '</td>'
                    + '</tr>';
            }).join('');
        }).catch(function () {
            section.style.display = 'none';
        });
    }

    function closeVehicleConfigModal() {
        persistVehicleConfigRows();
        var modal = document.getElementById('vehicle-config-modal');
        if (modal) modal.style.display = 'none';
    }

    function addVehicleConfigRow() {
        persistVehicleConfigRows();
        vehicleConfigs.push(defaultVehicleConfig(vehicleConfigs.length));
        renderVehicleConfigRows();
        updateVehicleConfigSummary();
    }

    function removeVehicleConfigRow(index) {
        persistVehicleConfigRows();
        vehicleConfigs.splice(index, 1);
        normalizeVehicleConfigs();
        renderVehicleConfigRows();
        updateVehicleConfigSummary();
    }

    function getVehicleConfigs() {
        normalizeVehicleConfigs();
        return vehicleConfigs.map(function (cfg) {
            return {
                type: 'tractor',
                count: 1,
                initial_status: cfg.initial_status || 'idle',
                speed_kmh: cfg.speed_kmh,
                capacity_m3: cfg.capacity_m3,
                fuel_capacity_l: cfg.fuel_capacity_l,
                fuel_consumption_l_per_km: cfg.fuel_consumption_l_per_km,
                breakdown_probability: cfg.breakdown_probability,
                repair_time_min: cfg.repair_time_min,
            };
        });
    }

    function applyVehicleStatus(vehicleId) {
        var token = AuthModule.getToken();
        var select = document.querySelector('[data-vehicle-status="' + vehicleId + '"]');
        if (!token || !select) return;
        AuthModule.apiFetch('/api/vehicle-states/' + encodeURIComponent(vehicleId), {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: select.value })
        })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function () {
                return SimModule.getVehicles(token);
            })
            .then(function (vehicles) {
                MapModule.updateVehicles(vehicles);
            })
            .catch(function () {
                toast('Не удалось обновить статус машины', 'error');
            });
    }

    function startSimulation() {
        var token = AuthModule.getToken();
        if (!token) { toast('Сначала войдите', 'error'); return; }
        if (SimModule.simId() && currentSimulationStatus === 'paused') {
            SimModule.resume(token)
                .then(function (state) {
                    simPaused = false;
                    currentSimulationStatus = state.status;
                    updateSimulationControls();
                    return SimModule.getVehicles(token);
                })
                .then(function (vehicles) {
                    MapModule.updateVehicles(vehicles);
                    toast('Симуляция возобновлена', 'success');
                })
                .catch(function (e) { toast('Ошибка возобновления: ' + e.message, 'error'); });
            return;
        }
        if (SimModule.simId() && currentSimulationStatus === 'running') {
            toast('Симуляция уже запущена', 'info');
            return;
        }
        if (cleaningTasks.length === 0) {
            toast('Добавьте хотя бы один маршрут уборки', 'error');
            return;
        }

        var vehicleConfigs = getVehicleConfigs();
        if (!vehicleConfigs.length) {
            toast('Добавьте хотя бы одну машину', 'error');
            return;
        }

        var params = {
            vehicles: vehicleConfigs,
            cleaning_tasks: cleaningTasks.map(function (t) {
                return { start: t.start, end: t.end, label: t.label, route_id: t.db_id || null };
            }),
            snowfall_cm: parseFloat(document.getElementById('sim-snow').value) || 5,
            speed_multiplier: parseFloat(document.getElementById('sim-speed').value) || 1,
            tick_duration_min: parseFloat(document.getElementById('sim-tick-minutes').value) || 5,
            refuel_threshold_pct: parseFloat(document.getElementById('sim-refuel-threshold').value) || 15,
            dump_threshold_pct: parseFloat(document.getElementById('sim-dump-threshold').value) || 90,
            snow_melt_rate_m3_per_tick: parseFloat(document.getElementById('sim-snow-melt-rate').value) || 10,
        };

        var simName = document.getElementById('sim-name') ? document.getElementById('sim-name').value.trim() : '';
        SimModule.start(token, params, simName || null)
            .then(function (state) {
                if (state.route_coords) {
                    MapModule.clearTaskRoutes();
                    MapModule.drawSimulationRoutes(state.route_coords);
                }
                showStatePanel(state);
                if (state.roads_total) {
                    document.getElementById('st-roads-total').textContent = state.roads_total;
                }
                StatsModule.reset();
                StatsModule.initCharts();
                document.getElementById('charts-panel').style.display = '';
                document.getElementById('sim-state-panel').style.display = '';
                simPaused = false;
                currentSimulationStatus = state.status;
                updateSimulationControls();
                return SimModule.getVehicles(token).then(function (vehicles) {
                    MapModule.updateVehicles(vehicles);
                    toast('Симуляция запущена', 'success');
                });
            })
            .catch(function (e) { toast('Ошибка запуска: ' + e.message, 'error'); });
    }

    function stopSimulation() {
        var token = AuthModule.getToken();
        SimModule.stop(token)
            .then(function () {
                MapModule.clearVehicles();
                MapModule.clearSimulationRoutes();
                cleaningTasks.forEach(function (task, idx) {
                    if (task.coords && task.coords.length) {
                        MapModule.addTaskRoute(task.coords, idx);
                    }
                });
                simPaused = false;
                currentSimulationStatus = 'finished';
                updateSimulationControls();
                toast('Симуляция остановлена', 'info');
            })
            .catch(function (e) { toast('Нельзя остановить: ' + e.message, 'error'); });
    }

    function pauseSimulation() {
        var token = AuthModule.getToken();
        if (!SimModule.simId()) {
            toast('Сначала запустите симуляцию', 'error');
            return;
        }
        SimModule.pause(token)
            .then(function (state) {
                simPaused = true;
                currentSimulationStatus = state.status;
                updateSimulationControls();
                toast('Симуляция на паузе', 'info');
            })
            .catch(function (e) { toast('Нельзя поставить на паузу: ' + e.message, 'error'); });
    }

    function doTick() {
        var token = AuthModule.getToken();
        if (!SimModule.simId()) { toast('Сначала запустите симуляцию', 'error'); return; }
        var tickState = null;
        SimModule.tick(token)
            .then(function (state) {
                if (state) {
                    tickState = state;
                    showStatePanel(state);
                    updateProgressBar(state.roads_cleaned_pct);
                    checkFinished(state);
                }
                return SimModule.getVehicles(token);
            })
            .then(function (vehicles) {
                MapModule.updateVehicles(vehicles);
                loadLiveVehicles();
                return SimModule.getStats(token);
            })
            .then(function (stats) {
                if (tickState) {
                    StatsModule.pushTick(tickState, stats);
                }
            })
            .catch(function (e) { toast('Тик не выполнен: ' + e.message, 'error'); });
    }

    function autoRun() {
        var token = AuthModule.getToken();
        if (!SimModule.simId()) { toast('Сначала запустите симуляцию', 'error'); return; }
        var ticks = 0;
        SimModule.startAutoRun(token, function (state) {
            showStatePanel(state);
            updateProgressBar(state.roads_cleaned_pct);
            ticks++;
            SimModule.getVehicles(token)
                .then(function (v) { MapModule.updateVehicles(v); loadLiveVehicles(); })
                .catch(function () { });
            if (ticks % 2 === 0) {
                SimModule.getStats(token)
                    .then(function (stats) { StatsModule.pushTick(state, stats); })
                    .catch(function () { StatsModule.pushTick(state, null); });
            }
            checkFinished(state);
        }, 300);
        toast('Авто-запуск активирован', 'info');
    }

    function checkFinished(state) {
        if (state.status === 'finished') {
            toast('Симуляция завершена! Убрано ' + Math.min(100, state.roads_cleaned_pct) + '% дорог', 'success');
            updateProgressBar(100);
        }
    }

    function updateProgressBar(pct) {
        var bar = document.getElementById('progress-bar-fill');
        if (bar) {
            var safePct = Math.max(0, Math.min(100, Number(pct) || 0));
            bar.style.width = safePct + '%';
            bar.textContent = safePct + '%';
        }
    }

    function showStatePanel(state) {
        document.getElementById('sim-state-panel').style.display = '';
        currentSimulationStatus = state.status;
        simPaused = state.status === 'paused';
        document.getElementById('st-status').textContent = state.status;
        document.getElementById('st-tick').textContent = state.tick;
        document.getElementById('st-time').textContent = (state.elapsed_minutes || 0).toFixed(1);
        document.getElementById('st-vehicles').textContent = state.vehicles_active;
        document.getElementById('st-en-route').textContent = state.vehicles_en_route || 0;
        document.getElementById('st-cleaning').textContent = state.vehicles_cleaning || 0;
        document.getElementById('st-dumping').textContent = state.vehicles_dumping || 0;
        document.getElementById('st-refueling').textContent = state.vehicles_refueling || 0;
        document.getElementById('st-broken').textContent = state.vehicles_broken;
        document.getElementById('st-maintenance').textContent = state.vehicles_maintenance || 0;
        document.getElementById('st-cleaned').textContent = Math.min(100, Math.max(0, Number(state.roads_cleaned_pct) || 0)) + '%';
        document.getElementById('st-snow').textContent = state.snow_collected_m3;
        document.getElementById('st-avg-fuel').textContent = (state.avg_fuel_pct || 0).toFixed(1) + '%';
        document.getElementById('st-avg-snow').textContent = (state.avg_snow_load_pct || 0).toFixed(1) + '%';
        updateProgressBar(state.roads_cleaned_pct);
        updateSimulationControls();
    }

    function updateSimulationControls() {
        var startBtn = document.getElementById('btn-sim-start');
        var pauseBtn = document.getElementById('btn-sim-pause');
        if (startBtn) {
            if (currentSimulationStatus === 'paused' && SimModule.simId()) {
                startBtn.textContent = '▶ Возобновить';
            } else {
                startBtn.textContent = '▶ Старт';
            }
        }
        if (pauseBtn) {
            pauseBtn.textContent = '⏸ Пауза';
            pauseBtn.disabled = !SimModule.simId() || currentSimulationStatus === 'paused' || currentSimulationStatus === 'finished';
        }
        updateClearTasksButtonUi();
    }

    function updateClearTasksButtonUi() {
        var btn = document.getElementById('btn-clear-tasks');
        if (!btn) return;
        if (SimModule.simId()) {
            btn.textContent = 'Выйти из симуляции';
            btn.className = 'btn-blue';
        } else {
            btn.textContent = 'Очистить все';
            btn.className = 'btn-red';
        }
    }

    function updateGraphToggleUi() {
        var btn = document.getElementById('btn-toggle-graph');
        var status = document.getElementById('graph-toggle-status');
        var visible = MapModule.isRoadGraphVisible();
        if (btn) {
            btn.textContent = visible ? '◉ Скрыть граф' : '◌ Показать граф';
            btn.className = visible ? 'btn-green' : 'btn-blue';
        }
        if (status) {
            status.textContent = visible
                ? 'Граф виден: рёбра + узлы'
                : 'Слой графа скрыт';
        }
    }

    function toggleRoadGraph() {
        var token = AuthModule.getToken();
        if (!token) {
            toast('Сначала войдите', 'error');
            return;
        }
        MapModule.toggleRoadGraph(token)
            .then(function () {
                updateGraphToggleUi();
            })
            .catch(function () {
                toast('Не удалось загрузить граф', 'error');
            });
    }

    function applySimulationParams(params) {
        params = params || {};
        vehicleConfigs = [];
        (params.vehicles || []).forEach(function (cfg) {
            if (cfg.type !== 'tractor') return;
            var copies = Math.max(1, parseInt(cfg.count, 10) || 1);
            for (var i = 0; i < copies; i += 1) {
                vehicleConfigs.push({
                    type: 'tractor',
                    label: 'Трактор ' + (vehicleConfigs.length + 1),
                    initial_status: cfg.initial_status || 'idle',
                    count: 1,
                    speed_kmh: cfg.speed_kmh,
                    capacity_m3: cfg.capacity_m3,
                    fuel_capacity_l: cfg.fuel_capacity_l,
                    fuel_consumption_l_per_km: cfg.fuel_consumption_l_per_km,
                    breakdown_probability: cfg.breakdown_probability,
                    repair_time_min: cfg.repair_time_min,
                });
            }
        });
        normalizeVehicleConfigs();
        if (params.snowfall_cm != null) document.getElementById('sim-snow').value = params.snowfall_cm;
        if (params.speed_multiplier != null) document.getElementById('sim-speed').value = params.speed_multiplier;
        if (params.tick_duration_min != null) document.getElementById('sim-tick-minutes').value = params.tick_duration_min;
        if (params.refuel_threshold_pct != null) document.getElementById('sim-refuel-threshold').value = params.refuel_threshold_pct;
        if (params.dump_threshold_pct != null) document.getElementById('sim-dump-threshold').value = params.dump_threshold_pct;
        if (params.snow_melt_rate_m3_per_tick != null) document.getElementById('sim-snow-melt-rate').value = params.snow_melt_rate_m3_per_tick;
        updateVehicleConfigSummary();
    }

    function loadExistingSimulation(simId) {
        var token = AuthModule.getToken();
        if (!token || !simId) return;

        Promise.all([
            AuthModule.apiFetch('/api/simulation/' + simId + '/details').then(function (r) {
                if (!r.ok) throw new Error('details');
                return r.json();
            }),
            AuthModule.apiFetch('/api/simulation/' + simId + '/routes').then(function (r) {
                return r.ok ? r.json() : [];
            }),
        ])
            .then(function (results) {
                var state = results[0];
                var routes = results[1] || [];

                SimModule.setSimId(simId);
                simPaused = state.status === 'paused';
                currentSimulationStatus = state.status;
                updateSimulationControls();

                if (document.getElementById('sim-name')) {
                    document.getElementById('sim-name').value = state.name || '';
                }
                applySimulationParams(state.params);

                cleaningTasks = routes.map(function (route) {
                    var pathNodes = route.path_nodes;
                    if ((!pathNodes || !pathNodes.length) && route.path_nodes_json) {
                        try { pathNodes = JSON.parse(route.path_nodes_json); } catch (e) { pathNodes = []; }
                    }
                    return {
                        start: route.start || { lat: route.start_lat, lng: route.start_lng },
                        end: route.end || { lat: route.end_lat, lng: route.end_lng },
                        label: route.label || route.id,
                        coords: pathNodes || [],
                        distance_m: route.distance_m || 0,
                        road_count: (route.streets || []).length,
                        db_id: route.id,
                    };
                });
                redrawTaskList();
                updateRouteTotal();

                MapModule.clearTaskRoutes();
                MapModule.clearSimulationRoutes();
                if (state.route_coords && state.route_coords.length) {
                    MapModule.drawSimulationRoutes(state.route_coords);
                } else {
                    cleaningTasks.forEach(function (task, idx) {
                        if (task.coords && task.coords.length) {
                            MapModule.addTaskRoute(task.coords, idx);
                        }
                    });
                }

                showStatePanel(state);
                if (state.roads_total != null) {
                    document.getElementById('st-roads-total').textContent = state.roads_total;
                }
                document.getElementById('sim-state-panel').style.display = '';
                document.getElementById('charts-panel').style.display = '';
                StatsModule.reset();
                StatsModule.initCharts();

                return Promise.all([
                    SimModule.getVehicles(token).catch(function () { return []; }),
                    SimModule.getStats(token).catch(function () { return null; }),
                ]).then(function (payload) {
                    var vehicles = payload[0] || [];
                    var stats = payload[1];
                    if (vehicles.length) {
                        MapModule.updateVehicles(vehicles);
                    }
                    StatsModule.pushTick(state, stats);
                    if (state.status === 'finished') {
                        toast('Историческая симуляция открыта на карте', 'info');
                    } else {
                        toast('Симуляция загружена на карту', 'success');
                    }
                });
            })
            .catch(function () {
                toast('Не удалось открыть симуляцию на карте', 'error');
            });
    }

    document.addEventListener('DOMContentLoaded', function () {
        MapModule.init();

        document.getElementById('btn-search-addr').addEventListener('click', searchAddress);
        document.getElementById('address-input').addEventListener('keydown', function (e) {
            if (e.key === 'Enter') searchAddress();
        });

        document.getElementById('btn-route-start').addEventListener('click', setRouteStart);
        document.getElementById('btn-route-waypoint').addEventListener('click', addRouteWaypoint);
        document.getElementById('btn-route-end').addEventListener('click', setRouteEnd);
        document.getElementById('btn-clear-tasks').addEventListener('click', function () {
            if (SimModule.simId()) {
                leaveSimulation();
                return;
            }
            clearAllTasks();
        });

        document.getElementById('btn-sim-start').addEventListener('click', startSimulation);
        document.getElementById('btn-sim-pause').addEventListener('click', pauseSimulation);
        document.getElementById('btn-sim-tick').addEventListener('click', doTick);
        document.getElementById('btn-sim-stop').addEventListener('click', stopSimulation);
        document.getElementById('btn-auto-run').addEventListener('click', autoRun);
        document.getElementById('btn-toggle-graph').addEventListener('click', toggleRoadGraph);
        document.getElementById('btn-configure-vehicles').addEventListener('click', openVehicleConfigModal);
        document.getElementById('btn-close-vehicle-config').addEventListener('click', closeVehicleConfigModal);
        document.getElementById('btn-add-vehicle-row').addEventListener('click', addVehicleConfigRow);

        checkAuth();
        updateGraphToggleUi();
        updateSimulationControls();
        normalizeVehicleConfigs();
        updateVehicleConfigSummary();
        if (AuthModule.getToken()) {
            var activeSimId = initialSimulationId || SimModule.getSavedSimId();
            if (activeSimId) {
                loadExistingSimulation(activeSimId);
            }
        }
    });

    return {
        login: login,
        setRouteStart: setRouteStart,
        addRouteWaypoint: addRouteWaypoint,
        removeRouteWaypoint: removeRouteWaypoint,
        setRouteEnd: setRouteEnd,
        removeTask: removeTask,
        removeVehicleConfigRow: removeVehicleConfigRow,
        applyVehicleStatus: applyVehicleStatus,
        clearAllTasks: clearAllTasks,
        leaveSimulation: leaveSimulation,
        startSimulation: startSimulation,
        pauseSimulation: pauseSimulation,
        stopSimulation: stopSimulation,
        doTick: doTick,
        autoRun: autoRun,
    };
})();
