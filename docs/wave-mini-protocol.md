**# Airthings Wave Mini BLE Protocol**

**\*\*Model:\*\*** Airthings Wave Mini  
**\*\*Model ID:\*\*** 2920  
**\*\*Implementation:\*\*** `WaveMini.py`  
**\*\*Configuration implementation:\*\*** `WaveMiniConfig.py`

**## 1. Overview**

This document describes the Bluetooth Low Energy (BLE) protocol currently implemented for the Airthings Wave Mini.

It covers:

- Device characteristics
- Live sensor data
- ACP (Additional Control Protocol) response
- Configuration reads and writes
- Historical data requests
- History packet structure and decoding
- Packet length validation
- Implementation status and unresolved protocol fields

The Wave Mini is documented independently from the Wave Plus. Similar command bytes or data fields do not necessarily indicate identical packet structures.

Unknown fields are preserved where practical and are not assigned meanings without supporting evidence.

**## 2. Device Characteristics**

| Characteristic | UUID |
|---|---|
| Service | `b42e3882-ade7-11e4-89d3-123b93f75cba` |
| Sensor data | `b42e3b98-ade7-11e4-89d3-123b93f75cba` |
| ACP | `b42e3ef4-ade7-11e4-89d3-123b93f75cba` |
| History data | `b42e41c4-ade7-11e4-89d3-123b93f75cba` |

**## 3. Live Sensor Data**

The live sensor characteristic returns a 20-byte packet.

**### 3.1 Current Decoder**

The current implementation uses:

```python
DATA_FORMAT = "<HHHHHHLL"
```

The packet is unpacked as:

```python
(
    unused01,
    temperature,
    pressure,
    humidity,
    voc,
    unused02,
    unused03,
    unused04,
) = struct.unpack(DATA_FORMAT, raw_data)
```

This represents six unsigned 16-bit values followed by two unsigned 32-bit values, all little-endian.

The expected packet length is:

- 6 × 2-byte values = 12 bytes
- 2 × 4-byte values = 8 bytes
- Total = 20 bytes

**### 3.2 Field Interpretation**

| Field | Conversion | Status |
|---|---|---|
| First 16-bit word | Not exposed | Unclassified |
| Temperature | `raw / 100 - 273.15` °C | Confirmed conversion |
| Pressure | `raw / 50` hPa | Confirmed conversion |
| Humidity | `raw / 100` % | Confirmed conversion |
| VOC | Raw value, ppb | Confirmed |
| Remaining 16-bit word | Not exposed | Unknown |
| First 32-bit word | Not exposed | Unknown |
| Second 32-bit word | Not exposed | Unknown |

**### 3.3 Alternative Byte Interpretation**

An upstream-style format has also been noted:

```python
struct.unpack("<2B5HLL", raw_data)
```

This separates the first two bytes into individual byte fields instead of interpreting them as one 16-bit word.

The current implementation does not assign meanings to those initial bytes.

Do not change the decoder's field interpretation without validating it against captured packets and device behavior.

**## 4. ACP Response**

The Mini ACP response provides additional device information beyond the live sensor characteristic.

The complete ACP response is exactly **34 bytes**.

The response consists of:

- A 2-byte command/status prefix.
- A 32-byte payload.

The payload structure was compared against the Airthings upstream struct format and confirmed to match:

```python
struct.unpack("<2L4B2HL4HL", payload)
```

**### 4.1 Response Length and Structure**

| Component | Offset | Length |
|---|---:|---:|
| Command/status prefix | 0–1 | 2 bytes |
| Airthings payload | 2–33 | 32 bytes |
| **Complete ACP response** | **0–33** | **34 bytes** |

The upstream payload format contains:

- Two unsigned 32-bit values
- Four unsigned 8-bit values
- Two unsigned 16-bit values
- One unsigned 32-bit value
- Four unsigned 16-bit values
- One unsigned 32-bit value

Total payload size: 32 bytes.

The complete response length is validated explicitly by the current implementation:

```python
if len(raw) != 34:
    return {
        "valid": False,
        "error": f"Unexpected ACP response length: {len(raw)}",
    }
```

The first response byte is also checked against the expected ACP command (`0x6D`).

**### 4.2 Confirmed Fields**

The current implementation decodes the payload using:

```python
values = struct.unpack("<2L4B2HL4HL", raw[2:])
```

The confirmed fields are:

| Field | Source | Status |
|---|---|---|
| BLE chip identifier | `values[1]` | Confirmed extraction |
| Subsystem identifier | `values[8]` | Confirmed extraction |
| Illuminance | `raw[22:24]` | Confirmed measurement, lux |
| Battery voltage | `values[11]` | Confirmed measurement, millivolts |

Battery voltage is also converted to volts:

```python
battery_voltage_v = battery_mv / 1000.0
```

The decoder returns:

```python
{
    "valid": True,
    "airthingschip": {
        "ble": values[1],
        "sub": values[8],
    },
    "illuminance_lux": illuminance_lux,
    "battery_mv": battery_mv,
    "battery_voltage_v": battery_mv / 1000.0,
    "raw_hex": raw.hex(" "),
}
```

Illuminance and battery are confirmed measurements, not speculative candidates.

The complete raw response is retained as hexadecimal data.

**### 4.3 ACP Field Interpretation**

The struct format establishes the layout and size of the 32-byte payload. It does not, by itself, establish the meaning of every field.

The current implementation exposes the fields whose extraction and interpretation have been established.

Other fields remain unclassified and should not be assigned meanings without independent evidence.

**\*\*Implementation note:\*\*** The previous decoder used a 28-byte minimum-length check because the fields being extracted at that time did not require the complete payload. That was not the confirmed protocol size. The current implementation correctly enforces an exact 34-byte response and decodes the complete 32-byte payload.

**## 5. Configuration Protocol**

The Wave Mini supports configuration reads and writes.

**### 5.1 Commands**

| Command | Operation |
|---|---|
| `66 00` | Read configuration |
| `66 01` | Write configuration |

Configuration thresholds use little-endian encoding for multi-byte values.

The current configuration implementation is in `WaveMiniConfig.py`.

**### 5.2 Read Response Structure**

The captured configuration response is 14 bytes.

| Offset | Length | Field | Interpretation |
|---:|---:|---|---|
| 0–1 | 2 bytes | Command | `66 00` |
| 2–5 | 4 bytes | Unknown prefix | Preserved; meaning unresolved |
| 6 | 1 byte | Humidity good-to-fair | Percentage threshold |
| 7 | 1 byte | Humidity fair-to-poor | Percentage threshold |
| 8 | 1 byte | Humidity fair-to-good | Percentage threshold |
| 9 | 1 byte | Humidity poor-to-fair | Percentage threshold |
| 10–11 | 2 bytes | VOC low | Unsigned 16-bit, little-endian |
| 12–13 | 2 bytes | VOC high | Unsigned 16-bit, little-endian |

The four-byte prefix is retained by the implementation so that configuration writes can reproduce it without assigning an unsupported meaning to those bytes.

The 14-byte length is an observed response length. It should not be treated as an established maximum or exact requirement for every possible configuration response.

**### 5.3 Captured Configuration Example**

Captured response after setting VOC thresholds to 275 / 2500:

```text
66 00 03 02 00 00 3C 46 1E 19 13 01 C4 09
```

Decoded values:

| Field | Value |
|---|---:|
| Unknown prefix | `03 02 00 00` |
| Humidity good-to-fair | 60% |
| Humidity fair-to-poor | 70% |
| Humidity fair-to-good | 30% |
| Humidity poor-to-fair | 25% |
| VOC low | 275 ppb |
| VOC high | 2500 ppb |

VOC values are decoded as unsigned 16-bit little-endian integers:

```text
13 01 = 275
C4 09 = 2500
```

**### 5.4 Humidity Thresholds**

The four humidity values define transitions between five displayed air-quality bands.

The implementation orders them as follows:

| Range | Displayed status |
|---|---|
| 0 to poor/fair | Poor |
| Poor/fair to fair/good | Fair |
| Fair/good to good/fair | Good |
| Good/fair to fair/poor | Fair |
| Fair/poor to 100 | Poor |

The decoder validates that the thresholds are in ascending order:

```python
humidity_poor_to_fair <= humidity_fair_to_good
humidity_fair_to_good <= humidity_good_to_fair
humidity_good_to_fair <= humidity_fair_to_poor
```

All values must be between 0 and 100.

These are configuration transition points, not direct humidity measurements.

**### 5.5 Configuration Writes**

A write packet is constructed using:

```text
66 01
[4-byte unknown prefix]
[4 humidity threshold bytes]
[2-byte VOC low, little-endian]
[2-byte VOC high, little-endian]
```

The implementation preserves the original four-byte prefix when reconstructing a write packet.

Example write packet using the captured configuration:

```text
66 01 03 02 00 00 3C 46 1E 19 13 01 C4 09
```

Validation currently enforces:

- Unknown prefix is exactly four bytes.
- Humidity thresholds are between 0 and 100.
- VOC thresholds are between 0 and 65535.

A configuration write should be followed by a read to verify that the device accepted and persisted the updated values.

**### 5.6 Configuration Implementation**

`WaveMiniConfig.py` provides:

| Function | Purpose |
|---|---|
| `decode_config(raw)` | Validates and decodes a configuration response |
| `config_to_dict(config)` | Returns dashboard-friendly decoded values |
| `humidity_bands(config)` | Generates the five humidity status bands |
| `print_config(config)` | Displays decoded configuration |
| `encode_config_write(config)` | Reconstructs a configuration write packet |
| `update_config(config, **changes)` | Creates an updated configuration without mutating the original |

The decoder uses:

```python
CONFIG_FORMAT = "<4B2H"
```

This represents four unsigned bytes followed by two unsigned 16-bit little-endian values.

**### 5.7 Unknown Configuration Fields**

| Field | Current understanding |
|---|---|
| Four-byte prefix | Preserved across writes; meaning unknown |
| Temperature thresholds | Not decoded |
| Optional response trailer | Not established |

Do not discard unknown bytes during a read-modify-write operation.

**## 6. History Protocol**

**### 6.1 Request Parameters**

| Property | Value |
|---|---:|
| Packet length | 205 bytes |
| Maximum records per packet | 12 |
| Packet duration | 60 minutes |
| Sample interval | 300 seconds |
| Record start offset | 25 |
| Record size | 15 bytes |
| Mode | 2 |
| `HOURS` field | 168 |

The `HOURS` value of 168 is a protocol field whose purpose has not been fully established for the Mini.

Routine collection uses three packets. Full-history collection requests up to 5000 packets.

A full-history request can cover approximately 208 days at one packet per hour. Requests beyond available history may produce empty notifications.

**### 6.2 Request Construction**

The Mini request is built as:

```python
struct.pack(
    "<BHHHH",
    0x01,
    self.MODE,
    requested_blocks - 1,
    self.HOURS,
    0,
)
```

The request fields are:

| Field | Value or meaning |
|---|---|
| Command | `0x01` |
| Mode | `2` |
| Requested packet count | Requested blocks minus one |
| Hours | `168` |
| Final field | `0` |

The request uses little-endian encoding.

The `HOURS` field is retained as an implementation parameter. Its exact role in the Mini history protocol remains unresolved.

**### 6.3 Command Acknowledgement**

The Mini handler reads the reported packet count from the final two bytes using big-endian order:

```python
int.from_bytes(data[-2:], "big")
```

A successful response begins with command `0x01` and status `0x00`.

The response count may be smaller than the requested count. The implementation treats a valid count no greater than the requested count as device confirmation of the available transfer.

**### 6.4 Packet Validation**

A history packet is accepted when:

- Its length is exactly 205 bytes.
- Its record count byte at offset 3 does not exceed 12.

The current implementation does not reject a packet merely because its block ID is zero.

**### 6.5 Block Identity**

The block ID is at byte offset 0.

The block timestamp is a little-endian 32-bit value at byte offset 4.

The deduplication identity is:

```python
(block_id, block_timestamp)
```

The timestamp is required because block IDs can wrap.

**## 7. History Packet Layout**

The Mini history packet is exactly 205 bytes.

| Offset | Size | Interpretation |
|---:|---:|---|
| 0 | 1 byte | Block ID |
| 1–2 | 2 bytes | Unclassified header |
| 3 | 1 byte | Record count |
| 4–7 | 4 bytes | Block timestamp, little-endian |
| 8–23 | 16 bytes | Other header fields, not yet fully classified |
| 24 | 1 byte | Header status |
| 25 onward | 15 bytes × record count | Sample records |

**### 7.1 Individual Record Layout**

Each record is 15 bytes.

| Relative offset | Size | Field | Interpretation |
|---:|---:|---|---|
| 0 | 1 byte | `flag` | Raw record flag |
| 1–2 | 2 bytes | `temp_raw` | Temperature |
| 3–4 | 2 bytes | `pressure_raw` | Pressure |
| 5–6 | 2 bytes | `rh_raw` | Relative humidity |
| 7–8 | 2 bytes | `voc` | VOC, ppb |
| 9–10 | 2 bytes | `u2` | Unknown |
| 11–14 | 4 bytes | `counter` | Raw counter |

The five 16-bit values are little-endian.

**### 7.2 Conversions**

- Temperature: `temp_raw / 100 - 273.15` °C
- Pressure: `pressure_raw / 50` hPa
- Humidity: `rh_raw / 100` %
- VOC: raw value, ppb

The flag, unknown value, and counter are retained in decoded records. Their meanings should not be inferred without additional evidence.

**### 7.3 Timestamps**

The block timestamp is interpreted as a Unix timestamp.

Sample timestamps are currently calculated as:

```python
timestamp = block_timestamp + index * 300
```

The implementation exposes both Unix timestamps and UTC ISO-8601 strings.

This five-minute spacing is the current decoder's timestamp model and should be checked against additional captured blocks if unusual record counts or partial blocks are encountered.

**## 8. History Collection**

The Mini collector supports:

- A requested duration converted to packet count.
- Full-history retrieval using the configured maximum request.
- Generic BLE transfer through `WaveGeneric.collect_history`.
- Device acknowledgement handling.
- Packet validation and deduplication.
- Model-specific block decoding.
- Persistent merging through `HistoryStore`.

The collector treats device confirmation as completion even if fewer packets were available than requested.

Empty notifications may be returned when the full-history request exceeds the available history.

**## 9. Packet Length Validation**

Packet lengths have been checked against captured BLE responses and the structures used by the implementation.

| Packet type | Length | Validation |
|---|---:|---|
| Live sensor | 20 bytes | Matches the current decoder structure |
| ACP payload | 32 bytes | Matches Airthings' upstream struct format |
| Complete ACP response | 34 bytes | Exact length enforced by decoder |
| Configuration response | 14 bytes observed | Captured response; decoder accepts the configuration structure |
| History packet | 205 bytes | Exact length enforced by decoder |

The ACP payload length is calculated from:

```python
struct.unpack("<2L4B2HL4HL", payload)
```

The resulting size is 32 bytes. Including the two-byte ACP prefix produces the complete 34-byte response.

History packet validation was tested against physical device responses. Both three-block and five-block transfers were successfully received and validated, with no short packets, long packets, or invalid record counts.

Observed packet lengths should be distinguished from decoder minimum-length requirements. The current ACP decoder enforces the complete 34-byte response, rather than the earlier 28-byte minimum check.

**## 10. Implementation Status**

| Feature | Status |
|---|---|
| Live sensor read | Implemented |
| Live temperature decoding | Implemented |
| Live pressure decoding | Implemented |
| Live humidity decoding | Implemented |
| Live VOC decoding | Implemented |
| ACP response collection | Implemented |
| ACP response length validation | Implemented; exactly 34 bytes |
| ACP payload structure | Confirmed against Airthings struct format |
| ACP BLE chip extraction | Implemented |
| ACP subsystem extraction | Implemented |
| ACP illuminance | Confirmed measurement |
| ACP battery voltage | Confirmed measurement |
| Configuration read | Implemented |
| Configuration write | Implemented |
| Configuration readback verification | Supported by configuration flow |
| Humidity threshold decoding | Implemented |
| VOC threshold decoding | Implemented |
| Unknown configuration prefix preservation | Implemented |
| Temperature threshold decoding | Not implemented |
| History request | Implemented |
| History packet validation | Implemented |
| History packet decoding | Implemented |
| History block identity | Implemented |
| Unknown header/record fields | Preserved; meanings unresolved |

**## 11. Open Questions**

1. What do the initial live sensor bytes represent?
2. What are the meanings of the remaining live sensor fields?
3. What is the complete semantic mapping of the 32-byte ACP payload?
4. Does the Mini history request's `HOURS` field have any effect on history retrieval, or is it ignored by the device?
5. What do the history header fields represent?
6. What do the record flag, unknown word, and counter represent?
7. Are timestamps always aligned to the block start plus five-minute intervals?
8. What do the four configuration prefix bytes represent?
9. Where are the temperature thresholds stored, and how are they encoded?
10. What is the meaning of any configuration response trailer?
11. Are the observed packet layouts consistent across Mini firmware revisions?

**## 12. Research and Validation Guidelines**

When investigating additional protocol fields:

- Preserve original raw BLE packets.
- Compare captures before and after changing one setting at a time.
- Record firmware versions and device model IDs.
- Distinguish byte extraction from semantic interpretation.
- Do not assign meanings to unknown values based on a single capture.
- Verify configuration writes through subsequent reads.
- Keep Wave Mini and Wave Plus packet structures separate unless equivalence is demonstrated.

A field being successfully unpacked does not establish its meaning.

Unknown bytes should remain preserved and explicitly unidentified until experiments support a reliable interpretation.