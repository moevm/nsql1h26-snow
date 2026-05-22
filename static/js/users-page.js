(function () {
    function buildQuery() {
        var p = [];
        var userId = document.getElementById('f-id').value.trim();
        var name = document.getElementById('f-name').value.trim();
        var role = document.getElementById('f-role').value;
        var createdFrom = document.getElementById('f-created-from').value;
        var createdTo = document.getElementById('f-created-to').value;
        var updFrom = document.getElementById('f-upd-from').value;
        var updTo = document.getElementById('f-upd-to').value;
        if (userId) p.push('user_id=' + encodeURIComponent(userId));
        if (name) p.push('name=' + encodeURIComponent(name));
        if (role) p.push('role=' + encodeURIComponent(role));
        if (createdFrom) p.push('created_at_from=' + encodeURIComponent(createdFrom));
        if (createdTo) p.push('created_at_to=' + encodeURIComponent(createdTo));
        if (updFrom) p.push('updated_at_from=' + encodeURIComponent(updFrom));
        if (updTo) p.push('updated_at_to=' + encodeURIComponent(updTo));
        return p.length ? '?' + p.join('&') : '';
    }

    function loadUsers() {
        if (!AuthModule.getToken()) return;
        showLoading(true);
        var url = '/api/users/' + buildQuery();
        AuthModule.apiFetch(url)
            .then(function (res) { if (!res.ok) throw new Error('HTTP ' + res.status); return res.json(); })
            .then(function (data) { render(data); showLoading(false); })
            .catch(function () { showLoading(false); });
    }

    function render(users) {
        var tbody = document.getElementById('users-tbody');
        var table = document.getElementById('users-table');
        var empty = document.getElementById('empty-state');
        var count = document.getElementById('result-count');
        if (count) count.textContent = 'Найдено: ' + users.length;
        if (!users.length) { table.style.display = 'none'; empty.style.display = ''; return; }
        table.style.display = ''; empty.style.display = 'none';
        tbody.innerHTML = users.map(function (u) {
            var detailUrl = '/static/user-detail.html?id=' + encodeURIComponent(u.id);
            return '<tr onclick="window.location=\'' + detailUrl + '\'" style="cursor:pointer">'
                + '<td>' + u.id + '</td>'
                + '<td>' + esc(u.name) + '</a></td>'
                + '<td>' + esc(u.role || 'operator') + '</td>'
                + '<td>' + fmtDate(u.created_at) + '</td>'
                + '<td>' + fmtDate(u.updated_at) + '</td>'
                + '<td style="display:flex;gap:4px">'
                + '<button class="btn-red" style="padding:2px 8px;font-size:0.8rem" onclick="deleteUser(\'' + u.id + '\')">✕</button>'
                + '</td>'
                + '</tr>';
        }).join('');
    }

    window.deleteUser = function (id) {
        if (!confirm('Удалить пользователя?')) return;
        AuthModule.apiFetch('/api/users/' + id, { method: 'DELETE' })
            .then(function () { loadUsers(); })
            .catch(function () { alert('Ошибка удаления'); });
    };

    document.getElementById('btn-create').addEventListener('click', function () {
        document.getElementById('modal-create').style.display = 'flex';
    });
    document.getElementById('btn-cancel-create').addEventListener('click', function () {
        document.getElementById('modal-create').style.display = 'none';
    });
    document.getElementById('btn-save-create').addEventListener('click', function () {
        var body = {
            name: document.getElementById('c-name').value.trim(),
            role: document.getElementById('c-role').value,
            password: document.getElementById('c-password').value
        };
        if (!body.name || !body.password) { alert('Введите имя и пароль'); return; }
        AuthModule.apiFetch('/api/users/', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) })
            .then(function (res) {
                if (!res.ok) return res.text().then(function(t){throw new Error(t);});
                document.getElementById('modal-create').style.display = 'none';
                document.getElementById('c-name').value = '';
                document.getElementById('c-password').value = '';
                loadUsers();
            })
            .catch(function (err) { alert('Ошибка: ' + (err.message || err)); });
    });

    document.getElementById('btn-filter').addEventListener('click', function () { loadUsers(); });
    document.getElementById('btn-reset').addEventListener('click', function () {
        ['f-id','f-name','f-created-from','f-created-to','f-upd-from','f-upd-to'].forEach(function(id) { var e = document.getElementById(id); if (e) e.value = ''; });
        var roleEl = document.getElementById('f-role'); if (roleEl) roleEl.selectedIndex = 0;
        loadUsers();
    });

    function esc(s) { return s ? String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;') : ''; }
    function fmtDate(d) { if (!d) return '—'; return new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }); }
    function showLoading(s) { var e = document.getElementById('loading'); if (e) e.style.display = s ? '' : 'none'; }

    if (AuthModule.getToken()) loadUsers();
})();
