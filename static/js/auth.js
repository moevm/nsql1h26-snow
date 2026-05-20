var AuthModule = (function () {
    var TOKEN_KEY = 'snow_token';
    var USER_KEY = 'snow_user';
    var verifyPromise = null;

    function getToken() {
        return localStorage.getItem(TOKEN_KEY);
    }

    function getUser() {
        return localStorage.getItem(USER_KEY);
    }

    function setToken(token, username) {
        localStorage.setItem(TOKEN_KEY, token);
        if (username) localStorage.setItem(USER_KEY, username);
    }

    function clearToken() {
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
        verifyPromise = null;
    }

    function notifyInvalidSession() {
        window.dispatchEvent(new CustomEvent('auth:invalid'));
    }

    function login(username, password) {
        return fetch('/api/auth/token', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: username, password: password }),
        })
            .then(function (resp) {
                if (!resp.ok) throw new Error('Auth failed');
                return resp.json();
            })
            .then(function (data) {
                setToken(data.access_token, username);
                verifyPromise = null;
                return data.access_token;
            });
    }

    function logout() {
        clearToken();
        window.location.reload();
    }

    function authHeaders(extra) {
        var token = getToken();
        var h = {};
        if (extra) {
            for (var k in extra) h[k] = extra[k];
        }
        if (token) h['Authorization'] = 'Bearer ' + token;
        return h;
    }

    function apiFetch(url, options) {
        options = options || {};
        options.headers = authHeaders(options.headers);
        return fetch(url, options).then(function (resp) {
            if (resp.status === 401 || resp.status === 403) {
                clearToken();
                notifyInvalidSession();
            }
            return resp;
        });
    }

    function ensureSession() {
        var token = getToken();
        if (!token) return Promise.resolve(null);
        if (verifyPromise) return verifyPromise;
        verifyPromise = fetch('/api/auth/me', {
            headers: { Authorization: 'Bearer ' + token }
        })
            .then(function (resp) {
                if (!resp.ok) {
                    clearToken();
                    notifyInvalidSession();
                    return null;
                }
                return resp.json();
            })
            .then(function (data) {
                if (!data || !data.username) return null;
                setToken(token, data.username);
                return data;
            })
            .catch(function () {
                clearToken();
                notifyInvalidSession();
                return null;
            })
            .finally(function () {
                verifyPromise = null;
            });
        return verifyPromise;
    }

    return {
        getToken: getToken,
        getUser: getUser,
        setToken: setToken,
        clearToken: clearToken,
        login: login,
        logout: logout,
        authHeaders: authHeaders,
        apiFetch: apiFetch,
        ensureSession: ensureSession,
    };
})();
