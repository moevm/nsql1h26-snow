var SortModule = (function () {
    function create(tableId, columns, onSortChange) {
        var table = document.getElementById(tableId);
        if (!table) return null;

        var params = new URLSearchParams(window.location.search);
        var sortBy = params.get('sort_by') || '';
        var sortOrder = params.get('sort_order') || 'desc';

        var state = {
            sortBy: columns.find(function (c) { return c.sort_key === sortBy; }) ? sortBy : '',
            sortOrder: sortOrder === 'asc' ? 'asc' : 'desc'
        };

        function updateUrl() {
            var url = new URL(window.location);
            if (state.sortBy) {
                url.searchParams.set('sort_by', state.sortBy);
                url.searchParams.set('sort_order', state.sortOrder);
            } else {
                url.searchParams.delete('sort_by');
                url.searchParams.delete('sort_order');
            }
            history.replaceState(null, '', url);
        }

        function updateArrows() {
            var ths = table.querySelectorAll('thead th');
            columns.forEach(function (col) {
                var th = ths[col.th_index];
                if (!th) return;
                // Remove existing arrow spans
                var arrows = th.querySelectorAll('.sort-arrow');
                arrows.forEach(function (a) { a.remove(); });
                if (state.sortBy === col.sort_key) {
                    var span = document.createElement('span');
                    span.className = 'sort-arrow';
                    span.textContent = state.sortOrder === 'asc' ? ' ▲' : ' ▼';
                    th.appendChild(span);
                    th.classList.add('sort-active');
                } else {
                    th.classList.remove('sort-active');
                }
            });
        }

        function handleClick(col) {
            if (state.sortBy === col.sort_key) {
                state.sortOrder = state.sortOrder === 'asc' ? 'desc' : 'asc';
            } else {
                state.sortBy = col.sort_key;
                state.sortOrder = 'asc';
            }
            updateUrl();
            updateArrows();
            if (typeof onSortChange === 'function') {
                onSortChange(state.sortBy, state.sortOrder);
            }
        }

        // Attach click handlers to th elements
        columns.forEach(function (col) {
            var ths = table.querySelectorAll('thead th');
            var th = ths[col.th_index];
            if (!th) return;
            th.classList.add('sortable');
            th.addEventListener('click', function () { handleClick(col); });
        });

        updateArrows();

        return {
            getSortBy: function () { return state.sortBy; },
            getSortOrder: function () { return state.sortOrder; }
        };
    }

    return { create: create };
})();