# Known Issues

## UI/Display Issues

### Retired Equipment Row Hover - Text Color
**Status:** ✅ RESOLVED
**Priority:** Low
**Description:** When hovering over retired equipment rows in the equipment list table, text color was changing to white/light color making it difficult to read against the light gray background.

**Resolution:** Found root cause in `static/css/style.css` - a global `.table-hover tbody tr:hover` rule was applying light text color to ALL table rows. Fixed by adding `:not(.table-secondary)` selector to exclude retired equipment rows.

**Context:**
- Retired equipment rows use Bootstrap's `table-secondary` class for styling
- Initial fix attempts in templates were overridden by global CSS rule in style.css
- The global rule at lines 99-102 was applying `color: #e9ecef !important;` to all rows
- Solution: Modified global rule to exclude retired equipment with `:not(.table-secondary)`

---
