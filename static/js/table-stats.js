var TableStatsModule = (function () {
    var cfg = null;
    var chart = null;
    var lastItems = [];

    function init(config) {
        cfg = Object.assign({
            largePage: 100000,
            extractItems: function (r) { return Array.isArray(r) ? r : (r.items || []); },
            getValue: function (item, key) { return item ? item[key] : undefined; },
            attributes: [],
        }, config);

        if (cfg.filterFields) {
            cfg.buildQuery = buildQueryFromFields;
        } else if (cfg.getFilters) {
            cfg.buildQuery = buildQueryFromFilters;
        } else if (cfg.stripPagination && cfg.buildQuery) {
            var orig = cfg.buildQuery;
            cfg.buildQuery = function () {
                return orig().replace(/[?&]page=\d+/g, '').replace(/[?&]page_size=\d+/g, '').replace(/^&/, '?') || '';
            };
        }

        injectModal();
        var btn = document.getElementById('btn-stats');
        if (btn) btn.onclick = openModal;
    }

    function buildQueryFromFields() {
        var pairs = [];
        cfg.filterFields.forEach(function (f) {
            var el = document.getElementById(f.id);
            if (!el) return;
            var val = el.type === 'checkbox' ? (el.checked ? 'true' : '') : el.value;
            if (val) pairs.push(f.param + '=' + encodeURIComponent(val));
        });
        return pairs.length ? '?' + pairs.join('&') : '';
    }

    function buildQueryFromFilters() {
        var f = cfg.getFilters();
        var skip = ['page', 'page_size'];
        var pairs = [];
        Object.keys(f).forEach(function (k) {
            if (skip.indexOf(k) >= 0) return;
            var v = f[k];
            if (v !== null && v !== undefined && v !== '') pairs.push(k + '=' + encodeURIComponent(v));
        });
        return pairs.length ? '?' + pairs.join('&') : '';
    }

    function injectModal() {
        if (document.getElementById('stats-modal')) return;
        var opts = cfg.attributes.map(function (a, i) {
            return '<option value="' + i + '">' + a.label + '</option>';
        }).join('');
        var html = '<div id="stats-modal" class="modal-overlay" style="display:none">'
            + '<div class="modal" style="max-width:900px;width:90%">'
            + '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">'
            + '<h3>Гистограмма статистики</h3>'
            + '<button id="stats-close" style="background:transparent;border:none;color:var(--text);font-size:1.2rem;cursor:pointer">×</button>'
            + '</div>'
            + '<p>Статистика считается только для отфильтрованного на таблице набора объектов. Выберите поля для учёта и количество бинов по обеим осям в гистограмме. Если ось откладывается по полю типа Категория или Строка, количество бинов будет равно количеству категорий или строк.</p>'
            + '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:end;margin-bottom:8px">'
            + '<label>Ось X: <select id="stats-x">' + opts + '</select></label>'
            + '<label>Ось Y: <select id="stats-y">' + opts + '</select></label>'
            + '<label>Бинов X: <input id="stats-bins-x" type="number" min="2" max="50" value="10" style="width:60px" /></label>'
            + '<label>Бинов Y: <input id="stats-bins-y" type="number" min="2" max="20" value="6" style="width:60px" /></label>'
            + '<button id="stats-refresh" class="btn-blue">Обновить</button>'
            + '<span id="stats-count" style="color:var(--text-dim);font-size:0.85rem"></span>'
            + '</div>'
            + '<div style="position:relative;height:420px"><canvas id="stats-canvas"></canvas></div>'
            + '<div id="stats-empty" class="empty-state" style="display:none;margin-top:8px">Нет данных для отображения</div>'
            + '</div></div>';
        var wrap = document.createElement('div');
        wrap.innerHTML = html;
        document.body.appendChild(wrap.firstChild);
        document.getElementById('stats-close').onclick = closeModal;
        document.getElementById('stats-refresh').onclick = rebuild;
        if (cfg.attributes.length > 1) document.getElementById('stats-y').selectedIndex = 1;
        ['stats-x', 'stats-y', 'stats-bins-x', 'stats-bins-y'].forEach(function (id) {
            document.getElementById(id).onchange = rebuild;
        });
    }

    function getAxes() {
        var xIdx = parseInt(document.getElementById('stats-x').value, 10);
        var yIdx = parseInt(document.getElementById('stats-y').value, 10);
        var binsX = parseInt(document.getElementById('stats-bins-x').value, 10) || 10;
        var binsY = parseInt(document.getElementById('stats-bins-y').value, 10) || 6;
        return { ax: cfg.attributes[xIdx], ay: cfg.attributes[yIdx], binsX: binsX, binsY: binsY };
    }

    function openModal() {
        document.getElementById('stats-modal').style.display = 'flex';
        fetchData().then(rebuild);
    }

    function closeModal() {
        document.getElementById('stats-modal').style.display = 'none';
    }

    function fetchData() {
        var q = cfg.buildQuery ? cfg.buildQuery() : '';
        q = (q ? q + '&' : '?') + 'page=1&page_size=' + cfg.largePage;
        document.getElementById('stats-count').textContent = 'загрузка...';
        return AuthModule.apiFetch(cfg.endpoint + q)
            .then(function (r) { if (!r.ok) throw new Error(); return r.json(); })
            .then(function (d) {
                lastItems = cfg.extractItems(d) || [];
                document.getElementById('stats-count').textContent = 'Найдено: ' + lastItems.length;
            })
            .catch(function () {
                lastItems = [];
                document.getElementById('stats-count').textContent = 'ошибка загрузки';
            });
    }

    function rebuild() {
        var a = getAxes();
        if (!a.ax || !a.ay) return;
        var xVals = lastItems.map(function (it) { return cfg.getValue(it, a.ax.key); });
        var yVals = lastItems.map(function (it) { return cfg.getValue(it, a.ay.key); });
        var xB = makeBucketer(a.ax, xVals, a.binsX);
        var yB = makeBucketer(a.ay, yVals, a.binsY);
        var counts = {};
        for (var i = 0; i < lastItems.length; i++) {
            var xb = xB.bucketOf(xVals[i]);
            var yb = yB.bucketOf(yVals[i]);
            if (xb == null || yb == null) continue;
            if (!counts[xb]) counts[xb] = {};
            counts[xb][yb] = (counts[xb][yb] || 0) + 1;
        }
        var matrix = xB.labels.map(function (xl) {
            return yB.labels.map(function (yl) { return (counts[xl] && counts[xl][yl]) || 0; });
        });
        renderMatrix(xB.labels, yB.labels, matrix, a.ax.label, a.ay.label);
    }

    function renderMatrix(xLabels, yLabels, counts, axLabel, ayLabel) {
        var empty = document.getElementById('stats-empty');
        if (!xLabels.length || !yLabels.length) {
            empty.style.display = '';
            if (chart) { chart.destroy(); chart = null; }
            return;
        }
        empty.style.display = 'none';
        var n = yLabels.length;
        var datasets = yLabels.map(function (yl, j) {
            var color = 'hsl(' + Math.round(j * 360 / n) + ',65%,65%)';
            return {
                label: yl,
                backgroundColor: color,
                data: xLabels.map(function (_, i) { return (counts[i] && counts[i][j]) || 0; }),
                stack: 's',
            };
        });
        var ctx = document.getElementById('stats-canvas').getContext('2d');
        if (chart) chart.destroy();
        chart = new Chart(ctx, {
            type: 'bar',
            data: { labels: xLabels, datasets: datasets },
            options: {
                responsive: true, maintainAspectRatio: false,
                plugins: {
                    legend: { labels: { color: '#cdd6f4' } },
                    tooltip: { mode: 'index' },
                    title: { display: true, text: 'Кол-во по ' + axLabel + ' / ' + ayLabel, color: '#cdd6f4' },
                },
                scales: {
                    x: { stacked: true, ticks: { color: '#a6adc8' }, grid: { color: '#3a3a50' }, title: { display: true, text: axLabel, color: '#a6adc8' } },
                    y: { stacked: true, beginAtZero: true, ticks: { color: '#a6adc8', precision: 0 }, grid: { color: '#3a3a50' }, title: { display: true, text: 'Количество', color: '#a6adc8' } },
                },
            },
        });
    }

    function makeBucketer(attr, values, bins) {
        var type = attr.type || 'auto';
        if (type === 'auto') type = inferType(values);
        if (type === 'numeric') return numericBucketer(values, bins);
        if (type === 'date') return dateBucketer(values, bins);
        return categoricalBucketer(values);
    }

    function inferType(values) {
        var sample = values.filter(function (v) { return v != null && v !== ''; }).slice(0, 30);
        if (!sample.length) return 'categorical';
        if (sample.every(function (v) { return typeof v === 'number' || (!isNaN(parseFloat(v)) && isFinite(v)); })) return 'numeric';
        if (sample.every(function (v) { return !isNaN(Date.parse(v)); })) return 'date';
        return 'categorical';
    }

    function categoricalBucketer(values) {
        var seen = {};
        values.forEach(function (v) { seen[v == null || v === '' ? '—' : String(v)] = true; });
        var labels = Object.keys(seen).sort();
        return {
            labels: labels,
            bucketOf: function (v) { return v == null || v === '' ? '—' : String(v); },
        };
    }

    function numericBucketer(values, bins) {
        var nums = values.map(parseFloat).filter(function (v) { return !isNaN(v); });
        if (!nums.length) return { labels: [], bucketOf: function () { return null; } };
        var mn = Math.min.apply(null, nums), mx = Math.max.apply(null, nums);
        if (mn === mx) {
            var lbl = fmtNum(mn);
            return { labels: [lbl], bucketOf: function (v) { return isNaN(parseFloat(v)) ? null : lbl; } };
        }
        var step = (mx - mn) / bins;
        var labels = [];
        for (var i = 0; i < bins; i++) labels.push(fmtNum(mn + i * step, step) + '–' + fmtNum(mn + (i + 1) * step, step));
        return {
            labels: labels,
            bucketOf: function (v) {
                var n = parseFloat(v);
                if (isNaN(n)) return null;
                return labels[Math.min(bins - 1, Math.max(0, Math.floor((n - mn) / step)))];
            },
        };
    }

    function dateBucketer(values, bins) {
        var ts = values.map(function (v) { return v ? Date.parse(v) : NaN; }).filter(function (v) { return !isNaN(v); });
        if (!ts.length) return { labels: [], bucketOf: function () { return null; } };
        var mn = Math.min.apply(null, ts), mx = Math.max.apply(null, ts);
        if (mn === mx) {
            var lbl = fmtDate(mn, 1);
            return { labels: [lbl], bucketOf: function (v) { return isNaN(Date.parse(v)) ? null : lbl; } };
        }
        var step = (mx - mn) / bins;
        var labels = [];
        for (var i = 0; i < bins; i++) labels.push(fmtDate(mn + i * step, step));
        return {
            labels: labels,
            bucketOf: function (v) {
                var t = Date.parse(v);
                if (isNaN(t)) return null;
                return labels[Math.min(bins - 1, Math.max(0, Math.floor((t - mn) / step)))];
            },
        };
    }

    function fmtNum(n, step) {
        var d = step > 0 ? Math.min(6, Math.max(0, Math.ceil(-Math.log10(step)) + 1)) : 2;
        return n.toFixed(d);
    }

    function fmtDate(t, step) {
        var d = new Date(t);
        var DAY = 86400000, MIN = 60000;
        if (step >= 30 * DAY) return d.toLocaleDateString('ru-RU', { year: '2-digit', month: '2-digit' });
        if (step >= DAY)      return d.toLocaleDateString('ru-RU', { year: '2-digit', month: '2-digit', day: '2-digit' });
        if (step >= MIN)      return d.toLocaleString('ru-RU', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
        return d.toLocaleString('ru-RU', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    return { init: init };
})();
