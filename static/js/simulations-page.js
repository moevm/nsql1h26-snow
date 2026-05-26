(function () {
    var currentPage = 1;
    var pageSize = 20;
    var totalPages = 1;

    function getFilters() {
        return {
            sim_id_filter: document.getElementById('f-sim-id').value.trim() || null,
            name: document.getElementById('f-name').value.trim() || null,
            status: document.getElementById('f-status').value || null,
            vehicles_min: document.getElementById('f-veh-min').value || null,
            vehicles_max: document.getElementById('f-veh-max').value || null,
            date_from: document.getElementById('f-date-from').value || null,
            date_to: document.getElementById('f-date-to').value || null,
            updated_at_from: document.getElementById('f-upd-from').value || null,
            updated_at_to: document.getElementById('f-upd-to').value || null,
            vehicles_en_route_min: document.getElementById('f-en-route-min').value || null,
            vehicles_en_route_max: document.getElementById('f-en-route-max').value || null,
            vehicles_cleaning_min: document.getElementById('f-cleaning-min').value || null,
            vehicles_cleaning_max: document.getElementById('f-cleaning-max').value || null,
            vehicles_dumping_min: document.getElementById('f-dumping-min').value || null,
            vehicles_dumping_max: document.getElementById('f-dumping-max').value || null,
            vehicles_refueling_min: document.getElementById('f-refueling-min').value || null,
            vehicles_refueling_max: document.getElementById('f-refueling-max').value || null,
            vehicles_maintenance_min: document.getElementById('f-maintenance-min').value || null,
            vehicles_maintenance_max: document.getElementById('f-maintenance-max').value || null,
            snow_min: document.getElementById('f-snow-min').value || null,
            snow_max: document.getElementById('f-snow-max').value || null,
            fuel_min: document.getElementById('f-fuel-min').value || null,
            fuel_max: document.getElementById('f-fuel-max').value || null,
            avg_fuel_min: document.getElementById('f-avg-fuel-min').value || null,
            avg_fuel_max: document.getElementById('f-avg-fuel-max').value || null,
            avg_snow_min: document.getElementById('f-avg-snow-min').value || null,
            avg_snow_max: document.getElementById('f-avg-snow-max').value || null,
            roads_total_min: document.getElementById('f-roads-min').value || null,
            roads_total_max: document.getElementById('f-roads-max').value || null,
            speed_multiplier_min: document.getElementById('f-speed-mult-min').value || null,
            speed_multiplier_max: document.getElementById('f-speed-mult-max').value || null,
            tick_duration_min_min: document.getElementById('f-tick-dur-min').value || null,
            tick_duration_min_max: document.getElementById('f-tick-dur-max').value || null,
            snowfall_cm_min: document.getElementById('f-snowfall-min').value || null,
            snowfall_cm_max: document.getElementById('f-snowfall-max').value || null,
            refuel_threshold_min: document.getElementById('f-refuel-thr-min').value || null,
            refuel_threshold_max: document.getElementById('f-refuel-thr-max').value || null,
            dump_threshold_min: document.getElementById('f-dump-thr-min').value || null,
            dump_threshold_max: document.getElementById('f-dump-thr-max').value || null,
            snow_melt_rate_min: document.getElementById('f-melt-min').value || null,
            snow_melt_rate_max: document.getElementById('f-melt-max').value || null,
            roads_cleaned_pct_min: document.getElementById('f-roads-cleaned-min').value || null,
            roads_cleaned_pct_max: document.getElementById('f-roads-cleaned-max').value || null,
            tick_min: document.getElementById('f-tick-min').value || null,
            tick_max: document.getElementById('f-tick-max').value || null,
            elapsed_minutes_min: document.getElementById('f-elapsed-min').value || null,
            elapsed_minutes_max: document.getElementById('f-elapsed-max').value || null,
            streets_count_min: document.getElementById('f-streets-count-min').value || null,
            streets_count_max: document.getElementById('f-streets-count-max').value || null,
            started_at_from: document.getElementById('f-started-from').value || null,
            started_at_to: document.getElementById('f-started-to').value || null,
            finished_at_from: document.getElementById('f-finished-from').value || null,
            finished_at_to: document.getElementById('f-finished-to').value || null,
        };
    }

    function buildQuery(f) {
        var p = ['page=' + currentPage, 'page_size=' + pageSize];
        Object.keys(f).forEach(function(k) {
            if (f[k] !== null && f[k] !== undefined && f[k] !== '') p.push(k + '=' + encodeURIComponent(f[k]));
        });
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
            var params = {};
            try { params = JSON.parse(s.params_json || '{}'); } catch(e) {}
            return '<tr onclick="window.location=\'/static/simulation.html?id=' + s.id + '\'" style="cursor:pointer">'
                + '<td><a href="/static/simulation.html?id=' + s.id + '">' + s.id + '</a></td>'
                + '<td>' + (s.name || '<span style="color:var(--text-dim)">—</span>') + '</td>'
                + '<td>' + statusBadge(s.status) + '</td>'
                + '<td>' + (s.tick || 0) + '</td>'
                + '<td>' + Math.round(s.elapsed_minutes || 0) + ' мин</td>'
                + '<td>' + (s.roads_cleaned_pct || 0) + '%</td>'
                + '<td>' + (s.vehicles_total || 0) + '</td>'
                + '<td>' + (s.vehicles_en_route != null ? s.vehicles_en_route : '—') + '</td>'
                + '<td>' + (s.vehicles_cleaning != null ? s.vehicles_cleaning : '—') + '</td>'
                + '<td>' + (s.vehicles_dumping != null ? s.vehicles_dumping : '—') + '</td>'
                + '<td>' + (s.vehicles_refueling != null ? s.vehicles_refueling : '—') + '</td>'
                + '<td>' + (s.vehicles_maintenance != null ? s.vehicles_maintenance : '—') + '</td>'
                + '<td>' + (s.snow_collected_m3 != null ? s.snow_collected_m3 : '—') + '</td>'
                + '<td>' + (s.fuel_spent_l != null ? s.fuel_spent_l : '—') + '</td>'
                + '<td>' + (s.avg_fuel_pct != null ? s.avg_fuel_pct : '—') + '</td>'
                + '<td>' + (s.avg_snow_load_pct != null ? s.avg_snow_load_pct : '—') + '</td>'
                + '<td>' + (s.roads_total != null ? s.roads_total : '—') + '</td>'
                + '<td>' + (params.speed_multiplier != null ? params.speed_multiplier : '—') + '</td>'
                + '<td>' + (params.tick_duration_min != null ? params.tick_duration_min : '—') + '</td>'
                + '<td>' + (params.snowfall_cm != null ? params.snowfall_cm : '—') + '</td>'
                + '<td>' + (params.refuel_threshold_pct != null ? params.refuel_threshold_pct : '—') + '</td>'
                + '<td>' + (params.dump_threshold_pct != null ? params.dump_threshold_pct : '—') + '</td>'
                + '<td>' + (params.snow_melt_rate_m3_per_tick != null ? params.snow_melt_rate_m3_per_tick : '—') + '</td>'
                + '<td>' + (s.streets || []).length + '</td>'
                + '<td>' + fmtDate(s.created_at) + '</td>'
                + '<td>' + fmtDate(s.updated_at) + '</td>'
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
        ['f-sim-id','f-name','f-status','f-veh-min','f-veh-max','f-date-from','f-date-to','f-upd-from','f-upd-to',
         'f-en-route-min','f-en-route-max','f-cleaning-min','f-cleaning-max','f-dumping-min','f-dumping-max',
         'f-refueling-min','f-refueling-max','f-maintenance-min','f-maintenance-max',
         'f-snow-min','f-snow-max','f-fuel-min','f-fuel-max','f-avg-fuel-min','f-avg-fuel-max',
         'f-avg-snow-min','f-avg-snow-max','f-roads-min','f-roads-max',
         'f-speed-mult-min','f-speed-mult-max','f-tick-dur-min','f-tick-dur-max',
         'f-snowfall-min','f-snowfall-max','f-refuel-thr-min','f-refuel-thr-max',
         'f-dump-thr-min','f-dump-thr-max','f-melt-min','f-melt-max',
         'f-roads-cleaned-min','f-roads-cleaned-max','f-tick-min','f-tick-max',
         'f-elapsed-min','f-elapsed-max','f-streets-count-min','f-streets-count-max',
         'f-started-from','f-started-to','f-finished-from','f-finished-to'].forEach(function(id){
            var el=document.getElementById(id); if(el) el.tagName==='SELECT' ? el.selectedIndex=0 : (el.value='');
        });
        currentPage = 1; loadSims();
    });

    if (AuthModule.getToken()) loadSims();

    TableStatsModule.init({
        endpoint: '/api/simulation/',
        getFilters: getFilters,
        extractItems: function (r) { return r.items || []; },
        getValue: function (it, key) {
            if (key === 'streets_count') return (it.streets || []).length;
            if (key.indexOf('params.') === 0) {
                try { return JSON.parse(it.params_json || '{}')[key.slice(7)]; } catch (e) { return undefined; }
            }
            return it[key];
        },
        attributes: [
            { key: 'status', label: 'Статус', type: 'categorical' },
            { key: 'tick', label: 'Тик', type: 'numeric' },
            { key: 'roads_cleaned_pct', label: 'Убрано (%)', type: 'numeric' },
            { key: 'streets_count', label: 'Улиц', type: 'numeric' },
            { key: 'vehicles_total', label: 'Техника', type: 'numeric' },
            { key: 'vehicles_en_route', label: 'Едут', type: 'numeric' },
            { key: 'vehicles_cleaning', label: 'Чистят', type: 'numeric' },
            { key: 'vehicles_dumping', label: 'Сброс снега', type: 'numeric' },
            { key: 'vehicles_refueling', label: 'Заправка', type: 'numeric' },
            { key: 'vehicles_maintenance', label: 'Техобслуж.', type: 'numeric' },
            { key: 'snow_collected_m3', label: 'Снег (м³)', type: 'numeric' },
            { key: 'fuel_spent_l', label: 'Топливо (л)', type: 'numeric' },
            { key: 'avg_fuel_pct', label: 'Ср. топл. %', type: 'numeric' },
            { key: 'avg_snow_load_pct', label: 'Ср. снег %', type: 'numeric' },
            { key: 'roads_total', label: 'Дорог', type: 'numeric' },
            { key: 'elapsed_minutes', label: 'Время (мин)', type: 'numeric' },
            { key: 'params.speed_multiplier', label: 'Ускорение', type: 'numeric' },
            { key: 'params.tick_duration_min', label: 'Длина тика', type: 'numeric' },
            { key: 'params.snowfall_cm', label: 'Снегопад (см)', type: 'numeric' },
            { key: 'params.refuel_threshold_pct', label: 'Порог заправки %', type: 'numeric' },
            { key: 'params.dump_threshold_pct', label: 'Порог сброса %', type: 'numeric' },
            { key: 'params.snow_melt_rate_m3_per_tick', label: 'Скор. плавильни', type: 'numeric' },
            { key: 'created_at', label: 'Создан', type: 'date' },
            { key: 'updated_at', label: 'Изменен', type: 'date' },
            { key: 'started_at', label: 'Начало', type: 'date' },
            { key: 'finished_at', label: 'Конец', type: 'date' },
            { key: 'id', label: 'ID', type: 'categorical' },
            { key: 'name', label: 'Навзание', type: 'categorical' },
        ],
    });
})();
