var MapModule = (function () {
    var map;
    var objectMarkers = {};
    var vehicleMarkers = {};
    var vehicleRouteLayers = {};
    var vehicleDisplayPrefs = {};
    var routeLayer = null;
    var clickLatLng = null;
    var clickMarker = null;
    var selectedPoint = null;

    var taskRouteLayers = [];
    var taskMarkers = [];
    var simulationRouteLayers = [];
    var waypointMarkers = [];
    var roadGraphLayer = null;
    var roadGraphLoaded = false;
    var roadGraphVisible = false;

    var ICONS = {
        parking: '🅿️',
        snow_polygon: '🏔️',
        service_station: '🔧',
    };

    var ROUTE_COLORS = ['#d90429', '#f77f00', '#ffbe0b', '#2a9d8f', '#3a86ff', '#8338ec'];
    var VEHICLE_COLOR_PALETTE = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#14b8a6', '#3b82f6', '#8b5cf6', '#ec4899', '#f43f5e', '#84cc16'];
    var boundaryOutlineLayer = null;
    var VEHICLE_PREFS_STORAGE_KEY = 'snow_vehicle_display_prefs';

    var BBOX_SOUTH = 59.9665;
    var BBOX_WEST  = 30.2970;
    var BBOX_NORTH = 59.9805;
    var BBOX_EAST  = 30.3305;

    var MAP_BOUNDS = L.latLngBounds(
        [BBOX_SOUTH, BBOX_WEST],
        [BBOX_NORTH, BBOX_EAST]
    );

    function showSeedAreaOutline() {
        if (boundaryOutlineLayer) {
            map.removeLayer(boundaryOutlineLayer);
        }

        boundaryOutlineLayer = L.rectangle(MAP_BOUNDS, {
            color: '#ff4d4f',
            weight: 2,
            opacity: 0.95,
            fill: false,
            dashArray: '8 6',
            interactive: false,
        }).addTo(map);
    }

    function init() {
        loadVehicleDisplayPrefs();
        map = L.map('map', {
            maxZoom: 19,
            worldCopyJump: false,
        });

        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors',
            maxZoom: 19,
        }).addTo(map);

        map.fitBounds(MAP_BOUNDS, { animate: false, padding: [20, 20] });
        showSeedAreaOutline();

        map.on('click', function (e) {
            setSelectedPoint(e.latlng.lat, e.latlng.lng);
        });

        console.log('[MapModule] init OK');
        return map;
    }

    function loadVehicleDisplayPrefs() {
        try {
            vehicleDisplayPrefs = JSON.parse(localStorage.getItem(VEHICLE_PREFS_STORAGE_KEY) || '{}') || {};
        } catch (e) {
            vehicleDisplayPrefs = {};
        }
    }

    function saveVehicleDisplayPrefs() {
        localStorage.setItem(VEHICLE_PREFS_STORAGE_KEY, JSON.stringify(vehicleDisplayPrefs));
    }

    function hashVehicleId(vehicleId) {
        var hash = 0;
        for (var i = 0; i < vehicleId.length; i += 1) {
            hash = ((hash << 5) - hash) + vehicleId.charCodeAt(i);
            hash |= 0;
        }
        return Math.abs(hash);
    }

    function defaultVehicleColor(vehicleId) {
        return VEHICLE_COLOR_PALETTE[hashVehicleId(vehicleId) % VEHICLE_COLOR_PALETTE.length];
    }

    function getVehicleDisplayPrefs(vehicleId) {
        var prefs = vehicleDisplayPrefs[vehicleId] || {};
        return {
            color: prefs.color || defaultVehicleColor(vehicleId),
            hidden: !!prefs.hidden,
        };
    }

    function setVehicleDisplayPrefs(vehicleId, prefs) {
        var current = getVehicleDisplayPrefs(vehicleId);
        vehicleDisplayPrefs[vehicleId] = {
            color: prefs.color || current.color,
            hidden: typeof prefs.hidden === 'boolean' ? prefs.hidden : current.hidden,
        };
        saveVehicleDisplayPrefs();
    }

    function addContrastPolyline(latlngs, color, options) {
        options = options || {};
        var baseWeight = options.weight || 5;
        var layers = [
            L.polyline(latlngs, {
                color: '#111827',
                weight: baseWeight + 5,
                opacity: options.haloOpacity != null ? options.haloOpacity : 0.9,
                lineCap: 'round',
                lineJoin: 'round',
            }),
            L.polyline(latlngs, {
                color: '#f8fafc',
                weight: baseWeight + 2,
                opacity: options.casingOpacity != null ? options.casingOpacity : 0.92,
                lineCap: 'round',
                lineJoin: 'round',
            }),
            L.polyline(latlngs, {
                color: color,
                weight: baseWeight,
                opacity: options.opacity != null ? options.opacity : 1,
                dashArray: options.dashArray || null,
                lineCap: 'round',
                lineJoin: 'round',
            }),
        ];
        return L.layerGroup(layers).addTo(map);
    }

    function loadRoadGraph(token) {
        if (!token) return Promise.reject(new Error('no-token'));
        if (roadGraphLoaded) return Promise.resolve();
        return fetch('/api/routes/graph', {
            headers: { Authorization: 'Bearer ' + token }
        })
            .then(function (resp) {
                if (!resp.ok) throw new Error('graph');
                return resp.json();
            })
            .then(function (roads) {
                var edgeLayers = [];
                var nodesById = {};
                (roads || []).forEach(function (road) {
                    var coords = Array.isArray(road.geometry) && road.geometry.length >= 2
                        ? road.geometry.map(function (p) { return [p[0], p[1]]; })
                        : [[road.src_lat, road.src_lng], [road.dst_lat, road.dst_lng]];
                    edgeLayers.push(L.polyline(coords, {
                        color: road.cleaned ? '#94a3b8' : '#0f766e',
                        weight: 2,
                        opacity: road.cleaned ? 0.3 : 0.48,
                        lineCap: 'round',
                        interactive: false,
                    }));
                    nodesById[road.src] = [road.src_lat, road.src_lng];
                    nodesById[road.dst] = [road.dst_lat, road.dst_lng];
                });
                var nodeLayers = Object.keys(nodesById).map(function (nodeId) {
                    var latlng = nodesById[nodeId];
                    return L.circleMarker(latlng, {
                        radius: 2,
                        color: '#f8fafc',
                        weight: 1,
                        fillColor: '#111827',
                        fillOpacity: 0.92,
                        opacity: 0.95,
                        interactive: false,
                    });
                });
                roadGraphLayer = L.layerGroup(edgeLayers.concat(nodeLayers));
                roadGraphLoaded = true;
                if (roadGraphVisible) {
                    map.addLayer(roadGraphLayer);
                    if (boundaryOutlineLayer) {
                        boundaryOutlineLayer.bringToFront();
                    }
                }
            })
            .catch(function () {
                roadGraphLoaded = false;
            });
    }

    function setRoadGraphVisible(visible, token) {
        roadGraphVisible = !!visible;
        if (roadGraphVisible) {
            return loadRoadGraph(token).then(function () {
                if (roadGraphLayer && !map.hasLayer(roadGraphLayer)) {
                    map.addLayer(roadGraphLayer);
                }
                if (boundaryOutlineLayer) {
                    boundaryOutlineLayer.bringToFront();
                }
            });
        }
        if (roadGraphLayer && map.hasLayer(roadGraphLayer)) {
            map.removeLayer(roadGraphLayer);
        }
        return Promise.resolve();
    }

    function toggleRoadGraph(token) {
        return setRoadGraphVisible(!roadGraphVisible, token).then(function () {
            return roadGraphVisible;
        });
    }

    function isRoadGraphVisible() {
        return roadGraphVisible;
    }

    function setSelectedPoint(lat, lng) {
        selectedPoint = { lat: lat, lng: lng };
        console.log('[MapModule] selected point:', lat, lng);

        if (clickMarker) map.removeLayer(clickMarker);
        clickMarker = L.circleMarker([lat, lng], {
            radius: 10, color: '#f38ba8', fillColor: '#f38ba8',
            fillOpacity: 0.9, weight: 2,
        }).addTo(map);

        var el = document.getElementById('route-coords');
        if (el) el.textContent = lat.toFixed(5) + ', ' + lng.toFixed(5);
    }

    function getSelectedPoint() {
        return selectedPoint;
    }

    function panTo(lat, lng, zoom) {
        map.setView([lat, lng], zoom || 16);
    }

    function searchAddress(query, callback) {
        var url = 'https://nominatim.openstreetmap.org/search?format=json&limit=5&countrycodes=ru'
            + '&viewbox=' + MAP_BOUNDS.getWest() + ',' + MAP_BOUNDS.getNorth() + ',' + MAP_BOUNDS.getEast() + ',' + MAP_BOUNDS.getSouth()
            + '&bounded=1'
            + '&q=' + encodeURIComponent(query);

        fetch(url, {
            headers: { 'Accept-Language': 'ru' }
        })
            .then(function (r) { return r.json(); })
            .then(function (results) { callback(null, results); })
            .catch(function (e) { callback(e, null); });
    }

    function addObjectMarker(obj) {
        var icon = L.divIcon({
            html: '<span style="font-size:22px">' + (ICONS[obj.type] || '📌') + '</span>',
            className: '',
            iconSize: [28, 28],
            iconAnchor: [14, 14],
        });

        var lat = obj.location ? obj.location.lat : obj.lat;
        var lng = obj.location ? obj.location.lng : obj.lng;

        var marker = L.marker([lat, lng], { icon: icon })
            .addTo(map)
            .bindPopup('<b>' + obj.name + '</b><br>' + obj.type);

        objectMarkers[obj.id] = marker;
    }

    function removeObjectMarker(id) {
        if (objectMarkers[id]) {
            map.removeLayer(objectMarkers[id]);
            delete objectMarkers[id];
        }
    }

    function clearObjectMarkers() {
        Object.values(objectMarkers).forEach(function (m) { map.removeLayer(m); });
        objectMarkers = {};
    }

    function updateVehicles(vehicles) {
        Object.values(vehicleMarkers).forEach(function (m) { map.removeLayer(m); });
        vehicleMarkers = {};
        Object.values(vehicleRouteLayers).forEach(function (l) { map.removeLayer(l); });
        vehicleRouteLayers = {};

        vehicles.forEach(function (v) {
            var prefs = getVehicleDisplayPrefs(v.id);
            if (prefs.hidden) {
                return;
            }
            var color = prefs.color;

            var cm = L.circleMarker([v.location.lat, v.location.lng], {
                radius: 7, color: '#ffffff', fillColor: color,
                fillOpacity: 1, weight: 3,
            }).addTo(map).bindPopup(
                '<b><a href="/static/vehicle-state.html?id=' + encodeURIComponent(v.id) + '">' + v.id + '</a></b><br>'
                + 'Статус: ' + (v.status || '—') + '<br>'
                + 'Топливо: ' + (v.fuel_level != null ? v.fuel_level.toFixed(1) : '—') + ' л<br>'
                + 'Снег: ' + (v.snow_loaded_m3 != null ? v.snow_loaded_m3.toFixed(2) : '—') + ' м³<br>'
                + 'Текущая скорость: ' + (v.speed_kmh != null ? v.speed_kmh.toFixed(1) : '—') + ' км/ч<br>'
                + 'Движение / уборка: ' + (v.travel_speed_kmh != null ? v.travel_speed_kmh.toFixed(1) : '—') + ' / ' + (v.cleaning_speed_kmh != null ? v.cleaning_speed_kmh.toFixed(1) : '—') + ' км/ч<br>'
                + 'Цель: ' + ((v.target_type || '—') + (v.target_id ? ' / ' + v.target_id : '')) + '<br>'
                + 'Дорога: ' + (v.current_road || v.current_edge || '—')
            );
            cm.on('click', function () {
                window.location.href = '/static/vehicle-state.html?id=' + encodeURIComponent(v.id);
            });

            if ((v.status === 'off_route'
                    || v.status === 'en_route'
                    || v.status === 'dumping'
                    || v.status === 'refueling'
                    || v.status === 'maintenance'
                    || (v.status === 'cleaning' && v.target_type === 'road_start'))
                    && v.target_location) {
                var routePoints = [[v.location.lat, v.location.lng]];
                if (v.path_waypoints && v.path_waypoints.length) {
                    v.path_waypoints.forEach(function (wp) {
                        routePoints.push([wp.lat, wp.lng]);
                    });
                }
                routePoints.push([v.target_location.lat, v.target_location.lng]);
                vehicleRouteLayers[v.id] = addContrastPolyline(routePoints, color, {
                    weight: 4,
                    opacity: 0.95,
                    dashArray: '10 8',
                    haloOpacity: 0.85,
                    casingOpacity: 0.88
                });
            }

            vehicleMarkers[v.id] = cm;
        });
    }

    function clearVehicles() {
        Object.values(vehicleMarkers).forEach(function (m) { map.removeLayer(m); });
        vehicleMarkers = {};
        Object.values(vehicleRouteLayers).forEach(function (l) { map.removeLayer(l); });
        vehicleRouteLayers = {};
    }

    function drawRoute(segments) {
        if (routeLayer) map.removeLayer(routeLayer);
        var coords = segments.flatMap(function (s) {
            return s.coords.map(function (c) { return [c.lat, c.lng]; });
        });
        routeLayer = addContrastPolyline(coords, '#d90429', { weight: 6 });
        map.fitBounds(L.latLngBounds(coords), { padding: [40, 40] });
    }

    function clearRoute() {
        if (routeLayer) { map.removeLayer(routeLayer); routeLayer = null; }
    }

    function addTaskRoute(coords, index) {
        var color = ROUTE_COLORS[index % ROUTE_COLORS.length];
        var latlngs = coords.map(function (c) { return [c.lat, c.lng]; });
        var line = addContrastPolyline(latlngs, color, {
            weight: 6,
            opacity: 1,
            dashArray: '12 8',
        });
        taskRouteLayers.push(line);

        if (latlngs.length >= 2) {
            var startIcon = L.divIcon({ html: '<span style="font-size:18px">🟢</span>', className: '', iconSize: [20, 20], iconAnchor: [10, 10] });
            var endIcon = L.divIcon({ html: '<span style="font-size:18px">🔴</span>', className: '', iconSize: [20, 20], iconAnchor: [10, 10] });
            taskMarkers.push(L.marker(latlngs[0], { icon: startIcon }).addTo(map));
            taskMarkers.push(L.marker(latlngs[latlngs.length - 1], { icon: endIcon }).addTo(map));
        }

        var allLatLngs = [];
        taskRouteLayers.forEach(function (layerGroup) {
            layerGroup.eachLayer(function (layer) {
                if (layer.getLatLngs) {
                    var pts = layer.getLatLngs();
                    if (Array.isArray(pts) && pts.length) {
                        allLatLngs = allLatLngs.concat(pts);
                    }
                }
            });
        });
        if (allLatLngs.length) {
            map.fitBounds(L.latLngBounds(allLatLngs), { padding: [50, 50] });
        }
    }

    function clearTaskRoutes() {
        taskRouteLayers.forEach(function (l) { map.removeLayer(l); });
        taskRouteLayers = [];
        taskMarkers.forEach(function (m) { map.removeLayer(m); });
        taskMarkers = [];
    }

    function drawSimulationRoutes(routeCoordsList) {
        clearSimulationRoutes();
        routeCoordsList.forEach(function (nodes, i) {
            var color = ROUTE_COLORS[i % ROUTE_COLORS.length];
            var latlngs = nodes.map(function (n) { return [n.lat, n.lng]; });
            var line = addContrastPolyline(latlngs, color, { weight: 6, opacity: 1 });
            simulationRouteLayers.push(line);
        });
    }

    function clearSimulationRoutes() {
        simulationRouteLayers.forEach(function (l) { map.removeLayer(l); });
        simulationRouteLayers = [];
    }

    function addWaypointMarker(lat, lng, index) {
        var icon = L.divIcon({
            html: '<div style="background:#f9e2af;color:#1e1e2e;border-radius:50%;width:22px;height:22px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:bold;border:2px solid #1e1e2e">' + index + '</div>',
            className: '',
            iconSize: [22, 22],
            iconAnchor: [11, 11],
        });
        var m = L.marker([lat, lng], { icon: icon }).addTo(map)
            .bindPopup('Точка ' + index + ': ' + lat.toFixed(5) + ', ' + lng.toFixed(5));
        waypointMarkers.push(m);
    }

    function clearWaypointMarkers() {
        waypointMarkers.forEach(function (m) { map.removeLayer(m); });
        waypointMarkers = [];
    }

    return {
        init: init,
        getSelectedPoint: getSelectedPoint,
        setSelectedPoint: setSelectedPoint,
        panTo: panTo,
        searchAddress: searchAddress,
        addObjectMarker: addObjectMarker,
        removeObjectMarker: removeObjectMarker,
        clearObjectMarkers: clearObjectMarkers,
        updateVehicles: updateVehicles,
        clearVehicles: clearVehicles,
        getVehicleDisplayPrefs: getVehicleDisplayPrefs,
        setVehicleDisplayPrefs: setVehicleDisplayPrefs,
        drawRoute: drawRoute,
        clearRoute: clearRoute,
        addTaskRoute: addTaskRoute,
        clearTaskRoutes: clearTaskRoutes,
        drawSimulationRoutes: drawSimulationRoutes,
        clearSimulationRoutes: clearSimulationRoutes,
        loadRoadGraph: loadRoadGraph,
        setRoadGraphVisible: setRoadGraphVisible,
        toggleRoadGraph: toggleRoadGraph,
        isRoadGraphVisible: isRoadGraphVisible,
        addWaypointMarker: addWaypointMarker,
        clearWaypointMarkers: clearWaypointMarkers,
    };
})();
