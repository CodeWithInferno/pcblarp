"""Design -> placed .kicad_pcb (real footprints, real nets, no routing yet).

Placement is deterministic shelf packing of courtyard boxes: connectors
first (so they land on the bottom edge row where a human would want them),
then everything else tallest-first. Checks performed are honest:

  - courtyard overlap (should never fire; packing prevents it)
  - board outline overflow (fires when the spec's max_board_size_mm is too
    small for the parts -> StageError feeds the revision loop)

Routing is intentionally not faked: the board ships placed-but-unrouted
with the ratsnest visible in KiCad, and the DRC report says so.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

from . import library, sexpr
from .netlist import Design
from .sexpr import Sym

NAMESPACE = uuid.UUID("7c3b71f9-5fce-4f4d-9d2a-3e7e2f8b9a01")

EDGE_MARGIN = 1.5      # courtyard to board edge, mm
PART_GAP = 0.6         # courtyard to courtyard, mm
ORIGIN = (50.0, 50.0)  # board top-left on the KiCad page


@dataclass
class Placement:
    ref: str
    footprint: library.FootprintDef
    x: float            # board-relative, mm (footprint origin)
    y: float
    rot: float = 0.0
    side: str = "top"


@dataclass
class Board:
    width: float
    height: float
    placements: list[Placement]
    violations: list[str] = field(default_factory=list)
    unrouted_nets: int = 0

    def placement(self, ref: str) -> Placement:
        for p in self.placements:
            if p.ref == ref:
                return p
        raise KeyError(ref)


def _uid(*key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, ":".join(key)))


def _fmt(v: float) -> str:
    if abs(v) < 5e-5:
        v = 0.0
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s or "0"


def build_board(design: Design,
                max_size_mm: tuple[float, float] | None) -> Board:
    boxes = []
    for comp in design.components:
        fp = library.load_footprint(comp.footprint_id)
        boxes.append((comp.ref, fp))

    def is_connector(item) -> bool:
        return item[0].rstrip("0123456789").rstrip(".") in ("J", "BT", "SW")

    def height(item) -> float:
        return item[1].height

    ordered = sorted(
        boxes,
        key=lambda b: (not is_connector(b), -b[1].width * b[1].height),
    )

    if max_size_mm:
        board_w, board_h = float(max_size_mm[0]), float(max_size_mm[1])
    else:
        area = sum((b[1].width + PART_GAP) * (b[1].height + PART_GAP)
                   for b in boxes)
        board_w = max(20.0, math.sqrt(area * 1.8 * 1.4))
        board_h = max(15.0, board_w / 1.4)

    placements, overflow = _maxrects_pack(ordered, board_w, board_h)
    if overflow and not max_size_mm:
        # auto-sized board: grow until everything fits
        scale = 1.2
        while overflow and scale < 3.0:
            placements, overflow = _maxrects_pack(
                ordered, board_w * scale, board_h * scale)
            if not overflow:
                board_w, board_h = board_w * scale, board_h * scale
            scale += 0.2

    violations = []
    if overflow:
        refs = ", ".join(r for r, _ in overflow)
        violations.append(
            f"board_outline: {len(overflow)} parts do not fit the "
            f"{board_w:.0f}x{board_h:.0f}mm outline ({refs})"
        )
    violations.extend(_courtyard_overlaps(placements))

    multi_pin_nets = sum(1 for members in design.nets.values()
                         if len(members) >= 2)
    return Board(
        width=round(board_w, 2),
        height=round(board_h, 2),
        placements=placements,
        violations=violations,
        unrouted_nets=multi_pin_nets,
    )


def _maxrects_pack(ordered, board_w: float, board_h: float):
    """MaxRects best-short-side-fit packing (no rotation)."""
    placements: list[Placement] = []
    overflow: list = []
    free = [(EDGE_MARGIN, EDGE_MARGIN,
             board_w - EDGE_MARGIN, board_h - EDGE_MARGIN)]

    for ref, fp in ordered:
        w = fp.width + PART_GAP
        h = fp.height + PART_GAP
        best = None
        for rect in free:
            rw, rh = rect[2] - rect[0], rect[3] - rect[1]
            if w <= rw + 1e-9 and h <= rh + 1e-9:
                score = min(rw - w, rh - h)
                if best is None or score < best[0]:
                    best = (score, rect)
        if best is None:
            overflow.append((ref, fp))
            continue
        rect = best[1]
        px, py = rect[0], rect[1]
        placed = (px, py, px + w, py + h)
        placements.append(Placement(
            ref=ref, footprint=fp,
            x=px - fp.courtyard[0] + PART_GAP / 2,
            y=py - fp.courtyard[1] + PART_GAP / 2,
        ))
        free = _split_free(free, placed)
    return placements, overflow


def _split_free(free, used):
    out = []
    ux0, uy0, ux1, uy1 = used
    for fx0, fy0, fx1, fy1 in free:
        if ux0 >= fx1 or ux1 <= fx0 or uy0 >= fy1 or uy1 <= fy0:
            out.append((fx0, fy0, fx1, fy1))
            continue
        if uy0 > fy0:
            out.append((fx0, fy0, fx1, uy0))      # above
        if uy1 < fy1:
            out.append((fx0, uy1, fx1, fy1))      # below
        if ux0 > fx0:
            out.append((fx0, fy0, ux0, fy1))      # left
        if ux1 < fx1:
            out.append((ux1, fy0, fx1, fy1))      # right
    # prune rects fully contained in another
    pruned = []
    for i, a in enumerate(out):
        contained = any(
            i != j and b[0] <= a[0] and b[1] <= a[1]
            and b[2] >= a[2] and b[3] >= a[3]
            for j, b in enumerate(out)
        )
        if not contained:
            pruned.append(a)
    return pruned


def _courtyard_overlaps(placements: list[Placement]) -> list[str]:
    out = []
    rects = []
    for p in placements:
        c = p.footprint.courtyard
        rects.append((p.ref, p.x + c[0], p.y + c[1], p.x + c[2], p.y + c[3]))
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]:
                out.append(f"courtyard_overlap: {a[0]} overlaps {b[0]}")
    return out


# ---------------------------------------------------------------------------
# .kicad_pcb generation
# ---------------------------------------------------------------------------

_LAYERS = [
    (0, "F.Cu", "signal"), (31, "B.Cu", "signal"),
    (32, "B.Adhes", "user", "B.Adhesive"), (33, "F.Adhes", "user", "F.Adhesive"),
    (34, "B.Paste", "user"), (35, "F.Paste", "user"),
    (36, "B.SilkS", "user", "B.Silkscreen"), (37, "F.SilkS", "user", "F.Silkscreen"),
    (38, "B.Mask", "user"), (39, "F.Mask", "user"),
    (40, "Dwgs.User", "user", "User.Drawings"), (41, "Cmts.User", "user", "User.Comments"),
    (44, "Edge.Cuts", "user"), (45, "Margin", "user"),
    (46, "B.CrtYd", "user", "B.Courtyard"), (47, "F.CrtYd", "user", "F.Courtyard"),
    (48, "B.Fab", "user"), (49, "F.Fab", "user"),
]


def generate_board(design: Design, board: Board, title: str) -> str:
    net_numbers: dict[str, int] = {"": 0}
    for net in sorted(design.nets):
        net_numbers[net] = len(net_numbers)

    layers_node = [Sym("layers")]
    for entry in _LAYERS:
        node = [Sym(str(entry[0])), entry[1], Sym(entry[2])]
        if len(entry) > 3:
            node.append(entry[3])
        layers_node.append(node)

    tree = [
        Sym("kicad_pcb"),
        [Sym("version"), Sym("20240108")],
        [Sym("generator"), "chatpcb"],
        [Sym("general"), [Sym("thickness"), Sym("1.6")],
         [Sym("legacy_teardrops"), Sym("no")]],
        [Sym("paper"), "A4"],
        [Sym("title_block"), [Sym("title"), title]],
        layers_node,
        [Sym("setup"),
         [Sym("pad_to_mask_clearance"), Sym("0")],
         [Sym("allow_soldermask_bridges_in_footprints"), Sym("no")]],
        *[[Sym("net"), Sym(str(num)), name]
          for name, num in sorted(net_numbers.items(), key=lambda kv: kv[1])],
    ]

    comp_by_ref = {c.ref: c for c in design.components}
    for placement in board.placements:
        comp = comp_by_ref[placement.ref]
        tree.append(_footprint_node(comp, placement, net_numbers))

    x0, y0 = ORIGIN
    x1, y1 = x0 + board.width, y0 + board.height
    tree.append([
        Sym("gr_rect"),
        [Sym("start"), Sym(_fmt(x0)), Sym(_fmt(y0))],
        [Sym("end"), Sym(_fmt(x1)), Sym(_fmt(y1))],
        [Sym("stroke"), [Sym("width"), Sym("0.1")], [Sym("type"), Sym("solid")]],
        [Sym("fill"), Sym("none")],
        [Sym("layer"), "Edge.Cuts"],
        [Sym("uuid"), _uid("outline")],
    ])
    tree.append([
        Sym("gr_text"), title,
        [Sym("at"), Sym(_fmt(x0 + 2)), Sym(_fmt(y1 - 2)), Sym("0")],
        [Sym("layer"), "F.SilkS"],
        [Sym("uuid"), _uid("title")],
        [Sym("effects"), [Sym("font"), [Sym("size"), Sym("1"), Sym("1")],
                          [Sym("thickness"), Sym("0.15")]],
         [Sym("justify"), Sym("left"), Sym("bottom")]],
    ])
    return sexpr.dumps(tree) + "\n"


def _footprint_node(comp, placement: Placement,
                    net_numbers: dict[str, int]) -> list:
    fp = placement.footprint
    # deep copy via reparse so we can mutate safely
    node = sexpr.parse(sexpr.dumps(fp.tree))
    node[1] = fp.lib_id

    insert = [
        [Sym("layer"), "F.Cu"],
        [Sym("uuid"), _uid(comp.ref)],
        [Sym("at"), Sym(_fmt(ORIGIN[0] + placement.x)),
         Sym(_fmt(ORIGIN[1] + placement.y)),
         Sym(_fmt(placement.rot))],
    ]
    # strip stale metadata, then splice our header right after the name
    body = [c for c in node[2:]
            if not (isinstance(c, list)
                    and sexpr.tag(c) in ("version", "layer", "uuid", "at",
                                         "tedit", "tstamp"))]
    node[2:] = insert + body

    for prop in sexpr.children(node, "property"):
        if prop[1] == "Reference":
            prop[2] = comp.ref
        elif prop[1] == "Value":
            prop[2] = comp.value
    for fp_text in sexpr.children(node, "fp_text"):
        kind = sexpr.text_of(fp_text)
        if kind == "reference":
            fp_text[2] = comp.ref
        elif kind == "value":
            fp_text[2] = comp.value

    for pad in sexpr.children(node, "pad"):
        pad_no = pad[1] if isinstance(pad[1], str) else pad[1].text
        net = comp.pin_nets.get(pad_no, "")
        if net and net in net_numbers:
            pad.append([Sym("net"), Sym(str(net_numbers[net])), net])
    return node
