# SpotFX React Migration Reference

This document captures architecture decisions and component mapping for a future React migration.
Updated as modularization progresses.

## Current Architecture
- **Backend**: Python + FastAPI (async, WebSocket)
- **Frontend**: Vanilla JS ES modules, served as static files by FastAPI
- **No build tooling**: Zero bundler, no node_modules

## Migration Stack (Recommended)
- **Vite** + **React 18+** (or 19 if stable)
- **TypeScript** (optional but recommended)
- **React Router** for SPA navigation
- **Dev proxy**: Vite proxies `/api/*` and `/ws` to FastAPI during development
- **Production**: Vite builds to `frontend/dist/`, FastAPI serves it as static

## Component Mapping

| Current Module/Pattern | React Component | Notes |
|---|---|---|
| `nav.js` (shared nav) | `<NavBar>` | Already extracted as module |
| `app.js` WS connection | `<WSProvider>` context | `useWS()` hook for components |
| `app.js` settings fetch | `<SettingsProvider>` context | `useSettings()` hook |
| `shape_canvas.js` | `<ShapeCanvas>` | Wrap existing factory in `useRef` + `useEffect` |
| Zoom handles (builder) | `<ZoomControls>` | Extract as module first |
| Action editor (events) | `<ActionEditor>` | Reusable form component |
| Trigger list (now playing) | `<TriggerList>` | Real-time WS updates via context |
| Toggle buttons | `<ToggleButton>` | `.toggle-btn` CSS already defined |
| Toast notifications | `useToast()` hook or context | Currently in `app.js` |
| Palette QWERTY display | `<PaletteKeyboard>` | New in modularization |

## Page Complexity (migration order: simplest first)

| Page | Lines | State Vars | WS Handlers | Suggested Order |
|---|---|---|---|---|
| Settings | 561 | 8 | 0 | 1st |
| Triggerless | 469 | 4 | 0 | 2nd |
| Events | 1,395 | 12 | 0 | 3rd |
| Now Playing | 908 | 30 | 11 | 4th |
| Builder | 1,813 | 45 | 9 | 5th |
| AI Triggers | 2,689 | 51 | 5 | Last (or skip) |

## Key Decisions
- Canvas stays imperative (React doesn't help with 2D context drawing)
- WS connection is app-level (single connection shared via context)
- Settings fetched once at app mount, cached in context
- Each "page" becomes a route in React Router
- FastAPI serves SPA's `index.html` for all routes (catch-all)

## Pre-Migration Modules (extract before React)
- [x] `nav.js` — shared nav bar injection
- [ ] `ws-state.js` — shared WS state (track, paused, etc.)
- [ ] `zoom-controls.js` — shared zoom handle logic
- [ ] `canvas.css` — shared canvas styles
- [ ] Action editor extraction from events.html
