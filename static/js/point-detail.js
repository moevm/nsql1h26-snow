(function () {
    var params = new URLSearchParams(window.location.search);
    var pointId = params.get('id');
    var TYPE_LABELS = { parking: 'Парковка', snow_polygon: 'Снегоплавильня', service_station: 'Сервисная станция' };
    var currentData = null;
    var leafletMap = null;
    var pointMarker = null;

    function loadPoint() {
        if (!AuthModule.getToken() || !pointId) return;
        AuthModule.apiFetch('/api/objects/' + pointId)
            .then(function (res) {
                if (res.status === 404) throw new Error('Not found');
                if (!res.ok) throw new Error('HTTP ' + res.status);
                return res.json();
            })
            .then(function (p) {
                currentData = p;
                document.getElementById('point-title').textContent = p.name || ('Точка ' + p.id.substring(0, 8));
                document.getElementById('point-attrs').innerHTML = [
                    field('ID', p.id),
                    field('Название', p.name || '—'),
                    field('Тип', TYPE_LABELS[p.type] || p.type || '— (не инфраструктурная)'),
                    field('Широта', p.lat != null ? p.lat.toFixed(6) : '—'),
                    field('Долгота', p.lng != null ? p.lng.toFixed(6) : '—'),
                    field('Вместимость', p.capacity != null ? p.capacity : '—'),
                    field('Описание', p.description || '—'),
                    field('Создан', fmtDate(p.created_at)),
                ].join('');
                if (!leafletMap && p.lat && p.lng) {
                    leafletMap = L.map('point-map').setView([p.lat, p.lng], 15);
                    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap' }).addTo(leafletMap);
                    pointMarker = L.marker([p.lat, p.lng], { draggable: true }).addTo(leafletMap).bindPopup(p.name || 'Точка');
                    pointMarker.dragging.disable();
                    pointMarker.on('dragend', function (e) {
                        if (document.getElementById('edit-card').style.display === 'none') return;
                        var pos = e.target.getLatLng();
                        document.getElementById('e-lat').value = pos.lat.toFixed(6);
                        document.getElementById('e-lng').value = pos.lng.toFixed(6);
                    });
                    leafletMap.on('click', function (e) {
                        if (document.getElementById('edit-card').style.display === 'none') return;
                        document.getElementById('e-lat').value = e.latlng.lat.toFixed(6);
                        document.getElementById('e-lng').value = e.latlng.lng.toFixed(6);
                        if (pointMarker) pointMarker.setLatLng(e.latlng);
                    });
                } else if (leafletMap && pointMarker && p.lat && p.lng) {
                    pointMarker.setLatLng([p.lat, p.lng]);
                }
            })
            .catch(function (err) {
                document.getElementById('point-title').textContent = err.message === 'Not found' ? 'Точка не найдена' : 'Ошибка загрузки';
            });
    }

    document.getElementById('btn-edit').addEventListener('click', function () {
        if (!currentData) return;
        document.getElementById('e-name').value = currentData.name || '';
        document.getElementById('e-type').value = currentData.type || '';
        document.getElementById('e-lat').value = currentData.lat || '';
        document.getElementById('e-lng').value = currentData.lng || '';
        document.getElementById('e-capacity').value = currentData.capacity != null ? currentData.capacity : '';
        document.getElementById('e-desc').value = currentData.description || '';
        document.getElementById('view-card').style.display = 'none';
        document.getElementById('edit-card').style.display = '';
        if (pointMarker) pointMarker.dragging.enable();
    });

    document.getElementById('btn-cancel-edit').addEventListener('click', function () {
        document.getElementById('view-card').style.display = '';
        document.getElementById('edit-card').style.display = 'none';
        if (pointMarker) {
            pointMarker.dragging.disable();
            pointMarker.setLatLng([currentData.lat, currentData.lng]);
        }
    });

    document.getElementById('btn-save').addEventListener('click', function () {
        var updates = {
            name: document.getElementById('e-name').value.trim() || null,
            type: document.getElementById('e-type').value || null,
            lat: parseFloat(document.getElementById('e-lat').value),
            lng: parseFloat(document.getElementById('e-lng').value),
            capacity: document.getElementById('e-capacity').value ? parseInt(document.getElementById('e-capacity').value) : null,
            description: document.getElementById('e-desc').value.trim() || null,
        };
        AuthModule.apiFetch('/api/objects/' + pointId, { method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify(updates) })
            .then(function (res) {
                if (!res.ok) throw new Error('HTTP ' + res.status);
                document.getElementById('view-card').style.display = '';
                document.getElementById('edit-card').style.display = 'none';
                if (pointMarker) pointMarker.dragging.disable();
                loadPoint();
            })
            .catch(function () { alert('Ошибка сохранения'); });
    });

    document.getElementById('btn-delete').addEventListener('click', function () {
        if (!confirm('Удалить точку?')) return;
        AuthModule.apiFetch('/api/objects/' + pointId, { method: 'DELETE' })
            .then(function () { window.location.href = '/static/points.html'; })
            .catch(function () { alert('Ошибка удаления'); });
    });

    function field(label, value) { return '<div class="field"><span>' + esc(label) + '</span><span class="value">' + esc(String(value != null ? value : '—')) + '</span></div>'; }
    function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
    function fmtDate(d) { if (!d) return '—'; return new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }); }

    if (AuthModule.getToken()) loadPoint();
})();
