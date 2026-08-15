# Marvi OS Desktop

Generated from the `@quick-start/electron` React/TypeScript template, then
reduced to the Marvi OS main control center and always-on Dynamic Island.

The renderer has no chat or terminal surface. Electron main owns the tray and
the separate frameless Island window. Closing the main window leaves both alive.

Development commands are repository tooling, not product UX:

```powershell
npm run dev
npm run test
npm run typecheck
```
