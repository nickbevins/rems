// Main JavaScript file for Physics Database

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
    
    // Auto-hide alerts after 5 seconds
    setTimeout(function() {
        var alerts = document.querySelectorAll('.alert');
        alerts.forEach(function(alert) {
            if (alert.classList.contains('alert-success') || alert.classList.contains('alert-info')) {
                var bsAlert = new bootstrap.Alert(alert);
                bsAlert.close();
            }
        });
    }, 5000);
});

// Utility functions
function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString();
}

function formatCurrency(amount) {
    if (!amount) return 'N/A';
    return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD'
    }).format(amount);
}

function calculateDaysUntil(dateString) {
    if (!dateString) return null;
    const targetDate = new Date(dateString);
    const today = new Date();
    const timeDiff = targetDate.getTime() - today.getTime();
    return Math.ceil(timeDiff / (1000 * 3600 * 24));
}

function calculateDaysOverdue(dateString) {
    if (!dateString) return null;
    const targetDate = new Date(dateString);
    const today = new Date();
    const timeDiff = today.getTime() - targetDate.getTime();
    return Math.ceil(timeDiff / (1000 * 3600 * 24));
}

// Equipment search and filter functions
function filterEquipment() {
    const searchTerm = document.getElementById('equipment-search')?.value.toLowerCase();
    const classFilter = document.getElementById('class-filter')?.value;
    const statusFilter = document.getElementById('status-filter')?.value;
    
    const tableRows = document.querySelectorAll('#equipment-table tbody tr');
    
    tableRows.forEach(row => {
        const cells = row.cells;
        const equipmentText = Array.from(cells).map(cell => cell.textContent.toLowerCase()).join(' ');
        const equipmentClass = cells[1]?.textContent.trim();
        const equipmentStatus = cells[8]?.textContent.trim();
        
        let showRow = true;
        
        // Search filter
        if (searchTerm && !equipmentText.includes(searchTerm)) {
            showRow = false;
        }
        
        // Class filter
        if (classFilter && equipmentClass !== classFilter) {
            showRow = false;
        }
        
        // Status filter
        if (statusFilter && equipmentStatus !== statusFilter) {
            showRow = false;
        }
        
        row.style.display = showRow ? '' : 'none';
    });
}

// Dashboard functions
function loadDashboardData() {
    fetch('/api/equipment')
        .then(response => response.json())
        .then(data => {
            updateDashboardStats(data);
            updateDashboardCharts(data);
        })
        .catch(error => {
            console.error('Error loading dashboard data:', error);
        });
}

function updateDashboardStats(equipment) {
    const totalEquipment = equipment.length;
    const activeEquipment = equipment.filter(eq => !eq.eq_retired).length;
    const retiredEquipment = equipment.filter(eq => eq.eq_retired).length;
    
    // Update stats cards
    document.getElementById('total-equipment').textContent = totalEquipment;
    document.getElementById('active-equipment').textContent = activeEquipment;
    document.getElementById('retired-equipment').textContent = retiredEquipment;
}

function updateDashboardCharts(equipment) {
    // Equipment by class chart
    const classData = {};
    equipment.forEach(eq => {
        if (!eq.eq_retired && eq.eq_class) {
            classData[eq.eq_class] = (classData[eq.eq_class] || 0) + 1;
        }
    });
    
    createChart('equipment-class-chart', 'Equipment by Class', classData);
    
    // Equipment by facility chart
    const facilityData = {};
    equipment.forEach(eq => {
        if (!eq.eq_retired && eq.eq_fac) {
            facilityData[eq.eq_fac] = (facilityData[eq.eq_fac] || 0) + 1;
        }
    });
    
    createChart('equipment-facility-chart', 'Equipment by Facility', facilityData);
}

function createChart(canvasId, title, data) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    
    const ctx = canvas.getContext('2d');
    
    // Clear existing chart
    if (canvas.chart) {
        canvas.chart.destroy();
    }
    
    canvas.chart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: Object.keys(data),
            datasets: [{
                data: Object.values(data),
                backgroundColor: [
                    '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF',
                    '#FF9F40', '#FF6384', '#C9CBCF', '#4BC0C0', '#FF6384'
                ]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                },
                title: {
                    display: true,
                    text: title
                }
            }
        }
    });
}

// Form helpers
function populateSelectFromAPI(selectId, apiUrl, valueField, textField) {
    fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
            const select = document.getElementById(selectId);
            if (!select) return;
            
            // Clear existing options except the first one
            while (select.children.length > 1) {
                select.removeChild(select.lastChild);
            }
            
            // Add new options
            data.forEach(item => {
                const option = document.createElement('option');
                option.value = item[valueField];
                option.textContent = item[textField];
                select.appendChild(option);
            });
        })
        .catch(error => {
            console.error('Error populating select:', error);
        });
}

// Export functions
function exportToCSV(tableId, filename) {
    const table = document.getElementById(tableId);
    if (!table) return;
    
    const csv = [];
    const rows = table.querySelectorAll('tr');
    
    rows.forEach(row => {
        const cells = row.querySelectorAll('td, th');
        const rowData = Array.from(cells).map(cell => {
            return '"' + cell.textContent.replace(/"/g, '""') + '"';
        });
        csv.push(rowData.join(','));
    });
    
    const csvContent = csv.join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    
    const a = document.createElement('a');
    a.href = url;
    a.download = filename || 'export.csv';
    a.click();
    
    window.URL.revokeObjectURL(url);
}

// Compliance helpers
function updateComplianceStatus(equipmentId, testType, status) {
    fetch('/api/compliance/update', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            equipment_id: equipmentId,
            test_type: testType,
            status: status
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('Error updating compliance status');
        }
    })
    .catch(error => {
        console.error('Error updating compliance status:', error);
        alert('Error updating compliance status');
    });
}

// Print functions
function printPage() {
    window.print();
}

function printElement(elementId) {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    const printWindow = window.open('', '_blank');
    printWindow.document.write(`
        <html>
            <head>
                <title>Print</title>
                <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
                <style>
                    body { font-size: 12px; }
                    .btn, .pagination, .card-header { display: none !important; }
                    .card { border: none; box-shadow: none; }
                </style>
            </head>
            <body>
                ${element.innerHTML}
            </body>
        </html>
    `);
    printWindow.document.close();
    printWindow.print();
}

// Local storage helpers
function saveToLocalStorage(key, value) {
    try {
        localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
        console.error('Error saving to localStorage:', error);
    }
}

function loadFromLocalStorage(key, defaultValue = null) {
    try {
        const value = localStorage.getItem(key);
        return value ? JSON.parse(value) : defaultValue;
    } catch (error) {
        console.error('Error loading from localStorage:', error);
        return defaultValue;
    }
}

// Auto-save form data
function enableAutoSave(formId) {
    const form = document.getElementById(formId);
    if (!form) return;
    
    const inputs = form.querySelectorAll('input, select, textarea');
    inputs.forEach(input => {
        input.addEventListener('input', function() {
            const formData = new FormData(form);
            const data = {};
            for (let [key, value] of formData.entries()) {
                data[key] = value;
            }
            saveToLocalStorage(`autosave_${formId}`, data);
        });
    });
    
    // Load saved data on page load
    const savedData = loadFromLocalStorage(`autosave_${formId}`);
    if (savedData) {
        Object.keys(savedData).forEach(key => {
            const input = form.querySelector(`[name="${key}"]`);
            if (input) {
                input.value = savedData[key];
            }
        });
    }
}

// Clear autosave data when form is submitted
document.addEventListener('DOMContentLoaded', function() {
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function() {
            localStorage.removeItem(`autosave_${form.id}`);
        });
    });
});

// Global error handler
window.addEventListener('error', function(event) {
    console.error('Global error:', event.error);
    // You can add error reporting here
});

// Service worker registration (for offline functionality)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/sw.js')
            .then(registration => {
                console.log('SW registered: ', registration);
            })
            .catch(registrationError => {
                console.log('SW registration failed: ', registrationError);
            });
    });
}