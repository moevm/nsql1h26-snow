var StatsModule = (function () {
    let progressChart = null;
    let fuelChart = null;

    const allTicks = [];

    let axisX = 'tick';
    let axisY = 'roads_cleaned_pct';
    let tickFrom = 0;
    let tickTo = Infinity;

    const AXIS_OPTIONS = {
        tick:              'Тик',
        time_min:          'Время (мин)',
        roads_cleaned_pct: 'Убрано дорог (%)',
        fuel_spent_l:      'Топливо (л)',
        snow_collected_m3: 'Снег (м\u00B3)',
        breakdowns:        'Поломки',
        efficiency:        'Эффективность',
    };

    function buildFilterUI(container) {
        if (!container) return;
        container.innerHTML = `
            <div class="stats-filters">
                <label>Ось X:
                    <select id="stats-axis-x">${_options(axisX)}</select>
                </label>
                <label>Ось Y:
                    <select id="stats-axis-y">${_options(axisY)}</select>
                </label>
                <label>Тик от:
                    <input id="stats-tick-from" type="number" value="0" min="0" style="width:60px" />
                </label>
                <label>Тик до:
                    <input id="stats-tick-to" type="number" value="" placeholder="\u221E" style="width:60px" />
                </label>
            </div>
        `;
        document.getElementById('stats-axis-x').onchange = (e) => { axisX = e.target.value; _rebuild(); };
        document.getElementById('stats-axis-y').onchange = (e) => { axisY = e.target.value; _rebuild(); };
        document.getElementById('stats-tick-from').onchange = (e) => { tickFrom = parseInt(e.target.value) || 0; _rebuild(); };
        document.getElementById('stats-tick-to').onchange = (e) => { tickTo = parseInt(e.target.value) || Infinity; _rebuild(); };
    }

    function _options(selected) {
        return Object.entries(AXIS_OPTIONS).map(([k, v]) =>
            `<option value="${k}" ${k === selected ? 'selected' : ''}>${v}</option>`
        ).join('');
    }

    function initCharts() {
        if (progressChart) { progressChart.destroy(); progressChart = null; }
        if (fuelChart) { fuelChart.destroy(); fuelChart = null; }
        allTicks.length = 0;

        const ctxP = document.getElementById('chart-progress');
        if (!ctxP) return;
        progressChart = new Chart(ctxP.getContext('2d'), {
            type: 'line',
            data: { labels: [], datasets: [{ label: AXIS_OPTIONS[axisY] || axisY, data: [], borderColor: '#a6e3a1', backgroundColor: 'rgba(166,227,161,0.15)', fill: true, tension: 0.3 }] },
            options: _chartOptions(),
        });

        const ctxF = document.getElementById('chart-fuel');
        if (!ctxF) return;
        fuelChart = new Chart(ctxF.getContext('2d'), {
            type: 'bar',
            data: { labels: [], datasets: [{ label: 'Топливо (л)', data: [], backgroundColor: '#f9e2af' }] },
            options: _chartOptions(),
        });

        buildFilterUI(document.getElementById('stats-filter-container'));
    }

    function _chartOptions() {
        return {
            responsive: true,
            plugins: { legend: { labels: { color: '#cdd6f4' } } },
            scales: {
                x: { ticks: { color: '#a6adc8' }, grid: { color: '#3a3a50' } },
                y: { ticks: { color: '#a6adc8' }, grid: { color: '#3a3a50' } },
            },
        };
    }

    function pushTick(state, stats) {
        const entry = {
            tick: state.tick,
            time_min: Math.round(state.elapsed_minutes * 10) / 10,
            roads_cleaned_pct: state.roads_cleaned_pct,
            fuel_spent_l: stats ? stats.fuel_spent_l : 0,
            snow_collected_m3: state.snow_collected_m3,
            breakdowns: stats ? stats.breakdowns : 0,
            efficiency: stats ? stats.efficiency : 0,
        };
        allTicks.push(entry);
        _rebuild();
    }

    function _rebuild() {
        const filtered = allTicks.filter(t => t.tick >= tickFrom && t.tick <= tickTo);
        const last60 = filtered.slice(-60);

        if (progressChart) {
            progressChart.data.labels = last60.map(t => t[axisX]);
            progressChart.data.datasets[0].data = last60.map(t => t[axisY]);
            progressChart.data.datasets[0].label = AXIS_OPTIONS[axisY] || axisY;
            progressChart.options.scales.x.title = { display: true, text: AXIS_OPTIONS[axisX], color: '#a6adc8' };
            progressChart.update();
        }

        if (fuelChart) {
            fuelChart.data.labels = last60.map(t => `T${t.tick}`);
            fuelChart.data.datasets[0].data = last60.map(t => t.fuel_spent_l);
            fuelChart.update();
        }
    }

    function reset() {
        allTicks.length = 0;
        tickFrom = 0;
        tickTo = Infinity;
        if (progressChart) { progressChart.data.labels = []; progressChart.data.datasets[0].data = []; progressChart.update(); }
        if (fuelChart) { fuelChart.data.labels = []; fuelChart.data.datasets[0].data = []; fuelChart.update(); }
    }

    return { initCharts, pushTick, reset, buildFilterUI };
})();
