# Airthings Wave Plus BLE Protocol

**Model:** Airthings Wave Plus  
**Model ID:** 2930  
**Implementation:** `WavePlus.py`

## 1. Device characteristics

| Characteristic | UUID |
|---|---|
| Service | `b42e1c08-ade7-11e4-89d3-123b93f75cba` |
| Sensor data | `b42e2a68-ade7-11e4-89d3-123b93f75cba` |
| ACP | `b42e2d06-ade7-11e4-89d3-123b93f75cba` |
| History data | `b42e2fc2-ade7-11e4-89d3-123b93f75cba` |

## 2. Live sensor data

The live sensor characteristic is 20 bytes.

Current structure:

```python
struct.unpack("<BBBBHHHHHHHH", raw_data)
```

| Field | Conversion / interpretation |
|---|---|
| Version | Must equal 1 |
| Humidity | `raw / 2` % |
| Ambient light | Raw byte |
| Waves | Raw byte; meaning not established |
| Radon ST | Converted using the shared radon conversion |
| Radon LT | Converted using the shared radon conversion |
| Temperature | `raw / 100` °C |
| Pressure | `raw / 50` hPa |
| CO₂ | ppm |
| VOC | ppb |
| Mode | Raw 16-bit value; unclassified |
| X3 | `raw / 256`; semantic meaning not established |

## 3. ACP Query 2 / status response

Command:

```text
6D
```

The response is 30 bytes total:

- Two-byte header: `6D 00`
- 28-byte payload.

Example:

```text
6D 00 63 F2 76 00 02 00 80 84 1C 00
00 00 00 00 00 00 4C 14 00 CA 33 07
00 0C 01 E4 0B 09 00
```

Current payload unpacking:

```python
values = struct.unpack("<L2BH2B9H", raw[2:])
```

| Value index | Field | Interpretation |
|---:|---|---|
| 0 | Elapsed | Seconds elapsed in the current sampling cycle |
| 1 | Device type | Device type value |
| 2 | Illuminance raw | Raw ambient-light value |
| 3 | MSP raw | MSP firmware encoding |
| 4–12 | Unclassified | Preserved 16-bit fields |
| 13 | Battery | Millivolts |
| 14 | Unclassified | Preserved 16-bit field |

The cycle start is estimated from host reception time:

```python
cycle_start = received_time - elapsed
```

This is an estimate based on when the host received the response.

### MSP firmware

The MSP raw value `0x8480` decodes to:

```text
2.4.2
```

The raw value is retained as `msp_firmware_raw`, and the decoded value is exposed under `airthingschip.msp`.

The decoder also handles a small set of known date-coded firmware values. Do not generalize that date encoding to unobserved values.

### Battery

The battery field is interpreted as millivolts.

Example:

```text
3044 mV = 3.044 V
```

### Unclassified fields

All other unpacked values are preserved. Their meanings remain unknown.

## 4. Configuration protocol

### Read

```text
66 00
```

### Write

```text
66 01
```

The read response is 24 bytes.

Example:

```text
66 00 3C 46 1E 19 69 00 CD 00 FA 00
D0 07 D5 02 E8 03 43 20 FF FF FF FF
```

### Field map

Offsets are relative to the beginning of the complete response.

| Offset | Size | Value | Meaning |
|---:|---:|---:|---|
| 0–1 | 2 | `66 00` | Response header |
| 2 | 1 | 60 | Humidity good → fair |
| 3 | 1 | 70 | Humidity fair → poor |
| 4 | 1 | 30 | Humidity fair → good |
| 5 | 1 | 25 | Humidity poor → fair |
| 6–7 | 2 | 105 | Radon low, little-endian |
| 8–9 | 2 | 205 | Radon high, little-endian |
| 10–11 | 2 | 250 | VOC low, little-endian |
| 12–13 | 2 | 2000 | VOC high, little-endian |
| 14–15 | 2 | 725 | CO₂ low, little-endian |
| 16–17 | 2 | 1000 | CO₂ high, little-endian |
| 18–19 | 2 | `0x2043` | Unknown word |
| 20–23 | 4 | `FF FF FF FF` | Response trailer |

### Humidity thresholds

Confirmed mappings:

- Poor → Fair = 25
- Fair → Good = 30
- Good → Fair = 60
- Fair → Poor = 70

### Units

- Radon: Bq/m³
- VOC: ppb
- CO₂: ppm

### Unknown word

The word at offsets 18–19 is currently `0x2043` (`43 20` on the wire). Its meaning is unknown.

Do not assign it to temperature thresholds without a controlled capture showing that relationship.

### Configuration write verification

The implementation:

1. Reads the current configuration.
2. Encodes the requested values using `WavePlusConfig`.
3. Sends the `66 01` write.
4. Receives the device's post-write configuration response.
5. Performs an explicit readback.
6. Verifies the resulting values.

A successful test verified radon thresholds of 105 / 205 Bq/m³.

## 5. History metadata

Before requesting history, the Plus implementation requests metadata.

Command:

```text
71 54 00
```

The response is 15 bytes:

```text
71 00 + 13-byte payload
```

Example:

```text
71 00 54 09 73 8B 6A 1B 02 2C C2 75 08 80 07
```

The payload is decoded using:

```python
struct.unpack("<BL4H", raw[2:])
```

| Field | Interpretation |
|---|---|
| Type | Metadata response type (`0x54`) |
| Series start | Unix timestamp |
| Unknown 1 | Unclassified 16-bit value |
| Unknown 2 | Unclassified 16-bit value |
| Number of records | Available history blocks |
| Unknown 3 | Unclassified 16-bit value |

The series start is converted to UTC for display.

Example metadata from testing:

- Series start: `1787523849`
- UTC: `2026-08-23T22:24:09Z`
- Available records: `2165`

The available record count is used to cap history requests.

## 6. History request

The Plus request is constructed using:

```python
struct.pack(
    "<BHHHH",
    0x01,
    self.MODE,
    0,
    self._history_request_hours,
    0
)
```

The mode is 2.

For the Plus implementation, the hours field is the requested number of additional blocks beyond the first block:

- Hours = 0 requests one block.
- Hours = 3 requests four blocks.

The requested block count is therefore:

```python
requested_blocks = requested_hours + 1
```

The device returns a six-byte packet-count acknowledgement.

Example:

```text
01 00 04 00 00 00
```

This reports four packets. It is an acknowledgement, not a transfer-completion notification.

## 7. History packet structure

Each history block is 230 bytes and contains 12 readings.

| Property | Value |
|---|---:|
| Packet length | 230 bytes |
| Records per packet | 12 |
| Block duration | 60 minutes |
| Sample interval | 300 seconds |

### Main data

The first 104 bytes are unpacked using:

```python
struct.unpack("<8H HH 12H 12B 12H 12H", data[:104])
```

| Values | Interpretation |
|---|---|
| 0–7 | Unclassified initial words |
| 8 | Radon ST |
| 9 | Radon LT |
| 10–21 | 12 temperatures |
| 22–33 | 12 humidities |
| 34–45 | 12 pressures |
| 46–57 | 12 CO₂ readings |

### Per-sample extras

Each sample has an eight-byte extra section beginning at offset 104:

```python
struct.unpack_from("<2HL", data, pos)
```

The current decoder exposes:

- `x4`: 16-bit raw value.
- `voc_ppb`: 16-bit VOC value.
- `x3`: 32-bit raw value, scaled by 1/256 in output.

X3 and X4 remain incompletely characterized.

### Packet tail

The final 30 bytes are unpacked using:

```python
struct.unpack("<12B 6B L 4H", data[200:230])
```

The first 12 bytes contain per-sample ambient-light values.

The series start timestamp and record number are extracted from the tail:

- Series start: packet offset 218, four bytes, little-endian.
- Record number: packet offset 228, two bytes, little-endian.

### Block identity

The block identity is:

```python
(series_start, record_number)
```

This is used for deduplication across polls.

### Timestamps

The block start time is:

```python
hour_start = series_start + record_number * 3600
```

Sample timestamps are:

```python
timestamp = hour_start + index * 300
```

The decoder exposes Unix timestamps and UTC ISO-8601 representations.

## 8. History collection

The Plus collector:

1. Retrieves metadata.
2. Determines the available block count.
3. Calculates the requested block count.
4. Requests raw BLE history packets through `WaveGeneric`.
5. Interprets the six-byte packet-count acknowledgement.
6. Filters empty sentinel packets.
7. Decodes valid 230-byte blocks.
8. Sorts blocks by series start and record number.
9. Merges them into HistoryStore.

The collector distinguishes notification count, unique packet count, duplicates, device-reported count, request rejection, and timeout status.

### Successful test

A three-hour request retrieved:

- Four expected blocks.
- Four notifications.
- Four unique raw packets.
- Zero duplicates.
- Zero sentinel packets.
- 48 decoded readings.
- No timeout.

The cumulative local HistoryStore at that test contained 2,022 unique blocks and 24,264 unique readings.

## 9. Other commands

### Flash light

```text
67 08
```

The implementation waits for a response beginning with `67 00`.

### Set device time

The command is constructed as:

```python
struct.pack("<BBLL", 0x71, 0x52, 1, unix_timestamp)
```

The expected response begins with:

```text
71 00 52
```

The response includes a confirmation value and a device timestamp.

This operation changes the device clock. Its exact semantics should be treated cautiously until further independently validated.

### Query 1

The implementation sends:

```text
66 00
```

and decodes a 21-byte response payload using:

```python
struct.unpack("<bBB9H", payload)
```

The configuration-read command uses the same command bytes in the current implementation. The response context and expected packet length must therefore be considered when distinguishing these operations. The field meanings of Query 1 remain undocumented.

## 10. Unresolved research

- Temperature threshold storage and commands.
- Meaning of configuration word `0x2043`.
- Meaning of the unclassified Query 2 fields.
- Meaning of the eight initial history words.
- Meaning of history X3 and X4.
- Meaning of metadata unknown fields.
- Commands `0x74`, `0x72 01 ...`, and `0x02 00`.

Do not infer temperature thresholds from `0x2043` without a controlled before/after capture.

## 11. Implementation status

| Feature | Status |
|---|---|
| Live sensor decoding | Working |
| ACP `0x6D` decoding | Working |
| MSP firmware decoding | Working |
| Battery voltage | Working |
| Configuration read | Working |
| Configuration write | Working |
| Explicit configuration readback | Working |
| Metadata request | Working |
| History request and transfer | Working |
| History decoding | Working |
| HistoryStore merging | Working |
| Flash light | Implemented |
| Set device time | Implemented; further validation desirable |
| Temperature thresholds | Unresolved |
| Unknown fields | Preserved for future research |
