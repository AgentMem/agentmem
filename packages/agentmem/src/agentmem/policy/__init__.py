"""The learned advantage layer: score past decisions, then let that history nudge the
next one. Training-free — it retrieves similar past states and estimates whether
injecting or staying silent tended to work out better. Nothing here invents a
reminder; it only adjusts the intervene/stay-silent call, and falls back to the plain
Phase 2 behavior whenever it has too little data.
"""

from __future__ import annotations
