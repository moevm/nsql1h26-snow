(function () {
    var currentPage = 1;
    var pageSize = 20;
    var totalPages = 1;

    function buildQuery() {
        var p = ['page=' + currentPage, 'page_size=' + pageSize];
        var simId = document.getElementById('f-sim-id').value.trim();
        var status = document.getElementById('f-status').value;
        var vtype = document.getElementById('f-type').value;
        var createdFrom = document.getElementById('f-created-from').value;
        var createdTo = document.getElementById('f-created-to').value;
        var updFrom = document.getElementById('f-upd-from').value;
        var updTo = document.getElementById('f-upd-to').value;
        var targetType = document.getElementById('f-target-type').value.trim();
        var targetId = document.getElementById('f-target-id').value.trim();
        var sourceId = document.getElementById('f-source-id').value.trim();
        var destId = document.getElementById('f-dest-id').value.trim();
        var stepIdFilter = document.getElementById('f-step-id').value.trim();
        var machineId = document.getElementById('f-machine-id').value.trim();
        var latMin = document.getElementById('f-lat-min').value;
        var latMax = document.getElementById('f-lat-max').value;
        var lngMin = document.getElementById('f-lng-min').value;
        var lngMax = document.getElementById('f-lng-max').value;
        var fuelMin = document.getElementById('f-fuel-min').value;
        var fuelMax = document.getElementById('f-fuel-max').value;
        var snowMin = document.getElementById('f-snow-min').value;
        var snowMax = document.getElementById('f-snow-max').value;
        var distMin = document.getElementById('f-dist-min').value;
        var distMax = document.getElementById('f-dist-max').value;
        var speedMin = document.getElementById('f-speed-min').value;
        var speedMax = document.getElementById('f-speed-max').value;
        var travelSpeedMin = document.getElementById('f-travel-speed-min').value;
        var travelSpeedMax = document.getElementById('f-travel-speed-max').value;
        var cleaningSpeedMin = document.getElementById('f-cleaning-speed-min').value;
        var cleaningSpeedMax = document.getElementById('f-cleaning-speed-max').value;
        var fuelCapMin = document.getElementById('f-fuel-cap-min').value;
        var fuelCapMax = document.getElementById('f-fuel-cap-max').value;
        var snowCapMin = document.getElementById('f-snow-cap-min').value;
        var snowCapMax = document.getElementById('f-snow-cap-max').value;
        var breakdownMin = document.getElementById('f-breakdown-min').value;
        var breakdownMax = document.getElementById('f-breakdown-max').value;
        var repairRemMin = document.getElementById('f-repair-rem-min').value;
        var repairRemMax = document.getElementById('f-repair-rem-max').value;
        var progressMin = document.getElementById('f-progress-min').value;
        var progressMax = document.getElementById('f-progress-max').value;
        var tickMin = document.getElementById('f-tick-min').value;
        var tickMax = document.getElementById('f-tick-max').value;
        if (simId) p.push('sim_id=' + encodeURIComponent(simId));
        if (status) p.push('status=' + encodeURIComponent(status));
        if (vtype) p.push('vehicle_type=' + encodeURIComponent(vtype));
        if (createdFrom) p.push('created_at_from=' + encodeURIComponent(createdFrom));
        if (createdTo) p.push('created_at_to=' + encodeURIComponent(createdTo));
        if (updFrom) p.push('updated_at_from=' + encodeURIComponent(updFrom));
        if (updTo) p.push('updated_at_to=' + encodeURIComponent(updTo));
        if (targetType) p.push('target_type_filter=' + encodeURIComponent(targetType));
        if (targetId) p.push('target_id_filter=' + encodeURIComponent(targetId));
        if (sourceId) p.push('source_id_filter=' + encodeURIComponent(sourceId));
        if (destId) p.push('dest_id_filter=' + encodeURIComponent(destId));
        if (stepIdFilter) p.push('step_id_filter=' + encodeURIComponent(stepIdFilter));
        if (machineId) p.push('machine_id_filter=' + encodeURIComponent(machineId));
        if (latMin) p.push('lat_min=' + latMin);
        if (latMax) p.push('lat_max=' + latMax);
        if (lngMin) p.push('lng_min=' + lngMin);
        if (lngMax) p.push('lng_max=' + lngMax);
        if (fuelMin) p.push('fuel_min=' + fuelMin);
        if (fuelMax) p.push('fuel_max=' + fuelMax);
        if (snowMin) p.push('snow_min=' + snowMin);
        if (snowMax) p.push('snow_max=' + snowMax);
        if (distMin) p.push('dist_min=' + distMin);
        if (distMax) p.push('dist_max=' + distMax);
        if (speedMin) p.push('speed_min=' + speedMin);
        if (speedMax) p.push('speed_max=' + speedMax);
        if (travelSpeedMin) p.push('travel_speed_min=' + travelSpeedMin);
        if (travelSpeedMax) p.push('travel_speed_max=' + travelSpeedMax);
        if (cleaningSpeedMin) p.push('cleaning_speed_min=' + cleaningSpeedMin);
        if (cleaningSpeedMax) p.push('cleaning_speed_max=' + cleaningSpeedMax);
        if (fuelCapMin) p.push('fuel_cap_min=' + fuelCapMin);
        if (fuelCapMax) p.push('fuel_cap_max=' + fuelCapMax);
        if (snowCapMin) p.push('snow_cap_min=' + snowCapMin);
        if (snowCapMax) p.push('snow_cap_max=' + snowCapMax);
        if (breakdownMin) p.push('breakdown_min=' + breakdownMin);
        if (breakdownMax) p.push('breakdown_max=' + breakdownMax);
        if (repairRemMin) p.push('repair_rem_min=' + repairRemMin);
        if (repairRemMax) p.push('repair_rem_max=' + repairRemMax);
        if (progressMin) p.push('progress_min=' + progressMin);
        if (progressMax) p.push('progress_max=' + progressMax);
        if (tickMin) p.push('tick_min=' + tickMin);
        if (tickMax) p.push('tick_max=' + tickMax);
        return '?' + p.join('&');
    }

    function load() {
        if (!AuthModule.getToken()) return;
        showLoading(true);
        AuthModule.apiFetch('/api/vehicle-states/' + buildQuery())
            .then(function(r) { if (!r.ok) throw new Error(); return r.json(); })
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
        var tbody = document.getElementById('vs-tbody');
        var table = document.getElementById('vs-table');
        var empty = document.getElementById('empty-state');
        if (!items || !items.length) {
            table.style.display = 'none';
            empty.style.display = '';
            tbody.innerHTML = '';
            return;
        }
        table.style.display = ''; empty.style.display = 'none';
        tbody.innerHTML = items.map(function(v) {
            return '<tr onclick="window.location=\'/static/vehicle-state.html?id=' + v.id + '\'" style="cursor:pointer">'
                + '<td><a href="/static/vehicle-state.html?id=' + v.id + '">' + v.id + '</a></td>'
                + '<td>' + (v.simulation_id ? '<a href="/static/simulation.html?id=' + v.simulation_id + '" onclick="event.stopPropagation()">' + v.simulation_id + '</a>' : '—') + '</td>'
                + '<td>' + (v.step_id ? '<a href="/static/simulation-step.html?id=' + v.step_id + '" onclick="event.stopPropagation()">' + v.step_id + '</a>' : '—') + '</td>'
                + '<td>' + (v.vehicle_type || '—') + '</td>'
                + '<td>' + (v.status || '—') + '</td>'
                + '<td>' + (v.lat != null ? v.lat.toFixed(5) : '—') + '</td>'
                + '<td>' + (v.lng != null ? v.lng.toFixed(5) : '—') + '</td>'
                + '<td>' + (v.fuel_level != null ? v.fuel_level.toFixed(1) : '—') + '</td>'
                + '<td>' + (v.snow_loaded_m3 != null ? v.snow_loaded_m3 : '—') + '</td>'
                + '<td>' + (v.distance_travelled_km != null ? v.distance_travelled_km.toFixed(2) : '—') + ' км</td>'
                + '<td>' + (v.speed_kmh != null ? v.speed_kmh : '—') + '</td>'
                + '<td>' + (v.travel_speed_kmh != null ? v.travel_speed_kmh : '—') + '</td>'
                + '<td>' + (v.cleaning_speed_kmh != null ? v.cleaning_speed_kmh : '—') + '</td>'
                + '<td>' + (v.fuel_capacity_l != null ? v.fuel_capacity_l : '—') + '</td>'
                + '<td>' + (v.snow_capacity_m3 != null ? v.snow_capacity_m3 : '—') + '</td>'
                + '<td>' + (v.breakdown_probability != null ? v.breakdown_probability : '—') + '</td>'
                + '<td>' + (v.repair_remaining_min != null ? v.repair_remaining_min : '—') + '</td>'
                + '<td>' + (v.target_type || '—') + '</td>'
                + '<td>' + (v.target_id ? '<a href="/static/point.html?id=' + v.target_id + '" onclick="event.stopPropagation()">' + v.target_id + '</a>' : '—') + '</td>'
                + '<td>' + (v.progress_m != null ? v.progress_m : '—') + '</td>'
                + (function() {
                    if (!v.current_road) return '<td>—</td>';
                    var parts = v.current_road.split('->');
                    if (parts.length === 2 && parts[0] && parts[1]) {
                        return '<td><a href="/static/point.html?id=' + parts[0] + '" onclick="event.stopPropagation()">' + parts[0] + '</a> → <a href="/static/point.html?id=' + parts[1] + '" onclick="event.stopPropagation()">' + parts[1] + '</a></td>';
                    }
                    return '<td>' + v.current_road + '</td>';
                })()
                + '<td>' + (v.tick != null ? v.tick : '—') + '</td>'
                + '<td>' + fmtDate(v.created_at) + '</td>'
                + '<td>' + fmtDate(v.updated_at) + '</td>'
                + '</tr>';
        }).join('');
    }

    function renderPagination(pages) {
        var el = document.getElementById('pagination');
        if (!el || pages <= 1) { if (el) el.innerHTML = ''; return; }
        var html = '<button onclick="changePage(' + (currentPage - 1) + ')"' + (currentPage <= 1 ? ' disabled' : '') + '>&laquo;</button>'
            + '<span class="pagination-info">Стр. ' + currentPage + ' / ' + pages + '</span>'
            + '<button onclick="changePage(' + (currentPage + 1) + ')"' + (currentPage >= pages ? ' disabled' : '') + '>&raquo;</button>';
        el.innerHTML = html;
    }

    window.changePage = function(p) { if (p < 1 || p > totalPages) return; currentPage = p; load(); };

    function fmtDate(d) { if (!d) return '—'; return new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }); }
    function showLoading(s) { var e = document.getElementById('loading'); if (e) e.style.display = s ? '' : 'none'; }

    document.getElementById('btn-filter').addEventListener('click', function() { currentPage = 1; load(); });
    document.getElementById('btn-reset').addEventListener('click', function() {
        ['f-sim-id','f-created-from','f-created-to','f-upd-from','f-upd-to',
         'f-target-type','f-target-id','f-source-id','f-dest-id','f-step-id','f-machine-id',
         'f-lat-min','f-lat-max','f-lng-min','f-lng-max',
         'f-fuel-min','f-fuel-max','f-snow-min','f-snow-max','f-dist-min','f-dist-max',
         'f-speed-min','f-speed-max','f-travel-speed-min','f-travel-speed-max',
         'f-cleaning-speed-min','f-cleaning-speed-max','f-fuel-cap-min','f-fuel-cap-max',
         'f-snow-cap-min','f-snow-cap-max','f-breakdown-min','f-breakdown-max',
         'f-repair-rem-min','f-repair-rem-max','f-progress-min','f-progress-max',
         'f-tick-min','f-tick-max'].forEach(function(id) { var e = document.getElementById(id); if (e) e.value = ''; });
        ['f-status', 'f-type'].forEach(function(id) { var e = document.getElementById(id); if (e) e.selectedIndex = 0; });
        currentPage = 1; load();
    });

    var urlParams = new URLSearchParams(window.location.search);
    var simParam = urlParams.get('sim_id');
    if (simParam) document.getElementById('f-sim-id').value = simParam;
    if (AuthModule.getToken()) load();

    TableStatsModule.init({
        endpoint: '/api/vehicle-states/',
        paginated: true,
        buildQuery: buildQuery,
        stripPagination: true,
        extractItems: function (r) { return r.items || []; },
        attributes: [
            { key: 'status', label: 'Статус', type: 'categorical' },
            { key: 'lat', label: 'Широта', type: 'numeric' },
            { key: 'lng', label: 'Долгота', type: 'numeric' },
            { key: 'fuel_level', label: 'Топливо', type: 'numeric' },
            { key: 'snow_loaded_m3', label: 'Снег (м³)', type: 'numeric' },
            { key: 'distance_travelled_km', label: 'Дистанция (км)', type: 'numeric' },
            { key: 'speed_kmh', label: 'Скорость', type: 'numeric' },
            { key: 'travel_speed_kmh', label: 'Скор. езды', type: 'numeric' },
            { key: 'cleaning_speed_kmh', label: 'Скор. чистки', type: 'numeric' },
            { key: 'fuel_capacity_l', label: 'Бак (л)', type: 'numeric' },
            { key: 'snow_capacity_m3', label: 'Ёмк. снег (м³)', type: 'numeric' },
            { key: 'breakdown_probability', label: 'Поломка %', type: 'numeric' },
            { key: 'repair_remaining_min', label: 'Ремонт (мин)', type: 'numeric' },
            { key: 'progress_m', label: 'Прогресс (м)', type: 'numeric' },
            { key: 'tick', label: 'Тик', type: 'numeric' },
            { key: 'target_id', label: 'Цель ID', type: 'categorical' },
            { key: 'target_type', label: 'Цель тип', type: 'categorical' },
            { key: 'simulation_id', label: 'ID Симуляции', type: 'categorical' },
            { key: 'step_id', label: 'ID Шага', type: 'categorical' },
            { key: 'created_at', label: 'Создан', type: 'date' },
            { key: 'updated_at', label: 'Изменен', type: 'date' },
            { key: 'vehicle_type', label: 'Тип', type: 'categorical' },
            { key: 'id', label: 'ID', type: 'categorical' },
        ],
    });
})();
