"""Vendor the KiCad official library components ChatPCB's block circuits use.

Downloads symbol libraries and footprints from the official KiCad GitLab
repos at a pinned release tag, extracts exactly the symbols we need
(flattening `extends` inheritance so every vendored symbol is standalone),
and writes them under data/kicad_library/:

    data/kicad_library/symbols/<Lib>/<Name>.kicad_sym   (one symbol per file)
    data/kicad_library/footprints/<Lib>.pretty/<Name>.kicad_mod
    data/kicad_library/manifest.json

The KiCad libraries are licensed CC-BY-SA 4.0 with the KiCad Libraries
Exception (use in designs is unrestricted); manifest.json records provenance.

Run: .venv/bin/python scripts/fetch_kicad_library.py
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from chatpcb.eda import sexpr  # noqa: E402

TAG = "9.0.9"
API = "https://gitlab.com/api/v4/projects"
SYM_PROJECT = "kicad%2Flibraries%2Fkicad-symbols"
FP_PROJECT = "kicad%2Flibraries%2Fkicad-footprints"
CACHE = Path("/tmp/chatpcb_kicad_cache")
OUT = REPO_ROOT / "data" / "kicad_library"

# (symbol lib, symbol name). Footprints come from each symbol's default
# Footprint property where set; generic symbols get them assigned in
# chatpcb/eda/blocks.py instead.
SYMBOLS = [
    ("Device", "R"),
    ("Device", "C"),
    ("Device", "L"),
    ("Device", "LED"),
    ("Device", "Battery_Cell"),
    ("Transistor_FET", "Q_PMOS_GSD"),
    ("Transistor_BJT", "Q_NPN_BEC"),
    ("Device", "D"),
    ("Device", "Buzzer"),
    ("RF_Module", "ESP32-WROOM-32"),
    ("RF_Module", "ESP32-C3-WROOM-02"),
    ("RF_Module", "ESP32-S3-MINI-1"),
    ("Sensor_Motion", "MPU-6050"),
    ("Sensor_Humidity", "SHT31-DIS"),
    ("Sensor_Audio", "SPH0645LM4H"),
    ("Sensor_Audio", "ICS-43434"),
    ("Regulator_Linear", "AMS1117-3.3"),
    ("Regulator_Switching", "AP63203WU"),
    ("Interface_USB", "CP2102N-Axx-xQFN24"),
    ("Battery_Management", "MCP73831-2-OT"),
    ("Memory_Flash", "W25Q32JVSS"),
    ("Connector", "USB_C_Receptacle_USB2.0_16P"),
    ("Connector", "Barrel_Jack_Switch"),
    ("Connector_Generic", "Conn_01x02"),
    ("Connector_Generic", "Conn_01x04"),
    ("Connector_Generic", "Conn_02x05_Odd_Even"),
    ("LED", "WS2812B"),
    ("Switch", "SW_Push"),
]

# Footprints needed beyond the symbols' default Footprint properties:
# generic passives/connectors where the circuit code picks the package.
EXTRA_FOOTPRINTS = [
    ("Resistor_SMD", "R_0603_1608Metric"),
    ("Capacitor_SMD", "C_0603_1608Metric"),
    ("Capacitor_SMD", "C_0805_2012Metric"),
    ("Inductor_SMD", "L_1210_3225Metric"),
    ("LED_SMD", "LED_0603_1608Metric"),
    ("Diode_SMD", "D_SOD-123"),
    ("Package_TO_SOT_SMD", "SOT-23"),
    ("Package_TO_SOT_SMD", "SOT-23-5"),
    ("Button_Switch_SMD", "SW_SPST_PTS645Sx43SMTR92"),
    ("Battery", "BatteryHolder_Keystone_1042_1x18650"),
    ("Connector_JST", "JST_SH_BM04B-SRSS-TB_1x04-1MP_P1.00mm_Vertical"),
    ("Connector_JST", "JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical"),
    ("Connector_PinHeader_2.54mm", "PinHeader_1x04_P2.54mm_Vertical"),
    ("Connector_PinHeader_1.27mm", "PinHeader_2x05_P1.27mm_Vertical"),
    ("Connector_BarrelJack", "BarrelJack_Horizontal"),
    ("Buzzer_Beeper", "Buzzer_12x9.5RM7.6"),
    ("Connector_USB", "USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal"),
]


def fetch(project: str, path: str) -> bytes:
    quoted = urllib.parse.quote(path, safe="")
    url = f"{API}/{project}/repository/files/{quoted}/raw?ref={TAG}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read()


def fetch_symbol_lib(lib: str) -> list | None:
    cached = CACHE / f"{lib}.kicad_sym"
    if not cached.exists():
        try:
            data = fetch(SYM_PROJECT, f"{lib}.kicad_sym")
        except Exception as exc:  # noqa: BLE001
            print(f"  !! symbol lib {lib}: {exc}")
            return None
        CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(data)
    return sexpr.parse(cached.read_text())


def lib_symbols(tree: list) -> dict[str, list]:
    return {
        node[1]: node
        for node in sexpr.children(tree, "symbol")
        if len(node) > 1 and isinstance(node[1], str)
    }


def flatten(name: str, table: dict[str, list]) -> list:
    """Resolve (extends "Parent") so the symbol is standalone."""
    node = table[name]
    ext = sexpr.child(node, "extends")
    if ext is None:
        return node
    parent = flatten(sexpr.first_atom(ext), table)
    merged: list = [node[0], name]
    child_props = {p[1]: p for p in sexpr.children(node, "property")}
    seen_props = set()
    skip = {"extends"}
    # Child's own scalar settings win; fall back to parent's.
    child_tags = {sexpr.tag(c) for c in node if isinstance(c, list)}
    for item in parent[2:]:
        t = sexpr.tag(item)
        if t == "property":
            prop = child_props.get(item[1], item)
            seen_props.add(item[1])
            merged.append(prop)
        elif t == "symbol":
            # rename unit "Parent_0_1" -> "Child_0_1"
            unit = list(item)
            if isinstance(unit[1], str) and unit[1].startswith(parent[1]):
                unit[1] = name + unit[1][len(parent[1]):]
            merged.append(unit)
        elif t in child_tags or t in skip:
            continue
        else:
            merged.append(item)
    for item in node[2:]:
        t = sexpr.tag(item)
        if t in skip:
            continue
        if t == "property":
            if item[1] not in seen_props:
                merged.append(item)
        elif t == "symbol":
            merged.append(item)  # child-defined units (rare)
        else:
            merged.append(item)
    return merged


def strip_tokens(node: list, names: set[str]) -> list:
    return [
        strip_tokens(c, names) if isinstance(c, list) else c
        for c in node
        if not (isinstance(c, list) and sexpr.tag(c) in names)
    ]


def main() -> int:
    missing: list[str] = []
    manifest: dict = {
        "source_tag": TAG,
        "license": "CC-BY-SA 4.0 with KiCad Libraries Exception",
        "symbols": [],
        "footprints": [],
    }
    footprints: list[tuple[str, str]] = list(EXTRA_FOOTPRINTS)

    lib_cache: dict[str, dict[str, list] | None] = {}
    for lib, name in SYMBOLS:
        if lib not in lib_cache:
            tree = fetch_symbol_lib(lib)
            lib_cache[lib] = lib_symbols(tree) if tree else None
        table = lib_cache[lib]
        if table is None:
            missing.append(f"symbol-lib {lib}")
            continue
        if name not in table:
            close = [n for n in table if name.split("-")[0].lower() in n.lower()]
            print(f"  !! {lib}:{name} not found; near: {close[:6]}")
            missing.append(f"symbol {lib}:{name}")
            continue
        node = flatten(name, table)
        node = strip_tokens(node, {"embedded_fonts"})
        out_path = OUT / "symbols" / lib / f"{name}.kicad_sym"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        wrapper = [
            Sym := sexpr.Sym("kicad_symbol_lib"),
            [sexpr.Sym("version"), sexpr.Sym("20241209")],
            [sexpr.Sym("generator"), "chatpcb_fetch"],
            node,
        ]
        out_path.write_text(sexpr.dumps(wrapper) + "\n")
        manifest["symbols"].append(f"{lib}:{name}")
        # Pull the default footprint, e.g. "RF_Module:ESP32-WROOM-32".
        prop = next(
            (p for p in sexpr.children(node, "property") if p[1] == "Footprint"),
            None,
        )
        if prop and isinstance(prop[2], str) and ":" in prop[2]:
            fp_lib, fp_name = prop[2].split(":", 1)
            if (fp_lib, fp_name) not in footprints:
                footprints.append((fp_lib, fp_name))

    for fp_lib, fp_name in footprints:
        out_path = OUT / "footprints" / f"{fp_lib}.pretty" / f"{fp_name}.kicad_mod"
        if not out_path.exists():
            try:
                data = fetch(FP_PROJECT, f"{fp_lib}.pretty/{fp_name}.kicad_mod")
            except Exception as exc:  # noqa: BLE001
                print(f"  !! footprint {fp_lib}:{fp_name}: {exc}")
                missing.append(f"footprint {fp_lib}:{fp_name}")
                continue
            tree = sexpr.parse(data.decode())
            tree = strip_tokens(
                tree, {"embedded_fonts", "generator", "generator_version"}
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(sexpr.dumps(tree) + "\n")
        manifest["footprints"].append(f"{fp_lib}:{fp_name}")

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"vendored {len(manifest['symbols'])} symbols, "
          f"{len(manifest['footprints'])} footprints -> {OUT}")
    if missing:
        print("MISSING:")
        for m in missing:
            print(f"  - {m}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
