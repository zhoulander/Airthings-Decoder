
#!/usr/bin/env python3
"""
Airthings Wave Mini configuration decoder.

Experimental protocol:
    66 00 = Read configuration
    66 01 = Write configuration

Known fields:
    4-byte unknown prefix (preserved)
    Humidity transitions
    VOC low/high

Unknown:
    Meaning of the first four data bytes
    Temperature thresholds (not decoded)

All multi-byte threshold values are little-endian.
"""

import struct
from dataclasses import dataclass, replace


CONFIG_READ = bytes.fromhex("66 00")
CONFIG_WRITE = bytes.fromhex("66 01")
CONFIG_FORMAT = "<4B2H"
CONFIG_SIZE = struct.calcsize(CONFIG_FORMAT)


@dataclass
class WaveMiniConfig:
    unknown_prefix: bytes

    humidity_good_to_fair: int
    humidity_fair_to_poor: int
    humidity_fair_to_good: int
    humidity_poor_to_fair: int

    voc_low: int
    voc_high: int

    response_trailer: bytes = b""


def decode_config(raw: bytes) -> WaveMiniConfig:
    """Decode a Wave Mini 66 00 configuration response."""

    expected_size = 2 + 4 + CONFIG_SIZE

    if len(raw) < expected_size:
        raise ValueError(
            f"Response too short: {len(raw)} bytes; "
            f"expected at least {expected_size}"
        )

    if raw[:2] != CONFIG_READ:
        raise ValueError(
            f"Unexpected response: {raw[:2].hex(' ')}"
        )

    unknown_prefix = raw[2:6]

    (
        humidity_good_to_fair,
        humidity_fair_to_poor,
        humidity_fair_to_good,
        humidity_poor_to_fair,
        voc_low,
        voc_high,
    ) = struct.unpack_from(CONFIG_FORMAT, raw, 6)

    return WaveMiniConfig(
        unknown_prefix=unknown_prefix,

        humidity_good_to_fair=humidity_good_to_fair,
        humidity_fair_to_poor=humidity_fair_to_poor,
        humidity_fair_to_good=humidity_fair_to_good,
        humidity_poor_to_fair=humidity_poor_to_fair,

        voc_low=voc_low,
        voc_high=voc_high,

        response_trailer=raw[expected_size:],
    )

def config_to_dict(config: WaveMiniConfig) -> dict:
    """Convert decoded configuration into dashboard-friendly data."""

    return {
        "humidity_good_to_fair": config.humidity_good_to_fair,
        "humidity_fair_to_poor": config.humidity_fair_to_poor,
        "humidity_fair_to_good": config.humidity_fair_to_good,
        "humidity_poor_to_fair": config.humidity_poor_to_fair,
        "voc_low": config.voc_low,
        "voc_high": config.voc_high,
    }

def humidity_bands(config):
    """Convert humidity transition points into readable bands."""

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


def print_config(config: WaveMiniConfig):
    """Print all currently decoded configuration fields."""

    print("=" * 48)
    print("          AIRTHINGS WAVE MINI CONFIG")
    print("=" * 48)

    print("\nHUMIDITY AIR QUALITY BANDS")
    print("-" * 48)

    for low, high, quality in humidity_bands(config):
        print(f"  {low:3d}% - {high:3d}%  : {quality}")

    print("\nVOC THRESHOLDS")
    print("-" * 48)
    print(f"  Low threshold : {config.voc_low} ppb")
    print(f"  High threshold: {config.voc_high} ppb")

    print("\nUNKNOWN FIELDS")
    print("-" * 48)
    print(
        "  Unknown prefix: "
        + config.unknown_prefix.hex(" ").upper()
    )

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
    print("  Unknown bytes : " + config.unknown_prefix.hex(" ").upper())
    print(
        "  Humidity bytes: "
        f"{config.humidity_good_to_fair:02X} "
        f"{config.humidity_fair_to_poor:02X} "
        f"{config.humidity_fair_to_good:02X} "
        f"{config.humidity_poor_to_fair:02X}"
    )

    print("=" * 48)


def encode_config_write(config: WaveMiniConfig) -> bytes:
    """Encode a Wave Mini 66 01 configuration write."""

    if len(config.unknown_prefix) != 4:
        raise ValueError("Unknown prefix must be exactly 4 bytes")

    humidity_values = (
        config.humidity_good_to_fair,
        config.humidity_fair_to_poor,
        config.humidity_fair_to_good,
        config.humidity_poor_to_fair,
    )

    if any(not 0 <= value <= 100 for value in humidity_values):
        raise ValueError(
            "Humidity thresholds must be between 0 and 100"
        )

    voc_values = (
        config.voc_low,
        config.voc_high,
    )

    if any(not 0 <= value <= 65535 for value in voc_values):
        raise ValueError(
            "VOC thresholds must be between 0 and 65535"
        )

    return (
        CONFIG_WRITE
        + config.unknown_prefix
        + struct.pack(CONFIG_FORMAT, *humidity_values, *voc_values)
    )

def update_config(config: WaveMiniConfig, **changes):
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

    # Captured Wave Mini readback after setting VOC to 275 / 2500.
    captured_response = bytes.fromhex(
        "6600030200003c461e191301c409"
    )

    config = decode_config(captured_response)

    print_config(config)

    print("\nReconstructed write packet:")
    print(encode_config_write(config).hex(" ").upper())

    # Example of changing VOC thresholds:
    updated = update_config(
        config,
        voc_low=300,
        voc_high=2000,
    )

    print("\nExample updated write packet:")
    print(encode_config_write(updated).hex(" ").upper())
