"""Loader for the vendored KiCad library (data/kicad_library).

Symbols and footprints are stored exactly as fetched from the official
KiCad libraries (flattened, standalone). This module parses them into
light dataclasses the generators consume:

  - SymbolDef: embeddable tree + pin table (number, name, position, angle)
  - FootprintDef: embeddable tree + pad table + courtyard bounding box
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .. import config
from . import sexpr

LIBRARY_DIR = config.DATA_DIR / "kicad_library"


class LibraryError(RuntimeError):
    """A referenced symbol or footprint is not in the vendored library."""


@dataclass(frozen=True)
class Pin:
    number: str
    name: str
    x: float          # symbol-space, mm, Y up
    y: float
    angle: float      # 0 right, 90 up, 180 left, 270 down (pin points INTO body)
    length: float
    etype: str        # passive, power_in, input, output, ...


@dataclass
class SymbolDef:
    lib_id: str               # "Device:R"
    tree: list                # (symbol "Name" ...) flattened
    pins: list[Pin]
    default_footprint: str    # "" when unset

    def pins_named(self, name: str) -> list[Pin]:
        return [p for p in self.pins if p.name == name]

    def pin(self, number: str) -> Pin:
        for p in self.pins:
            if p.number == number:
                return p
        raise LibraryError(f"{self.lib_id}: no pin number {number!r}")


@dataclass(frozen=True)
class Pad:
    number: str               # "" for NPTH holes
    kind: str                 # smd | thru_hole | np_thru_hole
    shape: str                # circle | rect | oval | roundrect | custom
    x: float                  # footprint-space, mm, Y down (board convention)
    y: float
    rot: float
    w: float
    h: float
    drill_w: float            # 0 for SMD
    drill_h: float
    layers: tuple[str, ...]
    roundrect_ratio: float


@dataclass
class FootprintDef:
    lib_id: str
    tree: list
    pads: list[Pad]
    courtyard: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    @property
    def width(self) -> float:
        return self.courtyard[2] - self.courtyard[0]

    @property
    def height(self) -> float:
        return self.courtyard[3] - self.courtyard[1]


@lru_cache(maxsize=None)
def load_symbol(lib_id: str) -> SymbolDef:
    lib, name = _split(lib_id)
    path = LIBRARY_DIR / "symbols" / lib / f"{name}.kicad_sym"
    if not path.exists():
        raise LibraryError(f"symbol {lib_id} not vendored (run scripts/fetch_kicad_library.py)")
    wrapper = sexpr.parse(path.read_text())
    node = sexpr.children(wrapper, "symbol")[0]
    pins = _collect_pins(node)
    fp = ""
    for prop in sexpr.children(node, "property"):
        if prop[1] == "Footprint" and isinstance(prop[2], str):
            fp = prop[2]
    return SymbolDef(lib_id=lib_id, tree=node, pins=pins, default_footprint=fp)


def _collect_pins(node: list) -> list[Pin]:
    pins: list[Pin] = []
    for unit in sexpr.children(node, "symbol"):
        pins.extend(_collect_pins(unit))
    for pin in sexpr.children(node, "pin"):
        at = sexpr.child(pin, "at")
        name_node = sexpr.child(pin, "name")
        number_node = sexpr.child(pin, "number")
        pins.append(Pin(
            number=sexpr.text_of(number_node),
            name=sexpr.text_of(name_node),
            x=sexpr.number(at, 0),
            y=sexpr.number(at, 1),
            angle=sexpr.number(at, 2),
            length=sexpr.number(sexpr.child(pin, "length")),
            etype=sexpr.text_of(pin, 0),
        ))
    return pins


@lru_cache(maxsize=None)
def load_footprint(lib_id: str) -> FootprintDef:
    lib, name = _split(lib_id)
    path = LIBRARY_DIR / "footprints" / f"{lib}.pretty" / f"{name}.kicad_mod"
    if not path.exists():
        raise LibraryError(f"footprint {lib_id} not vendored (run scripts/fetch_kicad_library.py)")
    tree = sexpr.parse(path.read_text())
    pads = [_parse_pad(p) for p in sexpr.children(tree, "pad")]
    courtyard = _courtyard_bbox(tree, pads)
    return FootprintDef(lib_id=lib_id, tree=tree, pads=pads, courtyard=courtyard)


def _parse_pad(pad: list) -> Pad:
    at = sexpr.child(pad, "at")
    size = sexpr.child(pad, "size")
    drill = sexpr.child(pad, "drill")
    drill_w = drill_h = 0.0
    if drill is not None:
        nums = [a for a in sexpr.atoms(drill) if not isinstance(a, str) or _numeric(a)]
        vals = [float(a) for a in sexpr.atoms(drill) if _numeric(a)]
        if "oval" in [getattr(a, "text", a) for a in sexpr.atoms(drill)]:
            drill_w = vals[0] if vals else 0.0
            drill_h = vals[1] if len(vals) > 1 else drill_w
        else:
            drill_w = drill_h = vals[0] if vals else 0.0
        del nums
    layers = tuple(
        a if isinstance(a, str) else a.text
        for a in sexpr.atoms(sexpr.child(pad, "layers") or [])
    )
    rr = sexpr.number(sexpr.child(pad, "roundrect_rratio"), 0, 0.25)
    return Pad(
        number=str(pad[1]) if isinstance(pad[1], str) else pad[1].text,
        kind=sexpr.text_of(pad, 1),
        shape=sexpr.text_of(pad, 2),
        x=sexpr.number(at, 0),
        y=sexpr.number(at, 1),
        rot=sexpr.number(at, 2),
        w=sexpr.number(size, 0),
        h=sexpr.number(size, 1),
        drill_w=drill_w,
        drill_h=drill_h,
        layers=layers,
        roundrect_ratio=rr,
    )


def _numeric(atom) -> bool:
    try:
        float(atom)
        return True
    except (TypeError, ValueError):
        return False


def _courtyard_bbox(tree: list, pads: list[Pad]) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []

    def on_courtyard(node: list) -> bool:
        layer = sexpr.child(node, "layer")
        return sexpr.text_of(layer) in ("F.CrtYd", "B.CrtYd")

    for kind in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly"):
        for node in sexpr.children(tree, kind):
            if not on_courtyard(node):
                continue
            for ptname in ("start", "end", "center", "mid"):
                pt = sexpr.child(node, ptname)
                if pt is not None:
                    xs.append(sexpr.number(pt, 0))
                    ys.append(sexpr.number(pt, 1))
            pts = sexpr.child(node, "pts")
            if pts is not None:
                for xy in sexpr.children(pts, "xy"):
                    xs.append(sexpr.number(xy, 0))
                    ys.append(sexpr.number(xy, 1))
    if not xs:  # no courtyard drawn: fall back to pad extents + margin
        for pad in pads:
            half = max(pad.w, pad.h) / 2 * math.sqrt(2)
            xs.extend([pad.x - half, pad.x + half])
            ys.extend([pad.y - half, pad.y + half])
        if not xs:
            return (-1.0, -1.0, 1.0, 1.0)
        return (min(xs) - 0.5, min(ys) - 0.5, max(xs) + 0.5, max(ys) + 0.5)
    return (min(xs), min(ys), max(xs), max(ys))


def _split(lib_id: str) -> tuple[str, str]:
    if ":" not in lib_id:
        raise LibraryError(f"bad lib id {lib_id!r}, expected 'Lib:Name'")
    lib, name = lib_id.split(":", 1)
    return lib, name


def available_symbols() -> list[str]:
    out = []
    for path in sorted((LIBRARY_DIR / "symbols").glob("*/*.kicad_sym")):
        out.append(f"{path.parent.name}:{path.stem}")
    return out
