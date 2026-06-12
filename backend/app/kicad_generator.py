import os
import json
import subprocess
from datetime import datetime

from app.models import RobotContext, DesignSpec

# Very minimal KiCad schematic template. Replace with real S-expressions later.
SCHEM_TEMPLATE = """(kicad_sch (version 20231120) (generator "PCBlarp")
  (uuid "{uuid}")
  (paper "A4")
  (lib_symbols)
  {symbols}
  {wires}
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""

def generate_kicad_project(context: RobotContext, spec: DesignSpec, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    session_id = os.path.basename(out_dir)

    sch_path = os.path.join(out_dir, f"{session_id}.kicad_sch")
    with open(sch_path, "w") as f:
        f.write(SCHEM_TEMPLATE.format(
            uuid=session_id,
            symbols="",
            wires="",
        ))

    # Placeholder PCB
    pcb_path = os.path.join(out_dir, f"{session_id}.kicad_pcb")
    with open(pcb_path, "w") as f:
        f.write(f"""(kicad_pcb (version 20240108) (generator "PCBlarp")
  (general\n    (thickness 1.6)\n  )
  (paper "A4")
  (layers\n    (0 "F.Cu" signal)\n    (31 "B.Cu" signal)\n    (32 "B.Adhes" user "B.Adhesive")\n    (33 "F.Adhes" user "F.Adhesive")\n    (34 "B.Paste" user)\n    (35 "F.Paste" user)\n    (36 "B.SilkS" user "B.Silkscreen")\n    (37 "F.SilkS" user "F.Silkscreen")\n    (38 "B.Mask" user)\n    (39 "F.Mask" user)\n    (40 "Dwgs.User" user "User.Drawings")\n    (41 "Cmts.User" user "User.Comments")\n    (42 "Eco1.User" user "User.Eco1")\n    (43 "Eco2.User" user "User.Eco2")\n    (44 "Edge.Cuts" user)\n    (45 "Margin" user)\n  )
  (setup\n    (pad_to_mask_clearance 0)\n  )
  (net 0 "")
  (gr_rect (start 0 0) (end 100 100) (stroke (width 0.1) (type default)) (fill none) (layer "Edge.Cuts") (uuid "{session_id}-board"))
)
""")

    # BOM
    bom = []
    for c in spec.components:
        bom.append({
            "name": c.name,
            "value": c.value,
            "footprint": c.footprint,
            "reason": c.reason,
        })
    bom_path = os.path.join(out_dir, "bom.json")
    with open(bom_path, "w") as f:
        json.dump(bom, f, indent=2)

    return {
        "sch": sch_path,
        "pcb": pcb_path,
        "bom": bom,
        "gerbers": None,  # TODO: run kicad-cli export gerbers
    }


def run_kicad_cli(pcb_path: str, out_dir: str) -> str:
    """Export gerbers using kicad-cli. Returns zip path."""
    cli = os.getenv("KICAD_CLI_PATH", "kicad-cli")
    cmd = [
        cli, "pcb", "export", "gerbers",
        "--output", out_dir,
        pcb_path,
    ]
    subprocess.run(cmd, check=True)
    return out_dir
