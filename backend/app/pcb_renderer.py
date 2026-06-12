import os

# TODO: convert kicad_pcb to a format the browser 3D viewer can use.
# Options:
# 1. Use kicad-cli to export STEP -> convert to glTF/GLB
# 2. Parse kicad_pcb S-expressions and generate Three.js geometry
# 3. Use KiCanvas WASM in browser directly

def get_preview_data(pcb_path: str) -> dict:
    """Return metadata + a placeholder viewer payload."""
    if not os.path.exists(pcb_path):
        return {"error": "PCB file not found"}
    return {
        "pcb_path": pcb_path,
        "viewer_type": "threejs",
        "payload": {
            "board": {"width": 100, "height": 100, "thickness": 1.6},
            "components": [],
            "traces": [],
        },
    }
