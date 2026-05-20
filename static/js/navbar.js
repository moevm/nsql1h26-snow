var NavbarModule = (function () {
    var PAGES = [
        { href: '/static/index.html', label: 'Карта', alias: '/' },
        { href: '/static/routes.html', label: 'Маршруты' },
        { href: '/static/points.html', label: 'Точки' },
        { href: '/static/simulations.html', label: 'Симуляции' },
        { href: '/static/simulation-steps.html', label: 'Шаги' },
        { href: '/static/vehicle-states.html', label: 'Машины' },
        { href: '/static/users.html', label: 'Пользователи' },
    ];

    function buildNavLinks() {
        var path = window.location.pathname;
        return PAGES.map(function (p) {
            var isActive = path === p.href || (p.alias && path === p.alias);
            return '<a href="' + p.href + '"' + (isActive ? ' class="active"' : '') + '>' + p.label + '</a>';
        }).join('');
    }

    function renderLoggedOut(container) {
        container.innerHTML = '<header class="header">'
            + '<h1>Уборка снега — СПб</h1>'
            + '<nav class="navbar">' + buildNavLinks() + '</nav>'
            + '<div id="ie-section" style="display:flex;gap:6px;align-items:center"></div>'
            + '<div id="auth-section">'
            + '<input id="username" type="text" placeholder="Логин" value="admin" />'
            + '<input id="password" type="password" placeholder="Пароль" value="admin" />'
            + '<button id="btn-login">Войти</button>'
            + '<span id="auth-status"></span>'
            + '</div>'
            + '</header>';

        var loginBtn = document.getElementById('btn-login');
        if (loginBtn) {
            loginBtn.addEventListener('click', function () {
                var u = document.getElementById('username').value;
                var p = document.getElementById('password').value;
                AuthModule.login(u, p)
                    .then(function () { window.location.reload(); })
                    .catch(function () { document.getElementById('auth-status').textContent = '✗ ошибка'; });
            });
        }
    }

    function bindImportExport() {
        var exportBtn = document.getElementById('btn-export');
        if (exportBtn) {
            exportBtn.addEventListener('click', function () {
                AuthModule.apiFetch('/api/data/export')
                    .then(function (res) {
                        if (!res.ok) throw new Error('HTTP ' + res.status);
                        return res.text();
                    })
                    .then(function (text) {
                        var blob = new Blob([text], { type: 'application/json' });
                        var a = document.createElement('a');
                        a.href = URL.createObjectURL(blob);
                        a.download = 'neo4j_export.json';
                        a.click();
                        URL.revokeObjectURL(a.href);
                    })
                    .catch(function (err) { alert('Ошибка экспорта: ' + (err.message || err)); });
            });
        }

        var importFile = document.getElementById('import-file');
        if (importFile) {
            importFile.addEventListener('change', function (e) {
                var file = e.target.files[0];
                if (!file) return;
                var reader = new FileReader();
                reader.onload = function (evt) {
                    var raw = evt.target.result;
                    AuthModule.apiFetch('/api/data/import', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/octet-stream' },
                        body: raw,
                    })
                        .then(function (res) { return res.json(); })
                        .then(function (r) {
                            var imp = r.imported || {};
                            alert('Импорт завершён.\nУзлов: ' + (imp.nodes || 0) + '\nСвязей: ' + (imp.relationships || 0));
                        })
                        .catch(function () { alert('Ошибка импорта'); });
                };
                reader.readAsText(file, 'utf-8');
                importFile.value = '';
            });
        }
    }

    function renderLoggedIn(container) {
        var user = AuthModule.getUser();
        var importExportHTML = '<button id="btn-export" style="font-size:0.8rem;padding:3px 8px;background:var(--green);color:var(--bg);border-radius:8px;font-weight:600;cursor:pointer;border:none">Экспорт</button>'
            + '<label style="font-size:0.8rem;cursor:pointer"><input id="import-file" type="file" accept=".json" style="display:none" /><span style="padding:3px 8px;background:var(--yellow);color:var(--bg);border-radius:8px;font-weight:600;cursor:pointer">Импорт</span></label>';
        var authHTML = '<span id="auth-status" style="color:var(--green);font-size:0.85rem;">✓ ' + (user || 'user') + '</span>'
            + ' <button id="btn-logout" style="font-size:0.8rem;padding:3px 8px;">Выйти</button>';

        container.innerHTML = '<header class="header">'
            + '<h1>Уборка снега — СПб</h1>'
            + '<nav class="navbar">' + buildNavLinks() + '</nav>'
            + '<div id="ie-section" style="display:flex;gap:6px;align-items:center">' + importExportHTML + '</div>'
            + '<div id="auth-section">' + authHTML + '</div>'
            + '</header>';

        var logoutBtn = document.getElementById('btn-logout');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', function () { AuthModule.logout(); });
        }
        bindImportExport();
    }

    function renderLoading(container) {
        container.innerHTML = '<header class="header">'
            + '<h1>Уборка снега — СПб</h1>'
            + '<nav class="navbar">' + buildNavLinks() + '</nav>'
            + '<div id="ie-section" style="display:flex;gap:6px;align-items:center"></div>'
            + '<div id="auth-section"><span id="auth-status" style="font-size:0.85rem;color:var(--text-dim)">Проверка сессии…</span></div>'
            + '</header>';
    }

    function init() {
        var container = document.getElementById('app-header');
        if (!container) return;

        if (!AuthModule.getToken()) {
            renderLoggedOut(container);
            return;
        }

        renderLoading(container);
        AuthModule.ensureSession().then(function (session) {
            if (session) {
                renderLoggedIn(container);
            } else {
                renderLoggedOut(container);
            }
        });
    }

    window.addEventListener('auth:invalid', function () {
        init();
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    return { init: init };
})();
