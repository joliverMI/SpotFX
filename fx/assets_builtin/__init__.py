"""SpotFX replacement for the fork's ledfx_assets package (23 MB of media,
not vendored). fx/consts.py imports this to resolve LEDFX_ASSETS_PATH.
builtin:// asset references resolve into this (near-empty) directory; the
GIFs production actually uses live in the user asset store under the fx
config dir and are uploaded through SpotFX's gif pipeline.
"""

import os


def where():
    return os.path.dirname(__file__)
