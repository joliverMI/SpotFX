"""
THE CAPTURE LANE (data/jukebox-plan/report.md §9 phase 4, PR 4.1): learns a
song by playing it on the hidden player "Serenity Capture" under the second
Spotify account (account B), INAUDIBLY, and writing the same shape files a
normal capture writes — so a guest's request can be learned while the house
plays something else (absorb-then-queue).

WHY A PROCESS OF ITS OWN (`python -m capture_lane`, 127.0.0.1:8030,
reference unit deploy/spotfx-capture-lane.service): captures already fail
when SpotFX's event loop stalls, and a capture plus ~30 s of librosa a song
must never run inside main.py (the plan's risk 7).

WHY NOTHING IS AUDIBLE, and it is the container, not this code: the hidden
player's container writes its PCM into its OWN FIFO
(/home/javi/spotify-stack/capture-audio/capturefifo), a directory snapserver
does not even mount. This package only reads that FIFO.

WHAT IT KEEPS TRUE (capture_lane/lane.py is the binding statement):
  * nothing is written to account B while the second account's switch on
    SPECTRA's Settings page is off or unreadable (fx/second_account.py —
    it ships OFF): the account-B client itself refuses every write, and a
    switch turned off mid-song ends the song within one poll, pausing only
    the system's own song;
  * it plays only as account B, never the main account, and only on the one
    device named "Serenity Capture" — checked before every song, from fresh
    reads, or nothing plays;
  * it never captures over a song that is already learned;
  * one song at a time, and it lets go on every way out — pausing the
    hidden player only while it is still playing the song the lane started;
  * it acts only when SpotFX asks (`POST /learn`, with the lane's key —
    capture_lane/key.py). Deciding WHAT to learn, and when the house may
    (the night, sleeping, Absorb), is SpotFX's.

Modules: pcm.py (the FIFO and its clock), spotify.py (account B's calls),
lane.py (one song), app.py (the three routes).
"""
