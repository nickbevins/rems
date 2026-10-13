// Shared behavior for the Equipment List and Capital Planning pages:
// filter auto-submit, multi-level column sorting kept in the URL, the cascading
// subclass filter, double-click to open a row, and drag-to-reorder columns.
// Needs Sortable.min.js. Each page calls initListPage() with its own options.

let listColumnManager = null;

function initListPage({ columnOrderKey, detailParams = {} }) {
    document.addEventListener('DOMContentLoaded', function() {
        initFilters();
        initRowDoubleClick(detailParams);
        initMultiSort();
        initSubclassFilter();
        if (document.getElementById('equipmentTable')) {
            listColumnManager = new ColumnReorderManager('equipmentTable', columnOrderKey);
        }
    });
}

function initFilters() {
    const filterForm = document.getElementById('filterForm');
    document.querySelectorAll('.auto-filter').forEach(element => {
        element.addEventListener('change', () => filterForm.submit());
    });

    // Search on Enter
    const searchInput = document.getElementById('search');
    if (searchInput) {
        searchInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter') filterForm.submit();
        });
    }
}

// Double-click a row to open the equipment, keeping the current filters
function initRowDoubleClick(detailParams) {
    document.querySelectorAll('.equipment-row').forEach(row => {
        row.addEventListener('dblclick', function(e) {
            if (e.target.closest('.btn-group')) return;  // not on the action buttons

            const params = new URLSearchParams(window.location.search);
            Object.entries(detailParams).forEach(([key, value]) => params.set(key, value));
            window.location.href = `/equipment/${this.getAttribute('data-eq-id')}?${params.toString()}`;
        });
    });
}

// Clicking a header adds it as the top sort level (up to 3); clicking again
// flips it to descending, and a third click removes it. The server sorts.
function initMultiSort() {
    const MAX_SORT_LEVELS = 3;
    const urlParams = new URLSearchParams(window.location.search);
    const sortFields = (urlParams.get('sort') || '').split(',').filter(Boolean);
    const sortOrders = (urlParams.get('order') || '').split(',');
    let sortStack = sortFields.map((field, i) => ({ field: field, order: sortOrders[i] || 'asc' }));

    const sortableHeaders = document.querySelectorAll('.sortable');
    sortableHeaders.forEach(header => {
        header.addEventListener('click', function() {
            const sortField = this.getAttribute('data-sort');
            const existingIndex = sortStack.findIndex(sort => sort.field === sortField);

            if (existingIndex === -1) {
                sortStack.unshift({ field: sortField, order: 'asc' });
                sortStack = sortStack.slice(0, MAX_SORT_LEVELS);
            } else if (sortStack[existingIndex].order === 'asc') {
                sortStack[existingIndex].order = 'desc';
            } else {
                sortStack.splice(existingIndex, 1);
            }

            const url = new URL(window.location);
            if (sortStack.length === 0) {
                url.searchParams.delete('sort');
                url.searchParams.delete('order');
            } else {
                url.searchParams.set('sort', sortStack.map(sort => sort.field).join(','));
                url.searchParams.set('order', sortStack.map(sort => sort.order).join(','));
            }
            url.searchParams.set('page', '1');
            window.location.href = url.toString();
        });
    });

    // Show the direction on each sorted column, numbered when there are several levels
    sortStack.forEach((sort, index) => {
        const header = document.querySelector(`.sortable[data-sort="${sort.field}"]`);
        if (!header) return;
        header.classList.add(sort.order);
        setIcon(header.querySelector('.icon'), sort.order === 'asc' ? 'sort-up' : 'sort-down');
        if (sortStack.length > 1) {
            const badge = document.createElement('span');
            badge.className = 'sort-level-badge badge bg-primary ms-1';
            badge.textContent = index + 1;
            badge.style.fontSize = '10px';
            badge.title = `Sort level ${index + 1}`;
            header.appendChild(badge);
        }
    });
}

// Limit the subclass dropdown to the selected class
function initSubclassFilter() {
    const classSelect = document.getElementById('eq_class');
    const subclassSelect = document.getElementById('eq_subclass');
    if (!classSelect || !subclassSelect) return;
    const currentSubclass = new URLSearchParams(window.location.search).get('eq_subclass') || '';

    function updateSubclasses() {
        const selectedClass = classSelect.value;
        const url = selectedClass ? '/api/subclasses?eq_class=' + encodeURIComponent(selectedClass) : '/api/subclasses';
        fetch(url)
            .then(response => response.json())
            .then(subclasses => {
                subclassSelect.innerHTML = '<option value="">All Subclasses</option>';
                subclasses.forEach(subclass => {
                    const option = document.createElement('option');
                    option.value = subclass;
                    option.textContent = subclass;
                    option.selected = subclass === currentSubclass;
                    subclassSelect.appendChild(option);
                });
            })
            .catch(error => console.error('Error loading subclasses:', error));
    }

    classSelect.addEventListener('change', function() {
        updateSubclasses();
        subclassSelect.value = '';
    });
    if (classSelect.value) updateSubclasses();
}

// "Clear" button: drop every filter by reloading without query parameters
function clearFilters() {
    window.location.href = window.location.pathname;
}

// "Reset Columns" button
function resetColumnOrder() {
    if (listColumnManager && confirm('Reset column order to default? This will reload the page.')) {
        listColumnManager.resetColumnOrder();
    }
}

// Drag-to-reorder table columns; the order is saved per page in localStorage
class ColumnReorderManager {
    constructor(tableId, storageKey) {
        this.table = document.getElementById(tableId);
        this.storageKey = storageKey;
        this.headerRow = document.getElementById(tableId + 'Header');
        if (!this.table || !this.headerRow) return;

        this.loadColumnOrder();
        this.sortable = Sortable.create(this.headerRow, {
            animation: 150,
            ghostClass: 'sortable-ghost',
            chosenClass: 'sortable-chosen',
            dragClass: 'sortable-drag',
            onEnd: (evt) => {
                this.moveBodyCells(evt.oldIndex, evt.newIndex);
                this.saveColumnOrder();
            }
        });
        this.headerRow.querySelectorAll('th').forEach(header => {
            if (!header.innerHTML.includes('Actions')) {
                header.style.cursor = 'move';
                header.title = header.title || header.textContent.trim() + ' - Drag to reorder columns';
                header.classList.add('draggable-header');
            }
        });
    }

    columnId(th) {
        return th.getAttribute('data-sort') || th.textContent.trim().toLowerCase().replace(/\s+/g, '_');
    }

    moveBodyCells(oldIndex, newIndex) {
        const tbody = this.table.querySelector('tbody');
        if (!tbody) return;
        tbody.querySelectorAll('tr').forEach(row => {
            const cells = Array.from(row.children);
            if (newIndex >= cells.length) {
                row.appendChild(cells[oldIndex]);
            } else {
                row.insertBefore(cells[oldIndex], cells[newIndex]);
            }
        });
    }

    saveColumnOrder() {
        const order = Array.from(this.headerRow.children).map(th => this.columnId(th));
        try {
            localStorage.setItem(this.storageKey, JSON.stringify(order));
        } catch (e) { /* storage unavailable: the order just isn't remembered */ }
    }

    loadColumnOrder() {
        let order;
        try {
            order = JSON.parse(localStorage.getItem(this.storageKey));
        } catch (e) {
            return;
        }
        if (!Array.isArray(order)) return;

        const headers = Array.from(this.headerRow.children);
        const currentOrder = headers.map(th => this.columnId(th));
        order.forEach((colId, newIndex) => {
            const currentIndex = currentOrder.indexOf(colId);
            if (currentIndex === -1 || currentIndex === newIndex) return;
            const header = headers[currentIndex];
            if (newIndex >= this.headerRow.children.length) {
                this.headerRow.appendChild(header);
            } else {
                this.headerRow.insertBefore(header, this.headerRow.children[newIndex]);
            }
            this.moveBodyCells(currentIndex, newIndex);
        });
    }

    resetColumnOrder() {
        try {
            localStorage.removeItem(this.storageKey);
        } catch (e) { /* nothing saved */ }
        location.reload();
    }
}
