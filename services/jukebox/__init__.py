"""
SpotFX — the Jukebox (data/jukebox-plan/report.md). Phase 1 is the program
engine: the host's set list played as Spotify's context, with jukebox slots
between set songs filled just in time from the jukebox line.

  program.py   the rules (where the slots are, what fills them) — pure
  night.py     the engine at run time: one night, observed from the poll
  gateway.py   every Spotify call, blocking, spaced; reached off the loop
  store.py     his program settings and the night file

models/jukebox.py is the data. The code says `program`, never `setlist`:
SpotFX's existing Set Lists feature (services/setlist_store.py) is a
different thing and keeps its name.
"""
