/**
 * SpotFX — Shared navigation bar.
 * Imported by every page to inject a consistent nav.
 */
import { GET, markActiveNav } from './app.js';

const NAV_HTML = `<nav>
  <span class="logo">SpotFX</span>
  <a href="/">Now Playing</a>
  <a href="/builder.html">Profile Builder</a>
  <a href="/events.html">Events</a>
  <a href="/color-sets.html">Color Sets</a>
  <a href="/devices.html">Devices</a>
  <a href="/ai_triggers.html" class="nav-ai-triggers">AI Triggers</a>
  <a href="/triggerless.html">Triggerless</a>
  <a href="/setlist.html">Set Lists</a>
  <a href="/timing-viz.html" class="nav-timing-viz advanced-only-inline">Timing</a>
  <a href="/debug.html" class="nav-debug advanced-only-inline">Debug</a>
  <a href="/settings.html">Settings</a>
  <div id="ws-status"><div id="ws-dot"></div> Live</div>
</nav>`;

/**
 * Inject nav bar into #nav-root, mark the active link,
 * and conditionally hide AI Triggers based on settings.
 */
export function initNav() {
  const root = document.getElementById('nav-root');
  if (!root) return;
  root.innerHTML = NAV_HTML;
  markActiveNav();

  // Hide AI Triggers link if setting is off
  GET('/settings').then(s => {
    const aiLink = document.querySelector('.nav-ai-triggers');
    if (aiLink && !s?.show_ai_triggers) aiLink.style.display = 'none';
    // Advanced mode
    if (s?.show_advanced) document.body.classList.add('advanced-mode');
  }).catch(() => {});
}
