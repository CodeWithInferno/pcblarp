"""Stage 3: spec + parts -> real netlist + .kicad_sch.

Instantiates real circuits (chatpcb/eda/blocks.py) for every spec block,
resolves all nets (chatpcb/eda/netlist.py), and writes a self-contained
KiCad schematic with symbols embedded from the vendored official KiCad
library. Design problems (unsupported blocks, missing power source, GPIO
exhaustion) raise StageError with llm_feedback so the pipeline's revision
loop can ask Claude for a buildable spec.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..eda.netlist import Design, DesignError, build_design
from ..eda.schematic_gen import generate_schematic
from ..models import PartsResult, Spec
from . import StageError, injected_failure, slugify


@dataclass
class SchematicResult:
    sch_path: str
    netlist_path: str
    erc_errors: int
    mocked: bool
    component_count: int = 0
    net_count: int = 0


def build_schematic(spec: Spec, parts: PartsResult, out_dir: Path) -> SchematicResult:
    failure = injected_failure("schematic")
    if failure:
        raise failure
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        design = build_design(spec)
    except DesignError as exc:
        raise StageError(str(exc), llm_feedback=exc.llm_feedback) from exc

    if design.erc_errors:
        raise StageError(
            f"ERC failed with {len(design.erc_errors)} errors: "
            + "; ".join(design.erc_errors),
            llm_feedback=(
                "Electrical rule check failed: "
                + "; ".join(design.erc_errors)
            ),
            metrics={"erc_errors": float(len(design.erc_errors))},
        )

    netlist_path = out_dir / "netlist.json"
    netlist_path.write_text(json.dumps(_netlist_dict(design, parts), indent=2))

    sch_path = out_dir / f"{slugify(spec.project.name)}.kicad_sch"
    sch_path.write_text(generate_schematic(design, slugify(spec.project.name)))

    return SchematicResult(
        sch_path=str(sch_path),
        netlist_path=str(netlist_path),
        erc_errors=0,
        mocked=False,
        component_count=len(design.components),
        net_count=len(design.nets),
    )


def _netlist_dict(design: Design, parts: PartsResult) -> dict:
    return {
        "components": [
            {
                "ref": c.ref,
                "value": c.value,
                "symbol": c.lib_id,
                "footprint": c.footprint_id,
                "block": c.block_id,
            }
            for c in design.components
        ],
        "nets": {
            net: [f"{ref}.{pin}" for ref, pin in members]
            for net, members in sorted(design.nets.items())
        },
        "warnings": design.warnings,
        "notes": design.notes,
        "bom_refs": [line.mpn for line in parts.bom if line.mpn],
        "mocked": False,
    }
