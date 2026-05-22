(function () {
    var params = new URLSearchParams(window.location.search);
    var userId = params.get('id');
    var currentData = null;

    function loadUser() {
        if (!AuthModule.getToken() || !userId) return;
        AuthModule.apiFetch('/api/users/' + userId)
            .then(function (res) {
                if (res.status === 404) throw new Error('Not found');
                if (!res.ok) throw new Error('HTTP ' + res.status);
                return res.json();
            })
            .then(function (u) {
                currentData = u;
                document.getElementById('user-title').textContent = u.name || 'Пользователь';
                document.getElementById('user-attrs').innerHTML = [
                    field('ID', u.id),
                    field('Имя', u.name),
                    field('Роль', u.role || 'operator'),
                    field('Создан', fmtDate(u.created_at)),
                    field('Изменён', fmtDate(u.updated_at)),
                ].join('');
            })
            .catch(function (err) {
                document.getElementById('user-title').textContent =
                    err.message === 'Not found' ? 'Пользователь не найден' : 'Ошибка загрузки';
            });
    }

    function showPanel(name) {
        ['view-card', 'edit-card', 'password-card'].forEach(function (id) {
            document.getElementById(id).style.display = id === name ? '' : 'none';
        });
    }

    document.getElementById('btn-edit').addEventListener('click', function () {
        if (!currentData) return;
        document.getElementById('e-name').value = currentData.name || '';
        document.getElementById('e-role').value = currentData.role || 'operator';
        showPanel('edit-card');
    });

    document.getElementById('btn-cancel-edit').addEventListener('click', function () {
        showPanel('view-card');
    });

    document.getElementById('btn-save').addEventListener('click', function () {
        var name = document.getElementById('e-name').value.trim();
        var role = document.getElementById('e-role').value;
        if (!name) { alert('Имя не может быть пустым'); return; }
        AuthModule.apiFetch('/api/users/' + userId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: name, role: role }),
        })
            .then(function (res) {
                if (!res.ok) throw new Error('HTTP ' + res.status);
                showPanel('view-card');
                loadUser();
            })
            .catch(function () { alert('Ошибка сохранения'); });
    });

    document.getElementById('btn-change-password').addEventListener('click', function () {
        document.getElementById('p-new').value = '';
        document.getElementById('p-confirm').value = '';
        document.getElementById('p-error').style.display = 'none';
        showPanel('password-card');
    });

    document.getElementById('btn-cancel-password').addEventListener('click', function () {
        showPanel('view-card');
    });

    document.getElementById('btn-save-password').addEventListener('click', function () {
        var newPwd = document.getElementById('p-new').value;
        var confirm = document.getElementById('p-confirm').value;
        var errEl = document.getElementById('p-error');
        errEl.style.display = 'none';
        if (!newPwd) { errEl.textContent = 'Введите новый пароль'; errEl.style.display = ''; return; }
        if (newPwd !== confirm) { errEl.textContent = 'Пароли не совпадают'; errEl.style.display = ''; return; }
        AuthModule.apiFetch('/api/users/' + userId, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: newPwd }),
        })
            .then(function (res) {
                if (!res.ok) throw new Error('HTTP ' + res.status);
                showPanel('view-card');
            })
            .catch(function () { alert('Ошибка смены пароля'); });
    });

    document.getElementById('btn-delete').addEventListener('click', function () {
        if (!confirm('Удалить пользователя?')) return;
        AuthModule.apiFetch('/api/users/' + userId, { method: 'DELETE' })
            .then(function () { window.location.href = '/static/users.html'; })
            .catch(function () { alert('Ошибка удаления'); });
    });

    function field(label, value) {
        return '<div class="field"><span>' + label + '</span><span class="value">' + esc(value != null ? String(value) : '—') + '</span></div>';
    }
    function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
    function fmtDate(d) { if (!d) return '—'; return new Date(d).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' }); }

    if (AuthModule.getToken()) loadUser();
})();
