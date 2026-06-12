"""Stage 5: collect artifacts -> Gerbers / BOM / pick-and-place + URLs.

This stage runs even when earlier stages failed so the demo always shows
partial results: it packages whatever exists (spec.json after stage 1,
bom.csv after stage 2, and so on). Gerber, pick-and-place, and assembly
BOM content is real, derived from the placed board (the board is unrouted,
so the copper layers carry pads only).

With S3_BUCKET set, files upload via boto3 and presigned URLs are returned;
otherwise URLs point at /artifacts/{run_id}/... served by the FastAPI app.
"""

from __future__ import annotations

import csv
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..eda.board_gen import Board, build_board
from ..eda.gerber import write_gerbers
from ..eda.netlist import Design, DesignError, assembly_bom, build_design
from ..models import PartsResult, Spec
from . import injected_failure, slugify
from .layout import MANUFACTURER, LayoutResult
from .schematic import SchematicResult

GERBER_LAYERS = (
    "F_Cu.gtl", "B_Cu.gbl", "F_Mask.gts", "B_Mask.gbs",
    "Edge_Cuts.gm1", "PTH.drl",
)


@dataclass
class ExportResult:
    files: dict[str, str] = field(default_factory=dict)  # name -> local path
    urls: dict[str, str] = field(default_factory=dict)   # name -> download URL


def export_artifacts(
    run_id: str,
    spec: Spec | None,
    parts: PartsResult | None,
    schematic: SchematicResult | None,
    layout: LayoutResult | None,
    out_dir: Path,
) -> ExportResult:
    failure = injected_failure("export")
    if failure:
        raise failure
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}

    if spec is not None:
        spec_path = out_dir / "spec.json"
        spec_path.write_text(spec.model_dump_json(indent=2))
        files["spec.json"] = str(spec_path)

    if parts is not None:
        files["bom.csv"] = str(_write_bom(parts, out_dir))

    if schematic is not None:
        files["schematic"] = schematic.sch_path
        files["netlist"] = schematic.netlist_path

    if layout is not None and spec is not None:
        files["board"] = layout.board_path
        files["drc_report"] = layout.drc_report_path
        name = slugify(spec.project.name)
        # Rebuild the design + placement deterministically from the spec
        # (same inputs as stage 4) to derive fab outputs.
        try:
            design = build_design(spec)
            board = build_board(design, spec.constraints.max_board_size_mm)
        except DesignError:
            design = board = None
        if design is not None and board is not None:
            files[f"gerbers_{MANUFACTURER}.zip"] = str(
                _write_gerber_zip(design, board, name, out_dir)
            )
            files["pick_and_place.csv"] = str(_write_pnp(board, out_dir))
            files["bom_assembly.csv"] = str(
                _write_assembly_bom(design, out_dir)
            )

    return ExportResult(files=files, urls=_publish(run_id, files))


def _write_bom(parts: PartsResult, out_dir: Path) -> Path:
    path = out_dir / "bom.csv"
    columns = [
        "block_id", "catalog_block", "role", "mpn", "lcsc", "description",
        "package", "qty", "unit_price_usd", "status",
    ]
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for line in parts.bom:
            writer.writerow(line.model_dump(include=set(columns)))
    return path


def _write_gerber_zip(design: Design, board: Board, name: str,
                      out_dir: Path) -> Path:
    gerber_dir = out_dir / "gerbers"
    if gerber_dir.exists():
        shutil.rmtree(gerber_dir)
    gerber_dir.mkdir(parents=True)
    write_gerbers(design, board, name, gerber_dir)
    zip_path = out_dir / f"gerbers_{MANUFACTURER}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(gerber_dir.iterdir()):
            zf.write(file, file.name)
    return zip_path


def _write_pnp(board: Board, out_dir: Path) -> Path:
    """Real centroid data from the placement (footprint origin, top side)."""
    path = out_dir / "pick_and_place.csv"
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        for placement in board.placements:
            writer.writerow([
                placement.ref,
                f"{placement.x:.3f}mm",
                f"{board.height - placement.y:.3f}mm",
                "top" if placement.side == "top" else "bottom",
                f"{placement.rot:.0f}",
            ])
    return path


def _write_assembly_bom(design: Design, out_dir: Path) -> Path:
    """PCBA-style BOM: every real component grouped by value+footprint."""
    path = out_dir / "bom_assembly.csv"
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["refs", "qty", "value", "footprint", "symbol"])
        writer.writeheader()
        for row in assembly_bom(design):
            writer.writerow(row)
    return path


def _publish(run_id: str, files: dict[str, str]) -> dict[str, str]:
    bucket = config.env("S3_BUCKET")
    if not bucket:
        return {
            name: f"/artifacts/{run_id}/{Path(path).name}"
            for name, path in files.items()
        }
    import boto3

    s3 = boto3.client("s3")
    urls: dict[str, str] = {}
    for name, path in files.items():
        key = f"chatpcb/{run_id}/{Path(path).name}"
        s3.upload_file(str(path), bucket, key)
        urls[name] = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=7 * 24 * 3600,
        )
    return urls
