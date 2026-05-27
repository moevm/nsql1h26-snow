var PaginationModule = (function () {
    function create(containerId, opts) {
        var el = document.getElementById(containerId);
        if (!el) return { render: function () {} };

        var onPageChange = opts.onPageChange || function () {};
        var onPageSizeChange = opts.onPageSizeChange || function () {};
        var sizeId = containerId + '-sz';

        function render(currentPage, totalPages, total, pageSize) {
            var pages = Math.max(1, totalPages || 1);
            var info = 'Стр. ' + currentPage + ' / ' + pages;
            if (total != null) info += ' · Всего: ' + total;

            var html = '<label class="pagination-size-label">Строк:&nbsp;<input id="' + sizeId + '" type="number" value="' + pageSize + '" min="1" max="10000" /></label>';
            html += '<button data-pg="' + (currentPage - 1) + '"' + (currentPage <= 1 ? ' disabled' : '') + '>&laquo;</button>';
            var start = Math.max(1, currentPage - 2);
            var end = Math.min(pages, currentPage + 2);
            for (var i = start; i <= end; i++) {
                html += '<button data-pg="' + i + '"' + (i === currentPage ? ' class="active"' : '') + '>' + i + '</button>';
            }
            html += '<button data-pg="' + (currentPage + 1) + '"' + (currentPage >= pages ? ' disabled' : '') + '>&raquo;</button>';
            html += '<span class="pagination-info">' + info + '</span>';

            el.innerHTML = html;

            el.querySelectorAll('[data-pg]').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    onPageChange(parseInt(btn.getAttribute('data-pg'), 10));
                });
            });

            var inp = document.getElementById(sizeId);
            if (inp) {
                inp.addEventListener('change', function () {
                    var s = parseInt(inp.value, 10);
                    if (s >= 1) onPageSizeChange(s);
                });
                inp.addEventListener('keydown', function (e) {
                    if (e.key === 'Enter') inp.blur();
                });
            }
        }

        return { render: render };
    }

    return { create: create };
})();
