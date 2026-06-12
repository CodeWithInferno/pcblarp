"""Real EDA file generation for ChatPCB.

Generates self-contained KiCad files (schematic, board, Gerbers) directly,
using symbols and footprints vendored from the official KiCad libraries
(data/kicad_library, fetched by scripts/fetch_kicad_library.py). No KiCad
installation or kicad-tools dependency is required at runtime; generated
files embed every symbol and footprint they reference.
"""
