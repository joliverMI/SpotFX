"""
The Jukebox's GUEST APP (data/jukebox-plan/report.md §7 and §9 phase 2, PR
2.1): the page guests open on their phones, as ITS OWN PROCESS on its own
port (`python -m jukebox_guest`, :8020) — never inside SpotFX's main.py,
whose event loop runs the music (the plan's risk 7).

FOUR THINGS IT KEEPS TRUE:
  * NOTHING BUT GUEST ROUTES ANSWER. app.ROUTES is the whole surface: the
    page and its files, and the calls under /g/. No docs, no OpenAPI, no
    master route; anything else is a 404. Tailscale Funnel publishes this
    port and only this port (services/jukebox/guest_link.py).
  * IT FORWARDS A SHORT ALLOWLIST, NAMING THE PHONE. Each /g/ call becomes
    exactly one of app.FORWARDS on SpotFX's loopback address, carrying the
    guest app's key (key.py) and the phone's code from its cookie (or, when
    a phone lost its cookie, the copy in its own storage). A phone never
    names a SpotFX path, and never names another phone.
  * RATE LIMITS, before anything is forwarded: per phone, per address for
    new phones, and for the whole party (app.LIMITS); a request body over
    2 KB is refused.
  * THE PARTY TOKEN STAYS PRIVATE. It is in the page's own address
    (`/?t=...`): the access log is off, the referrer policy is no-referrer
    (album art comes from Spotify's servers), and the page drops it from the
    address bar once the phone has joined.

What a call DOES is services/jukebox/guests.py, in SpotFX. The page itself
is spectra/web/src/guest/, built to spectra/web/guest-dist/
(`cd spectra/web && npx vite build --config vite.guest.config.ts`).
"""
