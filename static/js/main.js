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
