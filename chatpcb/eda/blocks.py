"""Block circuit library: catalog block id -> real components and wiring.

Each catalog block that the EDA pipeline supports maps to a CircuitDef:
a list of real parts (KiCad symbol + footprint + value) with pin-level
wiring. Net specs in PartDef.pins:

    "GND" / "+3V3" / "VBUS" / "VBAT" / ...  global net
    "SYS_IN"   regulator input; the netlist engine rewrites it to the
               actual system source (VBAT_SW / VBAT / VBUS / VIN)
    "$x"       block-local net (instantiated as "<block_id>.x")
    "@PORT"    exported port, joined to other blocks by the engine
    "NC"       explicit no-connect

Pin selectors are either a pin number ("3") or "n:NAME" which matches every
pin with that name (e.g. "n:GND" hits all ESP32 ground pins). Symbol pins
not mentioned and not allocated by the engine become no-connects.

Pin wiring here was written against the vendored 9.0.9 symbols; the test
suite instantiates every circuit so a library change that renames pins
fails loudly.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PartDef:
    ref: str                      # reference prefix: R, C, U, J, ...
    symbol: str                   # "Lib:Name" in the vendored library
    value: str
    pins: dict                    # selector -> net spec
    footprint: str = ""           # "" -> symbol's default Footprint property


@dataclass
class CircuitDef:
    parts: list[PartDef]
    groups: dict[str, list[str]] = field(default_factory=dict)
    # interface type -> ordered exported port names, e.g. {"i2c": ["SDA","SCL"]}
    provides: str = ""            # global net this block sources: VBAT/VBUS/VIN/+3V3
    is_mcu: bool = False
    fixed: dict = field(default_factory=dict)
    # MCU only: interface -> tuple of symbol pin NAMES, e.g. "i2c": ("IO21","IO22")
    pool: list[str] = field(default_factory=list)
    # MCU only: allocatable GPIO pin names, in preferred order
    notes: list[str] = field(default_factory=list)


R_0603 = "Resistor_SMD:R_0603_1608Metric"
C_0603 = "Capacitor_SMD:C_0603_1608Metric"
C_0805 = "Capacitor_SMD:C_0805_2012Metric"
LED_0603 = "LED_SMD:LED_0603_1608Metric"
D_SOD123 = "Diode_SMD:D_SOD-123"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
BTN_FP = "Button_Switch_SMD:SW_SPST_PTS645Sx43SMTR92"


def _r(value: str, a: str, b: str) -> PartDef:
    return PartDef("R", "Device:R", value, {"1": a, "2": b}, R_0603)


def _c(value: str, a: str, b: str, fp: str = C_0603) -> PartDef:
    return PartDef("C", "Device:C", value, {"1": a, "2": b}, fp)


def _esp32_support(boot_io: str) -> list[PartDef]:
    """EN R-C reset circuit, boot strap pull-up + button, supply decoupling."""
    return [
        _r("10k", "+3V3", "$EN"),
        _c("1uF", "$EN", "GND"),
        _r("10k", "+3V3", "$BOOT"),
        PartDef("SW", "Switch:SW_Push", "BOOT", {"1": "$BOOT", "2": "GND"}, BTN_FP),
        _c("10uF", "+3V3", "GND", C_0805),
        _c("100nF", "+3V3", "GND"),
    ], boot_io


CIRCUITS: dict[str, CircuitDef] = {}


def _define(name: str, circuit: CircuitDef) -> None:
    CIRCUITS[name] = circuit


# --------------------------------------------------------------------------
# MCUs
# --------------------------------------------------------------------------

_support, _boot = _esp32_support("IO0")
_define("mcu_esp32", CircuitDef(
    parts=[
        PartDef("U", "RF_Module:ESP32-WROOM-32", "ESP32-WROOM-32", {
            "n:VDD": "+3V3", "n:GND": "GND", "n:EN": "$EN", f"n:{_boot}": "$BOOT",
        }),
        *_support,
    ],
    is_mcu=True,
    fixed={
        "i2c": ("IO21", "IO22"),
        "uart": ("TXD0/IO1", "RXD0/IO3"),
    },
    pool=["IO4", "IO16", "IO17", "IO5", "IO18", "IO19", "IO23", "IO13",
          "IO14", "IO27", "IO26", "IO25", "IO32", "IO33"],
    notes=["boot: hold BOOT button (IO0) low while resetting to enter the "
           "serial bootloader; no auto-program transistors are fitted"],
))

_support, _boot = _esp32_support("IO9")
_define("mcu_esp32_c3", CircuitDef(
    parts=[
        PartDef("U", "RF_Module:ESP32-C3-WROOM-02", "ESP32-C3-WROOM-02", {
            "n:3V3": "+3V3", "n:GND": "GND", "n:EN": "$EN", f"n:{_boot}": "$BOOT",
        }),
        *_support,
    ],
    is_mcu=True,
    fixed={
        "i2c": ("IO1", "IO2"),
        "uart": ("IO21/TXD", "IO20/RXD"),
        "usb": ("IO19", "IO18"),       # (D+, D-) native USB
    },
    pool=["IO4", "IO5", "IO6", "IO7", "IO10", "IO3", "IO0", "IO19", "IO18"],
))

_support, _boot = _esp32_support("IO0")
_define("mcu_esp32_s3", CircuitDef(
    parts=[
        PartDef("U", "RF_Module:ESP32-S3-MINI-1", "ESP32-S3-MINI-1", {
            "n:3V3": "+3V3", "n:GND": "GND", "n:EN": "$EN", f"n:{_boot}": "$BOOT",
        }),
        *_support,
    ],
    is_mcu=True,
    fixed={
        "i2c": ("IO8", "IO9"),
        "uart": ("TXD0", "RXD0"),
        "usb": ("USB_D+", "USB_D-"),
    },
    pool=["IO1", "IO2", "IO4", "IO5", "IO6", "IO7", "IO10", "IO11", "IO12",
          "IO13", "IO14", "IO15", "IO16", "IO17", "IO18", "IO21"],
))

# --------------------------------------------------------------------------
# Power
# --------------------------------------------------------------------------

_define("power_battery_18650", CircuitDef(
    parts=[
        PartDef("BT", "Device:Battery_Cell", "18650", {"1": "VBAT", "2": "GND"},
                "Battery:BatteryHolder_Keystone_1042_1x18650"),
    ],
    provides="VBAT",
    notes=["no charge circuit on board: charge the cell externally"],
))

_define("power_battery_lipo_1s", CircuitDef(
    parts=[
        PartDef("J", "Connector_Generic:Conn_01x02", "BATT_JST-PH",
                {"1": "VBAT", "2": "GND"},
                "Connector_JST:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical"),
        PartDef("U", "Battery_Management:MCP73831-2-OT", "MCP73831-2", {
            "4": "VBUS", "2": "GND", "3": "VBAT", "5": "$PROG", "1": "$STAT",
        }),
        _r("2k", "$PROG", "GND"),
        _r("1k", "VBUS", "$CHG_A"),
        PartDef("D", "Device:LED", "CHG", {"2": "$CHG_A", "1": "$STAT"}, LED_0603),
        _c("4.7uF", "VBUS", "GND", C_0805),
        _c("4.7uF", "VBAT", "GND", C_0805),
    ],
    provides="VBAT",
    notes=["MCP73831 charges at ~500mA from VBUS; needs a power_usb_c_input "
           "block to supply VBUS"],
))

_define("power_usb_c_input", CircuitDef(
    parts=[
        PartDef("J", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C", {
            "n:VBUS": "VBUS", "n:GND": "GND", "n:SHIELD": "GND",
            "n:CC1": "$CC1", "n:CC2": "$CC2",
            "n:D+": "@DP", "n:D-": "@DM",
        }, "Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal"),
        _r("5.1k", "$CC1", "GND"),
        _r("5.1k", "$CC2", "GND"),
    ],
    groups={"usb": ["DP", "DM"]},
    provides="VBUS",
))

_define("power_barrel_jack", CircuitDef(
    parts=[
        PartDef("J", "Connector:Barrel_Jack_Switch", "DC_IN",
                {"1": "VIN", "2": "GND"},
                "Connector_BarrelJack:BarrelJack_Horizontal"),
    ],
    provides="VIN",
))

_define("power_ldo_3v3", CircuitDef(
    parts=[
        PartDef("U", "Regulator_Linear:AMS1117-3.3", "AMS1117-3.3",
                {"3": "SYS_IN", "2": "+3V3", "1": "GND"}),
        _c("10uF", "SYS_IN", "GND", C_0805),
        _c("10uF", "+3V3", "GND", C_0805),
    ],
    provides="+3V3",
))

_define("power_buck_3v3", CircuitDef(
    parts=[
        PartDef("U", "Regulator_Switching:AP63203WU", "AP63203", {
            "3": "SYS_IN", "2": "SYS_IN", "4": "GND",
            "5": "$SW", "6": "$BST", "1": "+3V3",
        }),
        _c("100nF", "$BST", "$SW"),
        PartDef("L", "Device:L", "4.7uH", {"1": "$SW", "2": "+3V3"},
                "Inductor_SMD:L_1210_3225Metric"),
        _c("10uF", "SYS_IN", "GND", C_0805),
        _c("22uF", "+3V3", "GND", C_0805),
        _c("22uF", "+3V3", "GND", C_0805),
    ],
    provides="+3V3",
))

_define("power_soft_latch_button", CircuitDef(
    parts=[
        PartDef("Q", "Transistor_FET:Q_PMOS_GSD", "PMOS",
                {"1": "$G", "2": "VBAT", "3": "VBAT_SW"}, SOT23),
        _r("100k", "VBAT", "$G"),
        PartDef("D", "Device:D", "1N4148W", {"2": "$G", "1": "$BTN"}, D_SOD123),
        PartDef("SW", "Switch:SW_Push", "PWR", {"1": "$BTN", "2": "GND"}, BTN_FP),
        _r("100k", "VBAT", "$BTN"),
        PartDef("Q", "Transistor_BJT:Q_NPN_BEC", "MMBT3904",
                {"1": "$B", "2": "GND", "3": "$G"}, SOT23),
        _r("10k", "@HOLD", "$B"),
        _r("100k", "$BTN", "@SENSE"),
    ],
    groups={"gpio": ["HOLD", "SENSE"]},
    notes=["press: PMOS gate pulled low through D, system powers on; firmware "
           "must drive HOLD high to latch, drop it to power off; SENSE reads "
           "the button through 100k"],
))

# --------------------------------------------------------------------------
# Sensors
# --------------------------------------------------------------------------

_define("sensor_imu_i2c", CircuitDef(
    parts=[
        PartDef("U", "Sensor_Motion:MPU-6050", "MPU-6050", {
            "13": "+3V3", "8": "+3V3", "18": "GND", "9": "GND",
            "11": "GND", "1": "GND",
            "23": "@SCL", "24": "@SDA", "10": "$REG", "20": "$CP",
        }),
        _c("100nF", "+3V3", "GND"),
        _c("100nF", "$REG", "GND"),
        _c("2.2nF", "$CP", "GND"),
    ],
    groups={"i2c": ["SDA", "SCL"]},
))

_define("sensor_temp_humid_i2c", CircuitDef(
    parts=[
        PartDef("U", "Sensor_Humidity:SHT31-DIS", "SHT31-DIS", {
            "1": "@SDA", "4": "@SCL", "5": "+3V3", "n:VSS": "GND",
            "2": "GND", "7": "GND",
        }),
        _c("100nF", "+3V3", "GND"),
    ],
    groups={"i2c": ["SDA", "SCL"]},
))

_define("sensor_pir", CircuitDef(
    parts=[
        PartDef("J", "Connector_Generic:Conn_01x03", "PIR_AM312",
                {"1": "+3V3", "2": "@OUT", "3": "GND"},
                "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"),
    ],
    groups={"gpio": ["OUT"]},
    notes=["header for a 3.3V PIR module (AM312-class); 5V-only HC-SR501 "
           "modules need the 5V rail"],
))

_define("sensor_adc_generic", CircuitDef(
    parts=[
        PartDef("J", "Connector_Generic:Conn_01x03", "ANALOG_IN",
                {"1": "+3V3", "2": "@SIG", "3": "GND"},
                "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"),
    ],
    groups={"adc": ["SIG"], "gpio": ["SIG"]},
    notes=["generic analog sensor header; keep the signal within 0-3.3V"],
))

_define("sensor_mic_i2s_mems", CircuitDef(
    parts=[
        PartDef("U", "Sensor_Audio:ICS-43434", "ICS-43434", {
            "1": "@WS", "4": "@BCLK", "6": "@SD",
            "2": "GND", "5": "+3V3", "3": "GND",
        }),
        _c("100nF", "+3V3", "GND"),
    ],
    groups={"i2s": ["BCLK", "WS", "SD"]},
))

# --------------------------------------------------------------------------
# UI
# --------------------------------------------------------------------------

_define("ui_button_tactile", CircuitDef(
    parts=[
        PartDef("SW", "Switch:SW_Push", "BTN", {"1": "@OUT", "2": "GND"}, BTN_FP),
        _r("10k", "+3V3", "@OUT"),
    ],
    groups={"gpio": ["OUT"]},
))

_define("ui_led_status", CircuitDef(
    parts=[
        _r("1k", "@CTRL", "$A"),
        PartDef("D", "Device:LED", "LED", {"2": "$A", "1": "GND"}, LED_0603),
    ],
    groups={"gpio": ["CTRL"], "pwm": ["CTRL"]},
))

_define("ui_led_rgb", CircuitDef(
    parts=[
        PartDef("D", "LED:WS2812B", "WS2812B", {
            "1": "+3V3", "3": "GND", "4": "@DIN", "2": "NC",
        }),
        _c("100nF", "+3V3", "GND"),
    ],
    groups={"gpio": ["DIN"], "pwm": ["DIN"]},
    notes=["WS2812B run at 3.3V supply so the 3.3V data input stays in spec"],
))

_define("ui_buzzer", CircuitDef(
    parts=[
        PartDef("BZ", "Device:Buzzer", "BUZZER", {"1": "+3V3", "2": "$C"},
                "Buzzer_Beeper:Buzzer_12x9.5RM7.6"),
        PartDef("D", "Device:D", "1N4148W", {"1": "+3V3", "2": "$C"}, D_SOD123),
        PartDef("Q", "Transistor_BJT:Q_NPN_BEC", "MMBT3904",
                {"1": "$B", "2": "GND", "3": "$C"}, SOT23),
        _r("1k", "@CTRL", "$B"),
    ],
    groups={"gpio": ["CTRL"], "pwm": ["CTRL"]},
))

_define("ui_oled_i2c_0_96", CircuitDef(
    parts=[
        PartDef("J", "Connector_Generic:Conn_01x04", "OLED_0.96",
                {"1": "GND", "2": "+3V3", "3": "@SCL", "4": "@SDA"},
                "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"),
    ],
    groups={"i2c": ["SDA", "SCL"]},
    notes=["header for a standard 0.96\" SSD1306 module (GND/VCC/SCL/SDA)"],
))

# --------------------------------------------------------------------------
# IO / comm / storage
# --------------------------------------------------------------------------

_define("io_qwiic_connector", CircuitDef(
    parts=[
        PartDef("J", "Connector_Generic:Conn_01x04", "QWIIC",
                {"1": "GND", "2": "+3V3", "3": "@SDA", "4": "@SCL"},
                "Connector_JST:JST_SH_BM04B-SRSS-TB_1x04-1MP_P1.00mm_Vertical"),
    ],
    groups={"i2c": ["SDA", "SCL"], "gpio": ["SDA", "SCL"]},
))

_define("io_usb_serial_bridge", CircuitDef(
    parts=[
        PartDef("U", "Interface_USB:CP2102N-Axx-xQFN24", "CP2102N-A02-GQFN24", {
            "7": "VBUS", "8": "VBUS", "6": "$VDD", "5": "$VDD",
            "3": "@DP", "4": "@DM", "21": "@TXD", "20": "@RXD",
            "n:GND": "GND",
        }),
        _c("4.7uF", "VBUS", "GND", C_0805),
        _c("4.7uF", "$VDD", "GND", C_0805),
        _c("100nF", "$VDD", "GND"),
    ],
    groups={"uart": ["TXD", "RXD"], "usb": ["DP", "DM"]},
    notes=["no auto-program transistors: use the BOOT button for flashing"],
))

_define("io_debug_header_swd", CircuitDef(
    parts=[
        PartDef("J", "Connector_Generic:Conn_02x05_Odd_Even", "SWD", {
            "1": "+3V3", "2": "@SWDIO", "3": "GND", "4": "@SWCLK",
            "5": "GND", "9": "GND", "10": "@NRST",
        }, "Connector_PinHeader_1.27mm:PinHeader_2x05_P1.27mm_Vertical"),
    ],
    groups={"gpio": ["SWDIO", "SWCLK", "NRST"]},
))

_define("storage_flash_spi", CircuitDef(
    parts=[
        PartDef("U", "Memory_Flash:W25Q32JVSS", "W25Q32JV", {
            "8": "+3V3", "4": "GND", "1": "@CS", "6": "@SCK",
            "5": "@MOSI", "2": "@MISO", "3": "+3V3", "7": "+3V3",
        }),
        _c("100nF", "+3V3", "GND"),
    ],
    groups={"spi": ["SCK", "MOSI", "MISO", "CS"]},
))

_define("comm_ble_builtin", CircuitDef(parts=[]))
_define("comm_wifi_builtin", CircuitDef(parts=[]))


def supported_blocks() -> list[str]:
    return sorted(CIRCUITS)
