/**
 * SpotFX — Shared navigation bar.
 * Imported by every page to inject a consistent nav.
 */
import { GET, markActiveNav } from './app.js';

const NAV_HTML = `<nav>
  <span class="logo">SpotFX</span>
  <a href="/app/now">Now Playing</a>
  <a href="/" class="advanced-only-inline">Now Playing (legacy)</a>
  <a href="/app/builder">Profile Builder</a>
  <a href="/builder.html" class="advanced-only-inline">Builder (legacy)</a>
  <a href="/app/">Events</a>
  <a href="/events.html" class="advanced-only-inline">Events (legacy)</a>
  <a href="/app/color-sets">Color Sets</a>
  <a href="/color-sets.html" class="advanced-only-inline">Color Sets (legacy)</a>
  <a href="/app/devices">Devices</a>
  <a href="/devices.html" class="advanced-only-inline">Devices (legacy)</a>
  <a href="/app/ai-triggers" class="nav-ai-triggers">AI Triggers</a>
  <a href="/ai_triggers.html" class="nav-ai-triggers advanced-only-inline">AI Triggers (legacy)</a>
  <a href="/app/triggerless">Triggerless</a>
  <a href="/triggerless.html" class="advanced-only-inline">Triggerless (legacy)</a>
  <a href="/app/setlists">Set Lists</a>
  <a href="/setlist.html" class="advanced-only-inline">Set Lists (legacy)</a>
  <a href="/app/timing" class="nav-timing-viz advanced-only-inline">Timing</a>
  <a href="/timing-viz.html" class="advanced-only-inline">Timing (legacy)</a>
  <a href="/app/debug" class="nav-debug">Debug</a>
  <a href="/debug.html" class="advanced-only-inline">Debug (legacy)</a>
  <a href="/app/settings">Settings</a>
  <a href="/settings.html" class="advanced-only-inline">Settings (legacy)</a>
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
