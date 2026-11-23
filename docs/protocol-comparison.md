# Wave Mini and Wave Plus Protocol Comparison

## Overview

Wave Mini (model ID 2920) and Wave Plus (model ID 2930) share the same broad architecture: BLE sensor characteristics, ACP communication, and historical data notifications.

Their wire formats are not interchangeable. Keep device-specific parsing and history logic in `WaveMini.py` and `WavePlus.py`.

## Device characteristics

| Characteristic | Wave Mini | Wave Plus |
|---|---|---|
| Model ID | 2920 | 2930 |
| Service UUID | `b42e3882-ade7-11e4-89d3-123b93f75cba` | `b42e1c08-ade7-11e4-89d3-123b93f75cba` |
| Sensor UUID | `b42e3b98-ade7-11e4-89d3-123b93f75cba` | `b42e2a68-ade7-11e4-89d3-123b93f75cba` |
| ACP UUID | `b42e3ef4-ade7-11e4-89d3-123b93f75cba` | `b42e2d06-ade7-11e4-89d3-123b93f75cba` |
| History data UUID | `b42e41c4-ade7-11e4-89d3-123b93f75cba` | `b42e2fc2-ade7-11e4-89d3-123b93f75cba` |

UUIDs are characteristic/service identifiers, not ATT handles.

## Live sensor formats

### Wave Mini

Current implementation:

```python
struct.unpack("<HHHHHHLL", raw_data)
```

The first 16-bit word is currently unused. The remaining decoded fields include temperature, pressure, humidity, and VOC.

The upstream-style field decomposition `<2B5HLL>` treats the first two bytes as separate byte fields rather than one unused word. The current decoder does not assign meanings to those initial bytes.

### Wave Plus

Current implementation:

```python
struct.unpack("<BBBBHHHHHHHH", raw_data)
```

The packet is 20 bytes and includes humidity, ambient light, radon, temperature, pressure, CO₂, VOC, and additional raw fields.

See the individual model documents for conversions and unresolved values.

## ACP responses

### Wave Mini

The current Mini decoder extracts:

- An ambient-light raw byte at full-packet offset 7.
- Illuminance in lux from bytes 22–23, little-endian.
- Battery voltage in millivolts from bytes 26–27, little-endian.

A 34-byte ACP response has been observed. The current decoder checks a minimum length of 28 bytes before accessing these fields.

The Mini response structure is not the same as the Plus `0x6D` structure.

### Wave Plus

The Plus `0x6D` response is 30 bytes total:

- Two-byte header.
- Twenty-eight-byte payload.

The payload is unpacked using:

```python
struct.unpack("<L2BH2B9H", raw[2:])
```

It provides elapsed time, device type, illuminance, MSP firmware raw value, battery voltage, and unclassified fields.

## History

| Property | Wave Mini | Wave Plus |
|---|---|---|
| History packet length | 205 bytes | 230 bytes |
| Records per block | Up to 12 | 12 |
| Sample interval | 5 minutes | 5 minutes |
| Block duration | 1 hour | 1 hour |
| Metadata pre-request | Not used by current Mini collector | `71 54 00` |
| History request | Model-specific `01 02 ...` payload | Model-specific `01 02 ...` payload |
| Block identity | Block ID + block timestamp | Series start + record number |

### Mini history

The Mini history packet has a block ID, record count, timestamp, and up to 12 fixed-size records. The record area begins at byte offset 25 and each record is 15 bytes.

### Plus history

The Plus history packet stores its measurements in a different layout. The packet tail contains series start and record number, which together identify a block.

## Configuration

Both model implementations expose configuration read/write operations through their respective configuration modules. Their payload formats must be documented and validated independently.

Wave Plus configuration fields are documented in [Wave Plus protocol](wave-plus-protocol.md). Wave Mini configuration details belong in its model-specific configuration decoder and should be added here only after checking the current `WaveMiniConfig.py`.

## Shared implementation

`WaveGeneric.py` provides reusable BLE transport, device connection, ACP collection, generic history transfer, and persistence integration.

The shared collector uses model-specific hooks for:

- Request construction.
- Packet validation.
- Packet identity.
- Completion response interpretation.
- Per-packet reporting.

This keeps common transport behavior reusable without assuming that the models share packet formats.
