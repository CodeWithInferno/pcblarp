"""Stage 5: collect artifacts -> Gerbers / BOM / pick-and-place + URLs.

This stage runs even when earlier stages failed so the demo always shows
partial results: it packages whatever exists (spec.json after stage 1,
bom.csv after stage 2, and so on). Gerber and pick-and-place content is
mocked until stage 4 is real.

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
from ..models import PartsResult, Spec
from . import injected_failure, slugify
from .layout import MANUFACTURER, LayoutResult
from .schematic import SchematicResult

GERBER_LAYERS = (
    "F_Cu.gtl", "B_Cu.gbl", "F_Mask.gts", "B_Mask.gbs",
    "F_Silkscreen.gto", "B_Silkscreen.gbo", "Edge_Cuts.gm1", "PTH.drl",
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

    if layout is not None:
        files["board"] = layout.board_path
        files["drc_report"] = layout.drc_report_path
        name = slugify(spec.project.name) if spec else "board"
        files[f"gerbers_{MANUFACTURER}.zip"] = str(
            _write_gerbers(name, out_dir)
        )
        if parts is not None:
            files["pick_and_place.csv"] = str(_write_pnp(parts, out_dir))

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


def _write_gerbers(name: str, out_dir: Path) -> Path:
    """MOCK: placeholder layer files until the real kicad-tools export."""
    gerber_dir = out_dir / "gerbers"
    if gerber_dir.exists():
        shutil.rmtree(gerber_dir)
    gerber_dir.mkdir(parents=True)
    for layer in GERBER_LAYERS:
        (gerber_dir / f"{name}-{layer}").write_text(
            f"; MOCK Gerber placeholder for {name} layer {layer}\n"
            f"; manufacturer profile: {MANUFACTURER}\n"
            "; replaced by real kicad-tools plot output in stage 4\n"
        )
    zip_path = out_dir / f"gerbers_{MANUFACTURER}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(gerber_dir.iterdir()):
            zf.write(file, file.name)
    return zip_path


def _write_pnp(parts: PartsResult, out_dir: Path) -> Path:
    """MOCK: grid positions until the real placement data exists."""
    path = out_dir / "pick_and_place.csv"
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["Ref", "Val", "Package", "PosX", "PosY", "Rot", "Side"])
        placed = [l for l in parts.bom if l.status == "matched"]
        for i, line in enumerate(placed):
            writer.writerow([
                f"U{i + 1}", line.mpn, line.package or "unknown",
                f"{(i % 5) * 10.0:.2f}", f"{(i // 5) * 10.0:.2f}", "0",
                "top",
            ])
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
