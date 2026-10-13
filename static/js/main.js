// Main JavaScript file for Physics Database

// Escape a value for insertion into HTML built from strings (template literals,
// innerHTML, d3 .html()). null/undefined become ''. Use it for every data value.
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Switch an inline SVG icon (rendered by the icon() template helper) to another
// symbol from the sprite in templates/_icons.svg, e.g. setIcon(el, 'sort-up').
function setIcon(svg, name) {
    const symbol = document.getElementById('i-' + name);
    if (symbol) svg.setAttribute('viewBox', symbol.getAttribute('viewBox'));
    svg.querySelector('use').setAttribute('href', '#i-' + name);
}

// Click-to-sort for a table whose headers have class "sortable" and data-column="some_name".
// A row's value comes from its data-some-name attribute, or else the text of that
// column's cell. Numbers compare as numbers; everything else (ISO dates included) as
// text. `initial` marks a sort the server already applied, e.g. {column, direction}.
function makeTableSortable(table, initial) {
    if (!table) return;
    const headers = table.querySelectorAll('.sortable');
    let current = initial || { column: null, direction: null };

    function cellValue(row, header) {
        const key = header.dataset.column.replace(/_([a-z])/g, (m, c) => c.toUpperCase());
        const cell = row.children[header.cellIndex];
        const value = (key in row.dataset ? row.dataset[key] : (cell ? cell.textContent : '')).trim();
        return value === '-' || value === 'N/A' ? '' : value;
    }

    function compare(a, b) {
        const isNumber = v => /^-?\d+(\.\d+)?$/.test(v);
        if (isNumber(a) && isNumber(b)) return Number(a) - Number(b);
        return a.localeCompare(b, undefined, { sensitivity: 'base' });
    }

    function showDirection(active, direction) {
        headers.forEach(h => {
            h.classList.remove('asc', 'desc');
            setIcon(h.querySelector('.icon'), 'sort');
        });
        active.classList.add(direction);
        setIcon(active.querySelector('.icon'), direction === 'asc' ? 'sort-up' : 'sort-down');
    }

    headers.forEach(header => {
        header.addEventListener('click', function() {
            const column = this.dataset.column;
            const direction = current.column === column && current.direction === 'asc' ? 'desc' : 'asc';
            current = { column, direction };
            const tbody = table.querySelector('tbody');
            const sign = direction === 'asc' ? 1 : -1;
            Array.from(tbody.rows)
                .sort((a, b) => sign * compare(cellValue(a, this), cellValue(b, this)))
                .forEach(row => tbody.appendChild(row));
            showDirection(this, direction);
        });
    });

    if (initial) {
        const header = table.querySelector(`.sortable[data-column="${initial.column}"]`);
        if (header) showDirection(header, initial.direction);
    }
}

// Initialize tooltips
document.addEventListener('DOMContentLoaded', function() {
    // Initialize Bootstrap tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Initialize form validation
    var forms = document.querySelectorAll('.needs-validation');
    Array.prototype.slice.call(forms).forEach(function(form) {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            form.classList.add('was-validated');
        }, false);
    });

    // Flashed success confirmations close after 5 seconds. Everything else stays until closed:
    // info, warning, and error messages, and the help boxes that are part of a page.
    setTimeout(function() {
        document.querySelectorAll('.flash-message.alert-success').forEach(function(alert) {
            new bootstrap.Alert(alert).close();
        });
    }, 5000);
});

// Global error handler
window.addEventListener('error', function(event) {
    console.error('Global error:', event.error);
});
