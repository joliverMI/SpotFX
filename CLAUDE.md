# SpotFX — agent notes

## In-app Help page (KEEP IT CURRENT)

The React app has a searchable help page at `/help`, rendered from
`web/src/help/helpContent.ts`. **Whenever you add or change a user-facing
feature — a page, keyboard shortcut, mouse/long-press gesture, filter
syntax, mode, or setting — update `helpContent.ts` in the same change.**
Treat it as part of the definition of done. The file header documents the
content schema and conventions (kbd tables, keywords, deep-link ids).

Deep links: `<HelpLink topic="<section-or-entry-id>" />` renders the small
circled-"?" used across the UI. Don't rename an id in `helpContent.ts`
without updating its `topic=` callers (grep `topic="`).

Prefer adding a `HelpLink` next to a complex control over embedding
instructional prose in the UI; short tooltips (`title=`) are fine.
