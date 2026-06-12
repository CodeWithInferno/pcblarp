import pytest
from pydantic import ValidationError

from chatpcb.models import BLOCK_CATALOG, Spec


def test_worked_example_validates(mock_spec_data):
    spec = Spec.model_validate(mock_spec_data)
    assert spec.project.name == "ble-voice-streamer"
    assert spec.mcu_requirements.chosen_block == "mcu_esp32_c3"
    assert spec.constraints.max_board_size_mm == (60, 45)


def test_catalog_has_all_prompt_blocks():
    # spot-check a few from each family
    for block in ("mcu_rp2040", "power_boost_5v", "sensor_pir",
                  "ui_vibration_motor", "comm_lora_module", "io_qwiic_connector"):
        assert block in BLOCK_CATALOG


def test_unknown_catalog_block_rejected(mock_spec_data):
    mock_spec_data["blocks"][0]["catalog_block"] = "mcu_fake9000"
    with pytest.raises(ValidationError, match="BLOCK CATALOG"):
        Spec.model_validate(mock_spec_data)


def test_connection_to_unknown_block_rejected(mock_spec_data):
    mock_spec_data["connections"][0]["to_block"] = "ghost_block"
    with pytest.raises(ValidationError, match="unknown block"):
        Spec.model_validate(mock_spec_data)


def test_rail_load_referencing_unknown_block_rejected(mock_spec_data):
    mock_spec_data["power"]["rails"][0]["loads"].append("ghost_block")
    with pytest.raises(ValidationError, match="unknown block"):
        Spec.model_validate(mock_spec_data)


def test_missing_field_rejected(mock_spec_data):
    del mock_spec_data["firmware_outline"]
    with pytest.raises(ValidationError):
        Spec.model_validate(mock_spec_data)
