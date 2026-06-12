"""Pydantic models for the ChatPCB pipeline.

The Spec models mirror the JSON schema embedded in prompts/stage1_spec.md
exactly; if the prompt schema changes, change these together. Validation
errors raised here are fed back to Claude verbatim by the stage 1 retry loop,
so keep the messages descriptive.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Must stay in sync with the BLOCK CATALOG section of prompts/stage1_spec.md.
# Longer term both should be generated from the real block library.
BLOCK_CATALOG = frozenset({
    "mcu_esp32", "mcu_esp32_s3", "mcu_esp32_c3", "mcu_rp2040",
    "mcu_stm32f1", "mcu_atmega328",
    "power_battery_lipo_1s", "power_battery_18650", "power_usb_c_input",
    "power_barrel_jack", "power_ldo_3v3", "power_ldo_5v", "power_buck_3v3",
    "power_boost_5v", "power_soft_latch_button",
    "sensor_mic_i2s_mems", "sensor_mic_analog", "sensor_imu_i2c",
    "sensor_temp_humid_i2c", "sensor_light_i2c", "sensor_hall", "sensor_pir",
    "sensor_adc_generic",
    "ui_button_tactile", "ui_led_status", "ui_led_rgb", "ui_buzzer",
    "ui_oled_i2c_0_96", "ui_tft_spi", "ui_rotary_encoder",
    "ui_vibration_motor",
    "comm_ble_builtin", "comm_wifi_builtin", "comm_lora_module", "comm_nrf24",
    "storage_microsd_spi", "storage_flash_spi",
    "io_usb_serial_bridge", "io_debug_header_swd", "io_qwiic_connector",
})

InterfaceType = Literal["i2s", "i2c", "spi", "uart", "gpio", "adc", "pwm", "usb"]


class Project(BaseModel):
    name: str
    summary: str
    user_prompt_verbatim: str


class Feasibility(BaseModel):
    overall: Literal["viable", "viable_with_caveats", "not_viable_as_stated"]
    notes: str
    risk_flags: list[str]


class Constraints(BaseModel):
    max_board_size_mm: Optional[tuple[float, float]]
    target_battery_life_hours: Optional[float]
    max_unit_cost_usd: Optional[float]
    enclosure_required: bool
    environment: Literal["indoor", "outdoor", "wearable", "unspecified"]


class Rail(BaseModel):
    voltage_v: float
    regulator_block: str
    loads: list[str]


class BudgetRow(BaseModel):
    block: str
    active_ma: float
    sleep_ua: float


class Power(BaseModel):
    source: Literal["battery_lipo_1s", "battery_18650", "usb", "mains_adapter"]
    battery_capacity_mah: Optional[float]
    rails: list[Rail]
    budget_table: list[BudgetRow]
    estimated_active_hours: Optional[float]
    sleep_strategy: Optional[str]


class BlockInterface(BaseModel):
    type: InterfaceType
    pins_required: int


class CandidatePart(BaseModel):
    mpn: str
    verified: bool
    why: str


class Block(BaseModel):
    id: str
    catalog_block: str
    purpose: str
    supply_voltage_v: float
    interfaces: list[BlockInterface]
    params: dict[str, Any]
    candidate_parts: list[CandidatePart]

    @field_validator("catalog_block")
    @classmethod
    def _known_catalog_block(cls, value: str) -> str:
        if value not in BLOCK_CATALOG:
            raise ValueError(
                f"'{value}' is not in the BLOCK CATALOG; use only catalog blocks"
            )
        return value


class Connection(BaseModel):
    from_block: str
    to_block: str
    interface: str
    notes: str


class McuRequirements(BaseModel):
    chosen_block: str
    min_gpio_required: int
    peripherals_required: list[str]
    why: str

    @field_validator("chosen_block")
    @classmethod
    def _known_catalog_block(cls, value: str) -> str:
        if value not in BLOCK_CATALOG:
            raise ValueError(
                f"'{value}' is not in the BLOCK CATALOG; use only catalog blocks"
            )
        return value


class FirmwareOutline(BaseModel):
    behavior_summary: str
    states: list[str]
    key_libraries: list[str]


class Spec(BaseModel):
    spec_version: str
    status: Literal["ok", "needs_clarification", "infeasible_with_catalog"]
    project: Project
    feasibility: Feasibility
    assumptions: list[str]
    clarification_questions: list[str]
    constraints: Constraints
    power: Power
    blocks: list[Block]
    connections: list[Connection]
    mcu_requirements: McuRequirements
    firmware_outline: FirmwareOutline
    out_of_scope_dependencies: list[str]
    test_plan_bringup: list[str]

    @model_validator(mode="after")
    def _check_block_references(self) -> "Spec":
        ids = [b.id for b in self.blocks]
        id_set = set(ids)
        if len(id_set) != len(ids):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"duplicate block ids: {dupes}")
        for conn in self.connections:
            for endpoint in (conn.from_block, conn.to_block):
                if endpoint not in id_set:
                    raise ValueError(
                        f"connection references unknown block id '{endpoint}'"
                    )
        for rail in self.power.rails:
            for load in rail.loads:
                if load not in id_set:
                    raise ValueError(
                        f"power rail {rail.voltage_v}V lists unknown block id '{load}' in loads"
                    )
        for row in self.power.budget_table:
            if row.block not in id_set:
                raise ValueError(
                    f"power budget_table references unknown block id '{row.block}'"
                )
        return self


# ---------------------------------------------------------------------------
# Stage 2 (parts) result models
# ---------------------------------------------------------------------------

class BomLine(BaseModel):
    block_id: str
    catalog_block: str
    role: str
    mpn: Optional[str]
    lcsc: Optional[str]
    description: str
    package: Optional[str]
    qty: int
    unit_price_usd: Optional[float]
    status: Literal["matched", "no_match", "integrated"]


class PartsResult(BaseModel):
    bom: list[BomLine]
    unmatched_blocks: list[str]
    total_cost_usd: float
    # Design-rule / selection context pulled from the Senso knowledge layer
    # when blocks could not be matched; feeds the spec revision prompt.
    kb_notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Pipeline run state (what the API/frontend poll)
# ---------------------------------------------------------------------------

STAGE_ORDER: tuple[str, ...] = ("spec", "parts", "schematic", "layout", "export")


class StageRecord(BaseModel):
    name: str
    status: Literal["pending", "running", "ok", "failed", "skipped"] = "pending"
    attempts: int = 0
    duration_ms: float = 0.0
    error: Optional[str] = None
    metrics: dict[str, float] = Field(default_factory=dict)
    artifacts: dict[str, str] = Field(default_factory=dict)  # name -> URL


class RunState(BaseModel):
    run_id: str
    idea: str
    status: Literal["queued", "running", "done", "partial", "failed"] = "queued"
    created_at: str
    stages: list[StageRecord]
    spec: Optional[Spec] = None
    bom: Optional[PartsResult] = None
    revision_count: int = 0
    events: list[str] = Field(default_factory=list)
