# PCBWay manufacturing capabilities (design rules)

Summarized for prompt context (Senso knowledge layer); verify against the
live pcbway.com capabilities page before ordering.

## Overview and stack-up

Standard FR-4 service: 1 to 14 layers, board size up to 500x1100mm, board
thickness 0.2 to 3.2mm (1.6mm default). 2-layer boards are the cheapest and
fastest tier; 4-layer adds internal power/ground planes, recommended once a
design has an MCU plus radio plus switching regulators.

## Trace width and spacing

Minimum trace width and spacing: 0.1mm/0.1mm (4mil) on the advanced tier;
use 0.15mm (6mil) or wider for the standard tier and best yield. For 2oz
copper, keep traces and gaps at 0.2mm (8mil) or wider. Power traces: 1oz
copper carries roughly 1A per 0.4mm of width with a 10C rise; size battery
charge paths and regulator outputs accordingly.

## Drills, vias, and annular rings

Minimum drill 0.2mm, maximum 6.3mm. Via pad diameter at least drill +
0.25mm (0.45mm pad for a 0.2mm drill). Annular ring at least 0.15mm (6mil).
Via-in-pad requires the plugged/capped via option. Castellated holes and
half-holes are supported as an extra option for module-style boards.

## Clearances and board outline

Copper to board edge: 0.3mm minimum for routed outlines, 0.4mm recommended.
Hole-to-hole clearance 0.25mm. Keep tall components 1mm from V-cut lines.
Slots minimum width 0.8mm routed.

## Soldermask and silkscreen

Soldermask dam minimum 0.1mm (green); other colors need 0.12mm. Soldermask
opening 0.05mm larger than the pad per side. Silkscreen line width minimum
0.15mm, text height minimum 0.8mm; keep silkscreen off pads.

## Surface finish and copper weight

HASL (leaded/lead-free) is default; ENIG recommended for fine-pitch QFN/BGA
and castellated modules. Outer copper 1oz standard, up to 13oz heavy copper
as an option; inner layers 0.5 to 2oz.

## Assembly (SMT service)

Minimum part size 0201; minimum BGA/QFN pitch 0.35mm with ENIG. Provide BOM
with MPN + LCSC part numbers and a pick-and-place file (Ref, Val, Package,
PosX, PosY, Rot, Side). Add at least 3 fiducials for boards with fine-pitch
parts. Parts on both sides increase cost; prefer single-side placement for
small runs.

## RF and antenna guidance

Modules with integrated antennas (ESP32-WROOM/MINI series) need a copper
keepout under and around the antenna area per the module datasheet; keep the
antenna edge on the board edge. Discrete RF (LoRa, nRF24 with external
antenna) at 50 ohm needs controlled impedance, which is an optional service
(+/-10% tolerance) and requires a defined stack-up; prefer integrated-antenna
modules unless RF layout expertise is available.

## Battery and power safety

LiPo charge/protection circuits: keep charger IC thermal pad stitched to a
copper pour, protection FETs close to the cell connector, and charge-path
traces sized for the full charge current. Do not route high-current battery
paths under RF antennas or crystals.
