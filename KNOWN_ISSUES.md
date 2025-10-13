# Known Issues

## UI/Display Issues

### Retired Equipment Row Hover - Text Color
**Status:** Open
**Priority:** Low
**Description:** When hovering over retired equipment rows in the equipment list table, text color changes to white/light color making it difficult to read against the light gray background.

**Context:**
- Retired equipment rows use Bootstrap's `table-secondary` class for styling
- The `table-hover` class applies hover effects that override text colors
- Multiple CSS override attempts have not successfully prevented the text color change on hover
- Attempted fixes:
  - Direct color overrides with `!important`
  - Bootstrap CSS variable overrides (`--bs-table-hover-color`)
  - More specific selectors (tbody, child selectors)

**Workaround:** Text is readable when not hovering. Double-click functionality still works.

**Next Steps:** May require removing `table-hover` class entirely for retired rows, or using a different styling approach (e.g., custom class instead of Bootstrap's `table-secondary`).

---
