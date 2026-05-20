var SimModule = (function () {
    let currentSimId = null;
    let autoRunInterval = null;
    const STORAGE_KEY = 'active_simulation_id';

    function simId() { return currentSimId; }
    function setSimId(id) {
        currentSimId = id || null;
        if (currentSimId) {
            localStorage.setItem(STORAGE_KEY, currentSimId);
        } else {
            localStorage.removeItem(STORAGE_KEY);
        }
    }
    function getSavedSimId() { return localStorage.getItem(STORAGE_KEY); }

    async function readJsonOrThrow(resp) {
        if (resp.ok) {
            return resp.json();
        }
        let detail = `HTTP ${resp.status}`;
        try {
            const body = await resp.json();
            detail = body.detail || detail;
        } catch (e) {}
        throw new Error(detail);
    }

    async function start(token, params, name) {
        const body = { params };
        if (name) body.name = name;
        const resp = await fetch('/api/simulation/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
            body: JSON.stringify(body),
        });
        const data = await readJsonOrThrow(resp);
        setSimId(data.id);
        return data;
    }

    async function tick(token) {
        if (!currentSimId) return null;
        const resp = await fetch(`/api/simulation/${currentSimId}/tick`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${token}` },
        });
        return readJsonOrThrow(resp);
    }

    async function pause(token) {
        if (!currentSimId) return;
        const resp = await fetch(`/api/simulation/${currentSimId}/pause`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${token}` },
        });
        await readJsonOrThrow(resp);
    }

    async function resume(token) {
        if (!currentSimId) return;
        const resp = await fetch(`/api/simulation/${currentSimId}/resume`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${token}` },
        });
        await readJsonOrThrow(resp);
    }

    async function stop(token) {
        if (!currentSimId) return;
        stopAutoRun();
        const resp = await fetch(`/api/simulation/${currentSimId}/stop`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${token}` },
        });
        await readJsonOrThrow(resp);
        setSimId(null);
    }

    async function getVehicles(token) {
        if (!currentSimId) return [];
        const resp = await fetch(`/api/simulation/${currentSimId}/vehicles`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        return readJsonOrThrow(resp);
    }

    async function getStats(token) {
        if (!currentSimId) return null;
        const resp = await fetch(`/api/statistics/${currentSimId}`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        return readJsonOrThrow(resp);
    }

    function startAutoRun(token, tickCallback, intervalMs = 300) {
        stopAutoRun();
        autoRunInterval = setInterval(async () => {
            let state = null;
            try {
                state = await tick(token);
            } catch (e) {
                stopAutoRun();
                return;
            }
            if (state && tickCallback) tickCallback(state);
            if (state && (state.status === 'finished' || state.status === 'error')) {
                stopAutoRun();
            }
        }, intervalMs);
    }

    function stopAutoRun() {
        if (autoRunInterval) { clearInterval(autoRunInterval); autoRunInterval = null; }
    }

    function leave() {
        stopAutoRun();
        setSimId(null);
    }

    return {
        simId, setSimId, getSavedSimId, start, tick, pause, resume, stop, getVehicles, getStats,
        startAutoRun, stopAutoRun, leave
    };
})();
