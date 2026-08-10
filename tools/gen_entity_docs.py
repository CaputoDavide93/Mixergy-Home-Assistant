#!/usr/bin/env python3
"""Generate the README entity/service tables from the integration source.

The tables between the ``<!-- AUTOGEN:... -->`` markers in README.md are
produced by this script — do not edit them by hand. Sources of truth:

- ``strings.json``            → entity names per platform, service names/descriptions
- ``sensor.py`` etc. (AST)    → units, ranges, PV-only availability, diagnostic flags
- ``services.yaml``           → the set of exposed services

Only the short prose in the *Description* column lives in this script
(``SENSOR_TEXT`` / ``BINARY_TEXT`` / ``CONTROL_TEXT``). A completeness check
cross-references every table against ``strings.json``: adding, removing, or
renaming an entity in the integration makes ``--check`` fail until both the
description map here and the README are updated.

Usage:
    python tools/gen_entity_docs.py           # rewrite README.md in place
    python tools/gen_entity_docs.py --check   # exit non-zero if README is stale

Stdlib only — no Home Assistant install required.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "mixergy"
README = ROOT / "README.md"

# ── Description prose (the only hand-written part; keyed by entity key) ────

SENSOR_TEXT = {
    "hot_water_temperature": "Current top-of-tank temperature",
    "coldest_water_temperature": "Current bottom-of-tank temperature",
    "target_temperature": "Configured target temperature",
    "cleansing_temperature": "Anti-legionella cleansing temperature",
    "charge": "Current hot water charge level",
    "target_charge": "Configured target charge level",
    "electric_power": "Real power draw from CT clamp",
    "electric_energy": "Cumulative electric energy (Energy Dashboard)",
    "pv_power": "Solar PV power being diverted",
    "pv_energy": "Cumulative PV energy (Energy Dashboard)",
    "clamp_power": "CT clamp power reading",
    "active_heat_source": "Currently active heat source",
    "default_heat_source": "Configured default heat source",
    "holiday_start": "Holiday mode start date",
    "holiday_end": "Holiday mode end date",
    "electric_cost": "Cumulative cost *(only when a tariff rate is set in options)*",
    "firmware_version": "Tank firmware",
    "model": "Tank model code",
    "last_update": "Time of the last API refresh",
}

# Sensors table row order (must cover exactly the strings.json sensor keys).
SENSOR_ORDER = list(SENSOR_TEXT)

BINARY_TEXT = {
    "electric_heat": "Electric immersion heater is currently on",
    "indirect_heat": "Gas/oil indirect coil is heating",
    "heatpump_heat": "Heat pump is heating",
    "is_heating": "Any heat source is actively heating",
    "low_hot_water": "Charge is below the low threshold (default 5%, configurable)",
    "no_hot_water": "Charge is below the no-water threshold (default 0.5%, configurable)",
    "holiday_mode": "Tank is currently in holiday mode",
}
BINARY_ORDER = list(BINARY_TEXT)

# Controls: (platform, key) → prose. ``water_heater`` has no strings.json
# entry (it takes the device name), so it is described here directly.
CONTROL_TEXT = {
    ("number", "boost_charge_simple"): "Set how full you want the tank right now",
    ("water_heater", "water_heater"): "Temperature, operation mode & away in one card",
    ("datetime", "holiday_start_set"): "Set the holiday start from a date/time picker",
    ("datetime", "holiday_end_set"): "Set the holiday end from a date/time picker",
    ("number", "target_temperature_control"): "Set the desired water temperature",
    ("number", "target_charge_control"): "Set the desired charge level",
    ("number", "cleansing_temperature_control"): "Set anti-legionella temperature",
    ("select", "default_heat_source_select"): "Choose default heat source",
    ("switch", "dsr_enabled"): "Enable/disable demand-side response",
    ("switch", "frost_protection"): "Enable/disable frost protection",
    ("switch", "distributed_computing"): "Enable/disable distributed computing",
    ("switch", "pv_divert"): "Enable/disable PV divert",
    ("number", "pv_cut_in_threshold"): "PV diverter cut-in threshold, in watts",
    ("number", "pv_charge_limit"): "Maximum charge from PV",
    ("number", "pv_target_current"): "PV target current",
    ("number", "pv_over_temperature"): "Maximum PV heating temperature",
    ("button", "clear_holiday"): "Clear holiday mode immediately",
}

SIMPLE_CONTROLS = [("number", "boost_charge_simple")]
ADVANCED_CONTROLS = [pk for pk in CONTROL_TEXT if pk not in SIMPLE_CONTROLS]

# ── AST extraction helpers ──────────────────────────────────────────────────

UNIT_MAP = {
    ("UnitOfTemperature", "CELSIUS"): "°C",
    ("UnitOfPower", "WATT"): "W",
    ("UnitOfPower", "KILO_WATT"): "kW",
    ("UnitOfEnergy", "KILO_WATT_HOUR"): "kWh",
}


def _unit(node: ast.AST | None) -> str | None:
    """Resolve a native_unit_of_measurement AST node to a display unit."""
    if node is None:
        return None
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return UNIT_MAP.get((node.value.id, node.attr))
    if isinstance(node, ast.Name) and node.id in {"PERCENTAGE", "PERCENTAGE_UNIT"}:
        return "%"
    return None


def _literal(node: ast.AST | None):
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def _num(value: float) -> str:
    """Format a number for display (int when whole, Unicode minus)."""
    if value == int(value):
        value = int(value)
    return str(value).replace("-", "−")


class Desc:
    """Metadata for one entity description extracted from the source."""

    def __init__(self, kwargs: dict[str, ast.AST]):
        self.kwargs = kwargs

    @property
    def unit(self) -> str | None:
        return _unit(self.kwargs.get("native_unit_of_measurement"))

    @property
    def is_timestamp(self) -> bool:
        node = self.kwargs.get("device_class")
        return isinstance(node, ast.Attribute) and node.attr == "TIMESTAMP"

    @property
    def pv_only(self) -> bool:
        node = self.kwargs.get("available_fn")
        return node is not None and "has_pv_diverter" in ast.unparse(node)

    @property
    def diagnostic_disabled(self) -> bool:
        cat = self.kwargs.get("entity_category")
        disabled = _literal(self.kwargs.get("entity_registry_enabled_default"))
        return (
            isinstance(cat, ast.Attribute)
            and cat.attr == "DIAGNOSTIC"
            and disabled is False
        )

    def number_range(self) -> str:
        lo = _literal(self.kwargs.get("native_min_value"))
        hi = _literal(self.kwargs.get("native_max_value"))
        parts = f"{_num(lo)}–{_num(hi)}"
        if self.unit:
            parts += f" {self.unit}"
        return parts


def collect_calls(path: Path, call_name: str, key_kwarg: str = "key") -> dict[str, Desc]:
    """Collect every ``call_name(...)`` in *path*, keyed by its ``key`` kwarg."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: dict[str, Desc] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != call_name:
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        key = _literal(kwargs.get(key_kwarg))
        if isinstance(key, str):
            found[key] = Desc(kwargs)
    return found


def collect_class_attrs(path: Path, class_name: str) -> Desc:
    """Collect ``_attr_*`` class attributes of *class_name* as a Desc."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    kwargs: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name):
                    attr = stmt.targets[0].id
                    if attr.startswith("_attr_"):
                        kwargs[attr.removeprefix("_attr_")] = stmt.value
    return Desc(kwargs)


# ── Source loading ──────────────────────────────────────────────────────────


def load_sources() -> dict:
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))

    sensors = collect_calls(COMPONENT / "sensor.py", "MixergySensorEntityDescription")
    # Energy sensors are built imperatively in async_setup_entry; their unit
    # and device class live on the MixergyEnergySensor class, so merge the
    # class-level _attr_* values under each constructor call's kwargs.
    energy = collect_calls(COMPONENT / "sensor.py", "MixergyEnergySensor")
    energy_cls = collect_class_attrs(COMPONENT / "sensor.py", "MixergyEnergySensor")
    for key, desc in energy.items():
        merged = dict(energy_cls.kwargs)
        merged.update(desc.kwargs)
        sensors[key] = Desc(merged)
    # Cost sensor is a dedicated class, created only when a tariff is set.
    cost = collect_class_attrs(COMPONENT / "sensor.py", "MixergyElectricCostSensor")
    cost_key = _literal(cost.kwargs.get("translation_key"))
    if cost_key:
        sensors[cost_key] = cost

    binaries = collect_calls(
        COMPONENT / "binary_sensor.py", "MixergyBinarySensorEntityDescription"
    )

    numbers = collect_calls(COMPONENT / "number.py", "MixergyNumberEntityDescription")
    boost = collect_class_attrs(COMPONENT / "number.py", "MixergyBoostNumber")
    boost_key = _literal(boost.kwargs.get("translation_key"))
    if boost_key:
        numbers[boost_key] = boost

    switches = collect_calls(COMPONENT / "switch.py", "MixergySwitchEntityDescription")

    services_yaml = (COMPONENT / "services.yaml").read_text(encoding="utf-8")
    service_keys = re.findall(r"^([a-z_]+):", services_yaml, flags=re.MULTILINE)

    return {
        "strings": strings,
        "sensors": sensors,
        "binaries": binaries,
        "numbers": numbers,
        "switches": switches,
        "service_keys": service_keys,
    }


# ── Completeness checks ─────────────────────────────────────────────────────


def verify(src: dict) -> list[str]:
    """Cross-check the description maps against strings.json and the source."""
    errors: list[str] = []
    strings_entities = src["strings"]["entity"]

    def diff(label: str, documented: set, actual: set) -> None:
        if missing := actual - documented:
            errors.append(f"{label}: undocumented keys {sorted(missing)} — add rows")
        if stale := documented - actual:
            errors.append(f"{label}: stale documented keys {sorted(stale)} — remove rows")

    diff("sensor (strings.json)", set(SENSOR_TEXT), set(strings_entities["sensor"]))
    diff("sensor (sensor.py)", set(SENSOR_TEXT), set(src["sensors"]))
    diff("binary_sensor (strings.json)", set(BINARY_TEXT), set(strings_entities["binary_sensor"]))
    diff("binary_sensor (binary_sensor.py)", set(BINARY_TEXT), set(src["binaries"]))

    control_docs: dict[str, set] = {}
    for platform, key in CONTROL_TEXT:
        control_docs.setdefault(platform, set()).add(key)
    for platform in ("number", "switch", "select", "button", "datetime"):
        diff(
            f"{platform} (strings.json)",
            control_docs.get(platform, set()),
            set(strings_entities.get(platform, {})),
        )
    diff("number (number.py)", control_docs["number"], set(src["numbers"]))
    diff("switch (switch.py)", control_docs["switch"], set(src["switches"]))

    if not (COMPONENT / "water_heater.py").exists():
        errors.append("water_heater.py missing but documented in Controls")

    diff("services (services.yaml)", set(src["strings"]["services"]), set(src["service_keys"]))
    return errors


# ── Table rendering ─────────────────────────────────────────────────────────

PV_SUFFIX = " *(PV diverter only)*"
DIAG_SUFFIX = " *(diagnostic, disabled by default)*"


def render_sensors(src: dict) -> str:
    names = src["strings"]["entity"]["sensor"]
    lines = ["| Sensor | Unit | Description |", "| ------ | ---- | ----------- |"]
    for key in SENSOR_ORDER:
        desc: Desc = src["sensors"][key]
        if key == "electric_cost":
            unit = "currency"
        elif desc.is_timestamp:
            unit = "Timestamp"
        else:
            unit = desc.unit or "—"
        text = SENSOR_TEXT[key]
        if desc.pv_only:
            text += PV_SUFFIX
        if desc.diagnostic_disabled:
            text += DIAG_SUFFIX
        lines.append(f"| {names[key]['name']} | {unit} | {text} |")
    return "\n".join(lines)


def render_binaries(src: dict) -> str:
    names = src["strings"]["entity"]["binary_sensor"]
    lines = ["| Sensor | Description |", "| ------ | ----------- |"]
    for key in BINARY_ORDER:
        text = BINARY_TEXT[key]
        if src["binaries"][key].pv_only:
            text += PV_SUFFIX
        lines.append(f"| {names[key]['name']} | {text} |")
    return "\n".join(lines)


def _control_row(src: dict, platform: str, key: str) -> str:
    strings_entities = src["strings"]["entity"]
    if platform == "water_heater":
        name, kind, pv = "Water heater", "Water heater", False
    elif platform == "number":
        desc = src["numbers"][key]
        name = strings_entities["number"][key]["name"]
        kind = f"Number ({desc.number_range()})"
        pv = desc.pv_only
    elif platform == "switch":
        desc = src["switches"][key]
        name = strings_entities["switch"][key]["name"]
        kind, pv = "Switch", desc.pv_only
    else:
        name = strings_entities[platform][key]["name"]
        kind = {"select": "Select", "button": "Button", "datetime": "DateTime"}[platform]
        pv = False
    text = CONTROL_TEXT[(platform, key)]
    if pv:
        text += PV_SUFFIX
    return f"| {name} | {kind} | {text} |"


def render_controls(src: dict, controls: list) -> str:
    lines = ["| Entity | Type | Description |", "| ------ | ---- | ----------- |"]
    lines.extend(_control_row(src, platform, key) for platform, key in controls)
    return "\n".join(lines)


def render_services(src: dict) -> str:
    services = src["strings"]["services"]
    lines = ["| Service | Description |", "| ------- | ----------- |"]
    for key in src["service_keys"]:
        lines.append(f"| `mixergy.{key}` | {services[key]['description']} |")
    return "\n".join(lines)


def render_blocks(src: dict) -> dict[str, str]:
    return {
        "sensors": render_sensors(src),
        "binary-sensors": render_binaries(src),
        "controls-simple": render_controls(src, SIMPLE_CONTROLS),
        "controls-advanced": render_controls(src, ADVANCED_CONTROLS),
        "services": render_services(src),
    }


# ── Document splicing ────────────────────────────────────────────────────────

# Files carrying the AUTOGEN markers. README.md is mandatory; docs/entities.md
# is spliced too when present so the deep-dive reference can never drift from
# the tables the README shows.
TARGETS = [README, ROOT / "docs" / "entities.md"]


def splice(
    text: str, blocks: dict[str, str], name_for_errors: str, *, strict: bool = True
) -> str:
    """Replace each marked block. Strict targets (README) must carry every
    marker pair; lenient targets may carry a subset — only the pairs present
    are refreshed."""
    for name, table in blocks.items():
        start = f"<!-- AUTOGEN:entities:{name} -->"
        end = f"<!-- /AUTOGEN:entities:{name} -->"
        if start not in text or end not in text:
            if strict:
                raise SystemExit(
                    f"{name_for_errors} is missing the {start} … {end} markers"
                )
            continue
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
        text = pattern.sub(f"{start}\n{table}\n{end}", text)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the generated tables are up to date; exit 1 if stale",
    )
    args = parser.parse_args()

    src = load_sources()
    if errors := verify(src):
        print("Entity documentation is out of sync with the source:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        print(f"Update the maps in {Path(__file__).name} to match.", file=sys.stderr)
        return 2

    blocks = render_blocks(src)
    stale: list[str] = []
    for target in TARGETS:
        if not target.exists():
            if target == README:
                raise SystemExit("README.md not found")
            continue
        rel = target.relative_to(ROOT)
        current = target.read_text(encoding="utf-8")
        updated = splice(current, blocks, str(rel), strict=target == README)
        if updated == current:
            continue
        if args.check:
            stale.append(str(rel))
        else:
            target.write_text(updated, encoding="utf-8")
            print(f"{rel} entity tables regenerated.")

    if args.check:
        if stale:
            print(
                f"Entity tables are stale in: {', '.join(stale)}. "
                "Run: python tools/gen_entity_docs.py",
                file=sys.stderr,
            )
            return 1
        print("Entity tables are up to date.")
        return 0

    print("Entity tables are up to date." if not stale else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
