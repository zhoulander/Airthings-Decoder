
#!/usr/bin/env python3
"""
Airthings Wave Plus configuration decoder.

Experimental protocol:
    66 00 = Read configuration
    66 01 = Write configuration

Known fields:
    Humidity transitions
    Radon low/high
    VOC low/high
    CO2 low/high

Unknown:
    16-bit field at offsets 18-19
    Temperature thresholds (not found yet)

All multi-byte threshold values are little-endian.
"""

import struct
from dataclasses import dataclass, replace


CONFIG_READ = bytes.fromhex("66 00")
CONFIG_WRITE = bytes.fromhex("66 01")
CONFIG_FORMAT = "<4B7H"
CONFIG_SIZE = struct.calcsize(CONFIG_FORMAT)
CONFIG_RESPONSE_SIZE = 2 + CONFIG_SIZE


@dataclass
class WavePlusConfig:
    humidity_good_to_fair: int
    humidity_fair_to_poor: int
    humidity_fair_to_good: int
    humidity_poor_to_fair: int

    radon_low: int
    radon_high: int

    voc_low: int
    voc_high: int

    co2_low: int
    co2_high: int

    unknown_word: int
    response_trailer: bytes = b""


def decode_config(raw: bytes) -> WavePlusConfig:
    """Decode a 66 00 configuration response."""

    if len(raw) < CONFIG_RESPONSE_SIZE:
        raise ValueError(
            f"Response too short: {len(raw)} bytes; "
            f"expected at least {CONFIG_RESPONSE_SIZE}"
        )

    if raw[:2] != CONFIG_READ:
        raise ValueError(
            f"Unexpected response: {raw[:2].hex(' ')}"
        )

    (
        humidity_good_to_fair,
        humidity_fair_to_poor,
        humidity_fair_to_good,
        humidity_poor_to_fair,
        radon_low,
        radon_high,
        voc_low,
        voc_high,
        co2_low,
        co2_high,
        unknown_word,
    ) = struct.unpack_from(CONFIG_FORMAT, raw, 2)

    return WavePlusConfig(
        humidity_good_to_fair=humidity_good_to_fair,
        humidity_fair_to_poor=humidity_fair_to_poor,
        humidity_fair_to_good=humidity_fair_to_good,
        humidity_poor_to_fair=humidity_poor_to_fair,
        radon_low=radon_low,
        radon_high=radon_high,
        voc_low=voc_low,
        voc_high=voc_high,
        co2_low=co2_low,
        co2_high=co2_high,
        unknown_word=unknown_word,
        response_trailer=raw[CONFIG_RESPONSE_SIZE:],
    )

def config_to_dict(config: WavePlusConfig) -> dict:
    """Convert decoded configuration into dashboard-friendly data."""

    return {
        "humidity_good_to_fair": config.humidity_good_to_fair,
        "humidity_fair_to_poor": config.humidity_fair_to_poor,
        "humidity_fair_to_good": config.humidity_fair_to_good,
        "humidity_poor_to_fair": config.humidity_poor_to_fair,
        "radon_low": config.radon_low,
        "radon_high": config.radon_high,
        "voc_low": config.voc_low,
        "voc_high": config.voc_high,
        "co2_low": config.co2_low,
        "co2_high": config.co2_high,
    }

def humidity_bands(config):
    """
    Convert the four humidity transition points into
    human-readable humidity bands.
    """

    p_to_f = config.humidity_poor_to_fair
    f_to_g = config.humidity_fair_to_good
    g_to_f = config.humidity_good_to_fair
    f_to_p = config.humidity_fair_to_poor

    if not (0 <= p_to_f <= f_to_g <= g_to_f <= f_to_p <= 100):
        raise ValueError(
            "Humidity thresholds are not in ascending order: "
            f"{p_to_f}, {f_to_g}, {g_to_f}, {f_to_p}"
        )

    return [
        (0, p_to_f, "Poor"),
        (p_to_f, f_to_g, "Fair"),
        (f_to_g, g_to_f, "Good"),
        (g_to_f, f_to_p, "Fair"),
        (f_to_p, 100, "Poor"),
    ]


def print_config(config: WavePlusConfig):
    """Print all currently decoded fields."""

    print("=" * 48)
    print("          AIRTHINGS WAVE PLUS CONFIG")
    print("=" * 48)

    print("\nHUMIDITY AIR QUALITY BANDS")
    print("-" * 48)

    for low, high, quality in humidity_bands(config):
        print(f"  {low:3d}% - {high:3d}%  : {quality}")

    print("\nRADON THRESHOLDS")
    print("-" * 48)
    print(f"  Low threshold : {config.radon_low} Bq/m³")
    print(f"  High threshold: {config.radon_high} Bq/m³")

    print("\nVOC THRESHOLDS")
    print("-" * 48)
    print(f"  Low threshold : {config.voc_low} ppb")
    print(f"  High threshold: {config.voc_high} ppb")

    print("\nCO2 THRESHOLDS")
    print("-" * 48)
    print(f"  Low threshold : {config.co2_low} ppm")
    print(f"  High threshold: {config.co2_high} ppm")

    print("\nUNKNOWN FIELDS")
    print("-" * 48)
    print(f"  Unknown word  : 0x{config.unknown_word:04X}")

    if config.response_trailer:
        print(
            "  Trailer       : "
            + config.response_trailer.hex(" ").upper()
        )

    print("\nTEMPERATURE")
    print("-" * 48)
    print("  Low threshold : Not decoded")
    print("  High threshold: Not decoded")

    print("\nRAW CONFIGURATION")
    print("-" * 48)
    print(f"  Humidity bytes: "
          f"{config.humidity_good_to_fair:02X} "
          f"{config.humidity_fair_to_poor:02X} "
          f"{config.humidity_fair_to_good:02X} "
          f"{config.humidity_poor_to_fair:02X}")

    print("=" * 48)


def encode_config_write(config: WavePlusConfig) -> bytes:
    """Encode a 66 01 configuration write."""

    humidity_values = (
        config.humidity_good_to_fair,
        config.humidity_fair_to_poor,
        config.humidity_fair_to_good,
        config.humidity_poor_to_fair,
    )

    threshold_values = (
        config.radon_low,
        config.radon_high,
        config.voc_low,
        config.voc_high,
        config.co2_low,
        config.co2_high,
        config.unknown_word,
    )

    if any(not 0 <= value <= 100 for value in humidity_values):
        raise ValueError("Humidity thresholds must be between 0 and 100")

    if any(not 0 <= value <= 65535 for value in threshold_values):
        raise ValueError("16-bit thresholds must be between 0 and 65535")

    return CONFIG_WRITE + struct.pack(
        CONFIG_FORMAT,
        *humidity_values,
        *threshold_values,
    )


def update_config(config: WavePlusConfig, **changes):
    """Create a modified copy without changing the original."""
    valid = set(config.__dataclass_fields__)
    invalid = set(changes) - valid

    if invalid:
        raise ValueError(f"Unknown fields: {sorted(invalid)}")

    return replace(config, **changes)


# ------------------------------------------------------------
# Example
# ------------------------------------------------------------

if __name__ == "__main__":

    captured_response = bytes.fromhex(
        "66003c461e196e001301fa00d007bc024c044320ffffffff"
    )

    config = decode_config(captured_response)

    print_config(config)

    print("\nReconstructed write packet:")
    print(encode_config_write(config).hex(" ").upper())
