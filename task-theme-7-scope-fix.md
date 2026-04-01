# Task: Fix Theme Toggle — Function Scope Bug

The theme toggle buttons don't work because `setThemePref`, `setFontPref`, `updateThemeButtons`, and `loadDisplayPrefs` are defined inside an IIFE (Immediately Invoked Function Expression) and are not accessible from the global scope where `onclick=` handlers run.

**Fix:** Expose these functions to the global scope using `window.` prefix.

---

## Fix for ALL files that have theme toggle buttons

Check each of these files for the same issue:
- `frontend/vendor/dashboard.html`
- `frontend/admin/settings.html`
- `frontend/pos/index.html`

In each file, find these function definitions (they may be inside an IIFE or other wrapper function):

```javascript
    function setThemePref(theme) {
```
```javascript
    function setFontPref(size) {
```
```javascript
    function updateThemeButtons(theme) {
```
```javascript
    function loadDisplayPrefs() {
```

And change them to be explicitly global:

```javascript
    window.setThemePref = function(theme) {
```
```javascript
    window.setFontPref = function(size) {
```
```javascript
    window.updateThemeButtons = function(theme) {
```
```javascript
    window.loadDisplayPrefs = function() {
```

**Also check:** Make sure `loadDisplayPrefs()` is still called at the end. If it was called as `loadDisplayPrefs();` inside the IIFE, it should now be `window.loadDisplayPrefs();` or just keep `loadDisplayPrefs();` after the assignment.

**Test:** After this fix, clicking the "Light" button on the vendor dashboard should immediately change the page background, text colors, and navbar to the light theme. Clicking "Dark" should switch back.

Commit and push when done.
