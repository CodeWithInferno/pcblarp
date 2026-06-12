from chatpcb.models import Spec
from chatpcb.stages.parts import load_parts_table, match_parts


def test_table_categories_are_valid_catalog_blocks():
    from chatpcb.models import BLOCK_CATALOG

    for row in load_parts_table():
        assert row["catalog_block"] in BLOCK_CATALOG, row


def test_bom_matches_expected_parts(mock_spec_data):
    spec = Spec.model_validate(mock_spec_data)
    result = match_parts(spec)

    mpns = {line.mpn for line in result.bom if line.mpn}
    assert "ESP32-C3-MINI-1-N4" in mpns  # candidate hint "ESP32-C3-MINI-1"
    assert "INMP441" in mpns
    assert "TP4056" in mpns              # LiPo block expands to several roles
    assert "DW01A-G" in mpns
    assert result.unmatched_blocks == []
    assert result.total_cost_usd > 0


def test_lipo_block_expands_to_multiple_roles(mock_spec_data):
    spec = Spec.model_validate(mock_spec_data)
    result = match_parts(spec)
    lipo_roles = {l.role for l in result.bom if l.block_id == "battery"}
    assert {"charger", "protection", "protection_fet", "connector"} <= lipo_roles


def test_unmatched_block_reported_not_fatal(mock_spec_data):
    spec = Spec.model_validate(mock_spec_data)
    table = [r for r in load_parts_table()
             if r["catalog_block"] != "sensor_mic_i2s_mems"]
    result = match_parts(spec, table=table)
    assert "mic" in result.unmatched_blocks
    assert any(l.status == "no_match" for l in result.bom)
