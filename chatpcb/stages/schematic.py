"""Stage 3: spec + parts -> .kicad_sch (MOCKED).

Real implementation: instantiate kicad-tools circuit blocks per spec block,
wire them from spec.connections, run ERC, and raise StageError with the ERC
output as llm_feedback on failure. Install the real deps with
`pip install -e ".[eda]"`; until then we emit a minimal kicad_sch skeleton
plus a netlist derived from the spec, so the demo always has downloadable
artifacts and downstream stages have a stable interface to build against.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

try:  # guarded: stage runs mocked when the eda extra is not installed
    import kicad_tools  # type: ignore  # noqa: F401
    HAVE_KICAD_TOOLS = True
except ImportError:
    HAVE_KICAD_TOOLS = False

from ..models import PartsResult, Spec
from . import StageError, injected_failure, slugify


@dataclass
class SchematicResult:
    sch_path: str
    netlist_path: str
    erc_errors: int
    mocked: bool


def build_schematic(spec: Spec, parts: PartsResult, out_dir: Path) -> SchematicResult:
    failure = injected_failure("schematic")
    if failure:
        raise failure
    out_dir.mkdir(parents=True, exist_ok=True)

    if HAVE_KICAD_TOOLS:
        # TODO: real flow — kicad_tools circuit blocks per spec.blocks, nets
        # from spec.connections, ERC, write .kicad_sch.
        raise StageError(
            "kicad-tools schematic generation not implemented yet; "
            "uninstall the [eda] extra to run the mock"
        )

    netlist = {
        "blocks": [
            {"id": b.id, "catalog_block": b.catalog_block, "purpose": b.purpose}
            for b in spec.blocks
        ],
        "nets": [
            {
                "from": c.from_block,
                "to": c.to_block,
                "interface": c.interface,
                "notes": c.notes,
            }
            for c in spec.connections
        ],
        "bom_refs": [line.mpn for line in parts.bom if line.mpn],
        "mocked": True,
    }
    netlist_path = out_dir / "netlist.json"
    netlist_path.write_text(json.dumps(netlist, indent=2))

    sch_path = out_dir / f"{slugify(spec.project.name)}.kicad_sch"
    sch_path.write_text(_mock_kicad_sch(spec))

    erc_errors = 0  # mock ERC always passes
    if erc_errors:
        raise StageError(
            f"ERC failed with {erc_errors} errors",
            llm_feedback=f"ERC reported {erc_errors} errors.",
            metrics={"erc_errors": float(erc_errors)},
        )
    return SchematicResult(
        sch_path=str(sch_path),
        netlist_path=str(netlist_path),
        erc_errors=erc_errors,
        mocked=True,
    )


def _mock_kicad_sch(spec: Spec) -> str:
    lines = [
        "(kicad_sch",
        "  (version 20231120)",
        '  (generator "chatpcb-mock")',
        "  (title_block",
        f'    (title "{slugify(spec.project.name)}")',
        '    (comment 1 "MOCK schematic placeholder, replace with kicad-tools output")',
        "  )",
    ]
    for i, block in enumerate(spec.blocks):
        lines.append(
            f'  (text "{block.id}: {block.catalog_block}" (at 25.4 {25.4 * (i + 1)} 0))'
        )
    lines.append(")")
    return "\n".join(lines) + "\n"
