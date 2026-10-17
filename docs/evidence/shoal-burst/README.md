# The shoaling burst, before and after

Each image is ONE pair rendered twice on the real vendored pipeline with the same seed, warm-up and gradients: the TOP block is the branch's merge-base (`d903874dc737`), the BOTTOM block is this branch. The first tile of each block is the outgoing effect just before the switch; every later tile is 5 frames (0.083 s) on.

Regenerate: `.venv/bin/python scripts/render_shoal_burst.py`.

The numbers behind them, and what each one is held to, are in `tests/test_shoal_burst.py`. 72x37 dummy matrix — the full rectangle, NOT his crystal's 976 real cells; nothing here has been seen in his room.
