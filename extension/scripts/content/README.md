# /extension/scripts/content/

Content scripts injected into job-board pages via `content_scripts` in manifest.json.

## Planned modules

| File | Responsibility |
|------|---------------|
| `scanner.js` | MutationObserver — detects form fields as they enter the DOM |
| `field_mapper.js` | Assigns UUIDs, extracts labels via the 3-rung traversal (attribute → label[for] → ancestor) |
| `constraint_extractor.js` | Reads `maxLength`, parses placeholder/sibling text for char/word limits |
| `injector.js` | Writes values using native prototype descriptor override + synthetic event dispatch |
| `verifier.js` | Read-back loop — confirms the value persisted after React/Angular reconciliation |
| `widget_strategies.js` | Per-widget-type fill logic: select, checkbox/radio, contenteditable, file input, custom combobox |
| `dom_registry.js` | Map<fieldId, WeakRef<Node>> + data-attribute fallback for re-query on deref miss |
