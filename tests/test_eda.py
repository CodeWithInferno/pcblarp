"""Tests for the real EDA pipeline (library, circuits, schematic, board,
gerbers). These instantiate every block circuit against the vendored KiCad
library, so a library refresh that renames pins or footprints fails here
rather than mid-pipeline."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from chatpcb.eda import library, sexpr
from chatpcb.eda.blocks import CIRCUITS
from chatpcb.eda.board_gen import build_board, generate_board
from chatpcb.eda.gerber import write_gerbers
from chatpcb.eda.netlist import DesignError, assembly_bom, build_design
from chatpcb.eda.schematic_gen import generate_schematic
from chatpcb.models import Spec

MOCK_SPEC = Path(__file__).parent.parent / "data" / "mock_spec.json"


@pytest.fixture(scope="module")
def design():
    spec = Spec.model_validate_json(MOCK_SPEC.read_text())
    return build_design(spec)


@pytest.fixture(scope="module")
def spec():
    return Spec.model_validate_json(MOCK_SPEC.read_text())


def test_every_circuit_resolves_against_vendored_library():
    """All pin selectors and footprints in blocks.py must exist."""
    for name, circuit in CIRCUITS.items():
        for part in circuit.parts:
            symbol = library.load_symbol(part.symbol)
            footprint = part.footprint or symbol.default_footprint
            assert footprint, f"{name}: {part.symbol} has no footprint"
            library.load_footprint(footprint)
            for selector in part.pins:
                if selector.startswith("n:"):
                    assert symbol.pins_named(selector[2:]), \
                        f"{name}: {part.symbol} has no pin named {selector[2:]}"
                else:
                    symbol.pin(selector)  # raises if missing


def test_mcu_fixed_and_pool_pins_exist():
    for name, circuit in CIRCUITS.items():
        if not circuit.is_mcu:
            continue
        symbol = library.load_symbol(circuit.parts[0].symbol)
        names = {p.name for p in symbol.pins}
        for iface, pins in circuit.fixed.items():
            for pin in pins:
                assert pin in names, f"{name}: fixed {iface} pin {pin} missing"
        for pin in circuit.pool:
            assert pin in names, f"{name}: pool pin {pin} missing"


def test_design_builds_clean_from_mock_spec(design):
    assert not design.erc_errors
    assert len(design.components) > 20
    # every multi-pin net has at least two members or is flagged
    assert "GND" in design.nets and len(design.nets["GND"]) > 10
    assert "+3V3" in design.nets


def test_unsupported_block_feeds_back_supported_list(spec):
    bad = spec.model_copy(deep=True)
    bad.blocks[0].catalog_block = "mcu_rp2040"
    with pytest.raises(DesignError) as err:
        build_design(bad)
    assert "mcu_rp2040" in str(err.value)
    assert "mcu_esp32" in err.value.llm_feedback  # offers alternatives


def test_schematic_parses_and_labels_sit_on_pins(design):
    sch = generate_schematic(design, "test")
    tree = sexpr.parse(sch)
    instances = sexpr.children(tree, "symbol")
    labels = sexpr.children(tree, "global_label")
    ncs = sexpr.children(tree, "no_connect")
    assert len(instances) == len(design.components)
    total_pins = sum(
        len(library.load_symbol(c.lib_id).pins) for c in design.components
    )
    assert len(labels) + len(ncs) == total_pins
    # embedded symbol defs cover every lib_id used
    embedded = {s[1] for s in
                sexpr.children(sexpr.child(tree, "lib_symbols"), "symbol")}
    assert {c.lib_id for c in design.components} <= embedded


def test_board_places_all_components_with_real_nets(design, spec):
    board = build_board(design, spec.constraints.max_board_size_mm)
    assert not board.violations
    assert len(board.placements) == len(design.components)
    pcb = generate_board(design, board, "test")
    tree = sexpr.parse(pcb)
    fps = sexpr.children(tree, "footprint")
    assert len(fps) == len(design.components)
    netted = sum(1 for f in fps for p in sexpr.children(f, "pad")
                 if sexpr.child(p, "net"))
    assert netted > 50
    assert sexpr.children(tree, "gr_rect"), "missing Edge.Cuts outline"


def test_board_too_small_reports_violation(design):
    board = build_board(design, (20.0, 20.0))
    assert board.violations
    assert "board_outline" in board.violations[0]


def test_gerbers_are_valid_rs274x(design, spec, tmp_path):
    board = build_board(design, spec.constraints.max_board_size_mm)
    files = write_gerbers(design, board, "test", tmp_path)
    names = set(files)
    assert {"test-F_Cu.gtl", "test-B_Cu.gbl", "test-F_Mask.gts",
            "test-Edge_Cuts.gm1", "test-PTH.drl"} <= names
    top = files["test-F_Cu.gtl"].read_text()
    assert top.startswith("%TF")
    assert "%FSLAX46Y46*%" in top and "%MOMM*%" in top
    assert top.rstrip().endswith("M02*")
    assert top.count("D03*") > 50  # plenty of pad flashes
    drl = files["test-PTH.drl"].read_text()
    assert drl.startswith("M48")
    assert drl.rstrip().endswith("M30")


def test_assembly_bom_covers_every_component(design):
    rows = assembly_bom(design)
    total = sum(row["qty"] for row in rows)
    assert total == len(design.components)


def test_prompt_catalog_only_advertises_buildable_blocks():
    """Every block in the stage-1 prompt's BLOCK CATALOG must have a real
    circuit, so Claude can never pick one the schematic stage rejects."""
    from chatpcb.models import BLOCK_CATALOG
    prompt = (Path(__file__).parent.parent / "prompts" /
              "stage1_spec.md").read_text()
    section = prompt.split("# BLOCK CATALOG")[1].split("# JSON SCHEMA")[0]
    advertised = {
        token for token in
        section.replace("|", " ").split()
        if token in BLOCK_CATALOG
    }
    assert advertised, "failed to parse any blocks out of the prompt"
    missing = advertised - set(CIRCUITS)
    assert not missing, f"prompt advertises blocks without circuits: {missing}"
