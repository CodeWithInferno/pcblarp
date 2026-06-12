"""Spec -> Design: instantiate block circuits and resolve every net.

This is the real replacement for the mocked stage 3 logic. It:
  - instantiates each block's CircuitDef into concrete components (R1, U2...)
  - wires power: VBAT/VBUS/VIN sources, optional soft-latch, regulator input
  - resolves spec.connections into nets, allocating MCU GPIOs from the pool
  - adds bus-level parts (I2C pull-ups) exactly once
  - marks every untouched pin as a no-connect so ERC is meaningful

Failures raise DesignError with llm_feedback so the pipeline's existing
revision loop can ask Claude for a buildable spec (e.g. swap an unsupported
catalog block, or add a power source).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Spec
from . import library
from .blocks import CIRCUITS, R_0603, CircuitDef, PartDef, supported_blocks

GLOBAL_NETS = {"GND", "+3V3", "+5V", "VBUS", "VBAT", "VBAT_SW", "VIN"}


class DesignError(Exception):
    def __init__(self, message: str, *, llm_feedback: str | None = None) -> None:
        super().__init__(message)
        self.llm_feedback = llm_feedback or message


@dataclass
class ComponentInstance:
    ref: str
    lib_id: str
    footprint_id: str
    value: str
    block_id: str
    pin_nets: dict[str, str] = field(default_factory=dict)  # pin number -> net
    nc_pins: list[str] = field(default_factory=list)


@dataclass
class Design:
    name: str
    components: list[ComponentInstance]
    nets: dict[str, list[tuple[str, str]]]  # net -> [(ref, pin number)]
    warnings: list[str]
    notes: list[str]
    erc_errors: list[str]

    def component(self, ref: str) -> ComponentInstance:
        for comp in self.components:
            if comp.ref == ref:
                return comp
        raise KeyError(ref)


def build_design(spec: Spec) -> Design:
    unsupported = sorted({
        b.catalog_block for b in spec.blocks if b.catalog_block not in CIRCUITS
    })
    if unsupported:
        supported = ", ".join(supported_blocks())
        raise DesignError(
            f"no circuit implementation for catalog blocks: {', '.join(unsupported)}",
            llm_feedback=(
                f"The schematic generator has no circuit for: "
                f"{', '.join(unsupported)}. Revise the spec to use only these "
                f"catalog blocks: {supported}."
            ),
        )

    builder = _Builder(spec)
    return builder.build()


class _Builder:
    def __init__(self, spec: Spec) -> None:
        self.spec = spec
        self.components: list[ComponentInstance] = []
        self.warnings: list[str] = []
        self.notes: list[str] = []
        self.erc: list[str] = []
        self.ref_counters: dict[str, int] = {}
        # (block_id, port) -> [(component index, pin number)]
        self.port_pins: dict[tuple[str, str], list[tuple[int, str]]] = {}
        self.port_nets: dict[tuple[str, str], str] = {}
        self.mcu_block_id: str | None = None
        self.mcu_circuit: CircuitDef | None = None
        self.mcu_index: int | None = None
        self.mcu_assigned: dict[str, str] = {}  # MCU pin NAME -> net
        self.mcu_pool: list[str] = []
        self.i2c_bus_up = False
        self.uart_up = False
        self.spi_bus_up = False

    # -- helpers ----------------------------------------------------------

    def _next_ref(self, prefix: str) -> str:
        self.ref_counters[prefix] = self.ref_counters.get(prefix, 0) + 1
        return f"{prefix}{self.ref_counters[prefix]}"

    def _sys_in(self) -> str:
        catalogs = {b.catalog_block for b in self.spec.blocks}
        has_batt = bool(catalogs & {"power_battery_18650", "power_battery_lipo_1s"})
        has_latch = "power_soft_latch_button" in catalogs
        if has_batt and has_latch:
            return "VBAT_SW"
        if has_batt:
            return "VBAT"
        if "power_usb_c_input" in catalogs:
            return "VBUS"
        if "power_barrel_jack" in catalogs:
            return "VIN"
        return "VBUS"  # least-bad default; flagged below if unsourced

    def _add_part(self, block_id: str, part: PartDef, sys_in: str) -> int:
        symbol = library.load_symbol(part.symbol)
        footprint = part.footprint or symbol.default_footprint
        if not footprint:
            raise DesignError(
                f"part {part.symbol} in block '{block_id}' has no footprint"
            )
        library.load_footprint(footprint)  # fail fast if not vendored
        comp = ComponentInstance(
            ref=self._next_ref(part.ref),
            lib_id=part.symbol,
            footprint_id=footprint,
            value=part.value,
            block_id=block_id,
        )
        index = len(self.components)
        self.components.append(comp)
        for selector, net_spec in part.pins.items():
            pins = (
                symbol.pins_named(selector[2:])
                if selector.startswith("n:")
                else [symbol.pin(selector)]
            )
            if not pins:
                raise DesignError(
                    f"{part.symbol}: pin selector {selector!r} matched nothing "
                    f"(library changed?)"
                )
            for pin in pins:
                self._wire(index, pin.number, net_spec, block_id, sys_in)
        return index

    def _wire(self, index: int, pin_no: str, net_spec: str,
              block_id: str, sys_in: str) -> None:
        comp = self.components[index]
        if net_spec == "NC":
            comp.nc_pins.append(pin_no)
        elif net_spec == "SYS_IN":
            comp.pin_nets[pin_no] = sys_in
        elif net_spec.startswith("$"):
            comp.pin_nets[pin_no] = f"{block_id}.{net_spec[1:]}"
        elif net_spec.startswith("@"):
            self.port_pins.setdefault((block_id, net_spec[1:]), []).append(
                (index, pin_no)
            )
        else:
            comp.pin_nets[pin_no] = net_spec

    def _alloc_gpio(self, count: int, why: str) -> list[str]:
        free = [p for p in self.mcu_pool if p not in self.mcu_assigned]
        if len(free) < count:
            raise DesignError(
                f"MCU has {len(free)} free GPIOs, {why} needs {count}",
                llm_feedback=(
                    f"The chosen MCU ran out of free GPIOs ({why} needs {count} "
                    f"more). Remove blocks or choose an MCU with more pins."
                ),
            )
        return free[:count]

    def _assign_mcu(self, pin_name: str, net: str) -> None:
        self.mcu_assigned[pin_name] = net

    def _bind_port(self, block_id: str, port: str, net: str) -> None:
        self.port_nets[(block_id, port)] = net

    def _peri_group(self, circuit: CircuitDef, block_id: str,
                    interface: str) -> list[str]:
        group = circuit.groups.get(interface) or circuit.groups.get("gpio")
        if group:
            return group
        return sorted({p for (bid, p) in self.port_pins if bid == block_id})

    # -- bus bring-up ------------------------------------------------------

    def _i2c_up(self, sys_in: str) -> None:
        if self.i2c_bus_up:
            return
        self.i2c_bus_up = True
        sda, scl = self.mcu_circuit.fixed["i2c"]
        self._assign_mcu(sda, "SDA")
        self._assign_mcu(scl, "SCL")
        for net in ("SDA", "SCL"):
            self._add_part(
                "i2c_bus",
                PartDef("R", "Device:R", "4.7k", {"1": "+3V3", "2": net}, R_0603),
                sys_in,
            )

    def _uart_up(self) -> None:
        if self.uart_up:
            return
        self.uart_up = True
        tx, rx = self.mcu_circuit.fixed["uart"]
        self._assign_mcu(tx, "UART0_TX")
        self._assign_mcu(rx, "UART0_RX")

    def _spi_up(self) -> None:
        if self.spi_bus_up:
            return
        self.spi_bus_up = True
        for pin, net in zip(self._alloc_gpio(3, "the SPI bus"),
                            ("SPI_SCK", "SPI_MOSI", "SPI_MISO")):
            self._assign_mcu(pin, net)

    # -- main build --------------------------------------------------------

    def build(self) -> Design:
        spec = self.spec
        sys_in = self._sys_in()

        for block in spec.blocks:
            circuit = CIRCUITS[block.catalog_block]
            first = len(self.components)
            for part in circuit.parts:
                self._add_part(block.id, part, sys_in)
            self.notes.extend(circuit.notes)
            if circuit.is_mcu and self.mcu_block_id is None:
                self.mcu_block_id = block.id
                self.mcu_circuit = circuit
                self.mcu_index = first  # MCU module is the first part
                self.mcu_pool = list(circuit.pool)

        # Fixed-pin interfaces first so they win their pins before GPIO
        # allocation can grab them.
        ordered = sorted(
            spec.connections,
            key=lambda c: 0 if c.interface in ("i2c", "uart", "usb") else 1,
        )
        handled_power = {"power"}
        for conn in ordered:
            iface = conn.interface.lower().strip()
            if iface in handled_power:
                continue
            self._connect(conn.from_block, conn.to_block, iface, sys_in)

        self._resolve_leftover_ports(sys_in)
        self._finalize_mcu()
        nets = self._collect_nets()
        self._power_sanity(nets, sys_in)

        return Design(
            name=spec.project.name,
            components=self.components,
            nets=nets,
            warnings=self.warnings,
            notes=self.notes,
            erc_errors=self.erc,
        )

    def _circuit_of(self, block_id: str) -> CircuitDef | None:
        for block in self.spec.blocks:
            if block.id == block_id:
                return CIRCUITS[block.catalog_block]
        return None

    def _connect(self, a: str, b: str, iface: str, sys_in: str) -> None:
        mcu_id = self.mcu_block_id
        if mcu_id is not None and mcu_id in (a, b):
            peri_id = b if a == mcu_id else a
            peri = self._circuit_of(peri_id)
            if peri is None or not peri.parts and not peri.groups:
                return  # builtin comm blocks etc.
            self._connect_mcu(peri_id, peri, iface, sys_in)
            return
        # MCU not involved: only USB (usb-c <-> bridge) is meaningful.
        if iface == "usb":
            for bid in (a, b):
                circuit = self._circuit_of(bid)
                if circuit is None:
                    continue
                for port in circuit.groups.get("usb", []):
                    self._bind_port(bid, port, f"USB_{port}")
            return
        if {a, b} & {self.mcu_block_id}:
            return
        self.warnings.append(
            f"connection {a} -> {b} ({iface}) does not involve the MCU; "
            "left unrouted"
        )

    def _connect_mcu(self, peri_id: str, peri: CircuitDef, iface: str,
                     sys_in: str) -> None:
        if self.mcu_circuit is None:
            self.warnings.append(
                f"no MCU block in spec; {peri_id} ({iface}) left unconnected"
            )
            return
        fixed = self.mcu_circuit.fixed
        if iface == "i2c" and "i2c" in fixed:
            self._i2c_up(sys_in)
            ports = peri.groups.get("i2c", ["SDA", "SCL"])
            for port, net in zip(ports, ("SDA", "SCL")):
                self._bind_port(peri_id, port, net)
        elif iface == "uart" and "uart" in fixed:
            self._uart_up()
            ports = self._peri_group(peri, peri_id, "uart")
            # Peripheral TXD drives the MCU's RX and vice versa.
            for port, net in zip(ports, ("UART0_RX", "UART0_TX")):
                self._bind_port(peri_id, port, net)
        elif iface == "usb" and "usb" in fixed:
            dp, dm = fixed["usb"]
            self._assign_mcu(dp, "USB_DP")
            self._assign_mcu(dm, "USB_DM")
            for port, net in zip(peri.groups.get("usb", ["DP", "DM"]),
                                 ("USB_DP", "USB_DM")):
                self._bind_port(peri_id, port, net)
        elif iface == "i2s":
            ports = peri.groups.get("i2s", ["BCLK", "WS", "SD"])
            nets = ("I2S_BCLK", "I2S_WS", "I2S_SD")
            for pin, net in zip(self._alloc_gpio(len(ports), "the I2S port"),
                                nets):
                self._assign_mcu(pin, net)
            for port, net in zip(ports, nets):
                self._bind_port(peri_id, port, net)
        elif iface == "spi":
            self._spi_up()
            cs_net = f"{peri_id.upper()}_CS"
            self._assign_mcu(self._alloc_gpio(1, f"{peri_id} chip select")[0],
                             cs_net)
            ports = peri.groups.get("spi", ["SCK", "MOSI", "MISO", "CS"])
            for port, net in zip(ports,
                                 ("SPI_SCK", "SPI_MOSI", "SPI_MISO", cs_net)):
                self._bind_port(peri_id, port, net)
        else:
            # gpio / pwm / adc / anything else: one MCU pin per exported port
            ports = [
                p for p in self._peri_group(peri, peri_id, iface)
                if (peri_id, p) not in self.port_nets
            ]
            if not ports:
                return
            pins = self._alloc_gpio(len(ports), f"{peri_id} ({iface})")
            for port, pin in zip(ports, pins):
                net = f"{peri_id.upper()}_{port}"
                self._assign_mcu(pin, net)
                self._bind_port(peri_id, port, net)

    def _resolve_leftover_ports(self, sys_in: str) -> None:
        for (block_id, port), pins in self.port_pins.items():
            if (block_id, port) in self.port_nets:
                continue
            circuit = self._circuit_of(block_id)
            groups = circuit.groups if circuit else {}
            if port in groups.get("i2c", []) \
                    and self.mcu_circuit and "i2c" in self.mcu_circuit.fixed:
                # I2C device the spec forgot to connect: join the bus.
                self._i2c_up(sys_in)
                net = "SDA" if port == "SDA" else "SCL"
                self._bind_port(block_id, port, net)
                self.warnings.append(
                    f"{block_id}.{port} had no connection in the spec; "
                    "joined the I2C bus"
                )
            elif port in groups.get("usb", []):
                # USB data lines with no consumer (charge-only port): NC.
                for index, pin_no in pins:
                    self.components[index].nc_pins.append(pin_no)
                self._bind_port(block_id, port, "")
                self.notes.append(
                    f"{block_id}: USB data lines unused (power only)"
                )
            elif self.mcu_circuit is not None:
                # GPIO-ish port the spec forgot: wire it to a free MCU pin.
                try:
                    pin = self._alloc_gpio(1, f"{block_id}.{port}")[0]
                except DesignError:
                    self._bind_port(block_id, port,
                                    f"{block_id.upper()}_{port}")
                    self.warnings.append(
                        f"{block_id}.{port} left unconnected (no free MCU pins)"
                    )
                    continue
                net = f"{block_id.upper()}_{port}"
                self._assign_mcu(pin, net)
                self._bind_port(block_id, port, net)
                self.warnings.append(
                    f"{block_id}.{port} had no connection in the spec; "
                    f"wired to MCU {pin}"
                )
            else:
                self._bind_port(block_id, port, f"{block_id.upper()}_{port}")
                self.warnings.append(
                    f"{block_id}.{port} is not connected to the MCU"
                )
        for (block_id, port), pins in self.port_pins.items():
            net = self.port_nets[(block_id, port)]
            if not net:
                continue
            for index, pin_no in pins:
                self.components[index].pin_nets[pin_no] = net

    def _finalize_mcu(self) -> None:
        if self.mcu_index is None:
            return
        mcu = self.components[self.mcu_index]
        symbol = library.load_symbol(mcu.lib_id)
        by_name: dict[str, list[str]] = {}
        for pin in symbol.pins:
            by_name.setdefault(pin.name, []).append(pin.number)
        for name, net in self.mcu_assigned.items():
            numbers = by_name.get(name)
            if not numbers:
                raise DesignError(
                    f"MCU {mcu.lib_id} has no pin named {name!r} (library changed?)"
                )
            for number in numbers:
                mcu.pin_nets.setdefault(number, net)

    def _collect_nets(self) -> dict[str, list[tuple[str, str]]]:
        nets: dict[str, list[tuple[str, str]]] = {}
        for comp in self.components:
            symbol = library.load_symbol(comp.lib_id)
            for pin in symbol.pins:
                if pin.number in comp.pin_nets:
                    nets.setdefault(comp.pin_nets[pin.number], []).append(
                        (comp.ref, pin.number)
                    )
                elif pin.number not in comp.nc_pins:
                    comp.nc_pins.append(pin.number)
        for net, members in nets.items():
            if len(members) == 1 and net not in GLOBAL_NETS:
                self.warnings.append(
                    f"net {net} has a single pin "
                    f"({members[0][0]}.{members[0][1]})"
                )
        return nets

    def _power_sanity(self, nets: dict[str, list[tuple[str, str]]],
                      sys_in: str) -> None:
        catalogs = {b.catalog_block for b in self.spec.blocks}
        sources = {
            "VBAT": catalogs & {"power_battery_18650", "power_battery_lipo_1s"},
            "VBUS": catalogs & {"power_usb_c_input"},
            "VIN": catalogs & {"power_barrel_jack"},
            "+3V3": catalogs & {"power_ldo_3v3", "power_buck_3v3"},
        }
        for net, has in sources.items():
            if net in nets and not has:
                self.erc.append(
                    f"net {net} has consumers but no source block; add the "
                    "matching power block"
                )
        if "+3V3" in nets and not sources["+3V3"]:
            pass  # already reported above
        if "power_soft_latch_button" in catalogs and not sources["VBAT"]:
            self.erc.append(
                "power_soft_latch_button requires a battery block (it switches "
                "VBAT); add power_battery_lipo_1s or power_battery_18650"
            )
        if "power_battery_lipo_1s" in catalogs and not sources["VBUS"]:
            self.warnings.append(
                "LiPo charger has no VBUS source; add power_usb_c_input to "
                "charge on board"
            )


def assembly_bom(design: Design) -> list[dict]:
    """Group components by (value, footprint) for the PCBA-style BOM."""
    groups: dict[tuple[str, str, str], list[str]] = {}
    for comp in design.components:
        key = (comp.value, comp.footprint_id, comp.lib_id)
        groups.setdefault(key, []).append(comp.ref)
    rows = []
    for (value, footprint, lib_id), refs in sorted(
        groups.items(), key=lambda kv: _ref_sort_key(kv[1][0])
    ):
        rows.append({
            "refs": ",".join(sorted(refs, key=_ref_sort_key)),
            "qty": len(refs),
            "value": value,
            "symbol": lib_id,
            "footprint": footprint.split(":", 1)[1],
        })
    return rows


def _ref_sort_key(ref: str) -> tuple[str, int]:
    head = ref.rstrip("0123456789")
    tail = ref[len(head):]
    return (head, int(tail) if tail else 0)
