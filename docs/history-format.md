# History Collection and Storage

## Overview

Wave Mini and Wave Plus use different history packet formats, but share generic BLE transfer and persistent storage infrastructure.

`WaveGeneric.collect_history()` handles the common notification workflow. Each model supplies its own request builder, packet validation, identity function, completion interpretation, and decoder.

The generic collector handles packet transport and collection metadata. Model-specific implementations decode the history packets into structured blocks and individual measurements.

HistoryStore manages persistent storage, merging, and deduplication for both sensor history and ACP history.

## Generic collection responsibilities

The shared collector:

1. Validates the requested block count.
2. Builds a model-specific request.
3. Connects to the device if needed.
4. Subscribes to the command and history characteristics.
5. Sends the request.
6. Receives command responses and history notifications.
7. Validates packets.
8. Deduplicates packets using model-specific identity.
9. Waits for the expected completion condition or timeout.
10. Stops notifications and disconnects if it opened the connection.
11. Returns raw packets and transfer metadata.

The generic collector does not decode model-specific history measurements.

## Model-specific behavior

| Behavior | Wave Mini | Wave Plus |
|---|---|---|
| Packet size | 205 bytes | 230 bytes |
| Block identity | Block ID + timestamp | Series start + record number |
| Records per block | Up to 12 | 12 |
| Sample interval | 300 seconds | 300 seconds |
| Metadata preflight | Not used by current collector | Required |
| Completion | Device acknowledgement may confirm fewer available packets | Unique packet notifications determine received blocks; six-byte acknowledgement is not completion |

## Duplicate handling

A block identity must remain stable across repeated retrievals.

- Mini uses `(block_id, block_timestamp)` because the short block ID can wrap.
- Plus uses `(series_start, record_number)`.

HistoryStore merges decoded blocks and avoids storing the same logical block repeatedly.

Individual records are deduplicated using their block timestamp and record index.

Blocks are ordered by `block_timestamp`. Individual records are ordered chronologically using their measurement timestamps.

## Timestamps

Each individual history measurement has its own timestamp. All measurements within the same history block also share a block timestamp.

These fields represent different things and must not be treated as interchangeable.

| Field | Meaning |
|---|---|
| `timestamp` | Unix timestamp of the individual measurement |
| `timestamp_utc` | UTC ISO-8601 representation of the individual measurement timestamp |
| `block_timestamp` | Unix timestamp identifying the history block's time anchor |
| `block_time_utc` | UTC ISO-8601 representation of the block timestamp |

Both models contain up to 12 five-minute measurements per hourly block.

### Wave Mini

The Mini packet provides the block timestamp directly.

Individual measurement timestamps are derived from that block timestamp and the record's index:

`timestamp = block_timestamp + (index × 300)`

The first measurement has index `0` and therefore uses the block timestamp itself.

The twelfth measurement has index `11` and occurs 3,300 seconds after the block timestamp.

Each decoded measurement stores its own `timestamp` and `timestamp_utc`, while retaining the shared `block_timestamp` and `block_time_utc`.

### Wave Plus

Plus derives the beginning of each hourly block from the series start and record number:

`block_timestamp = series_start + (record_number × 3600)`

Individual measurement timestamps are then calculated from the block timestamp and record index:

`timestamp = block_timestamp + (index × 300)`

The first measurement uses the block timestamp. The twelfth measurement occurs 3,300 seconds later.

Decoded records retain both their individual measurement timestamps and the shared block timestamp. Series start and record number are also retained as block metadata.

### Timestamp handling

All timestamps are represented as Unix seconds and UTC ISO-8601 strings.

Use `timestamp` when working with individual measurements, including:

- Chronological ordering of measurements.
- Time-range filtering.
- Determining the latest measurement.
- Comparing measurements across devices.

Use `block_timestamp` when working with history blocks, including:

- Block ordering.
- Block identity and deduplication.
- Preserving the original history grouping.

Do not use `block_timestamp` as a replacement for an individual measurement's `timestamp`. Doing so would assign every measurement in a block the same time and produce incorrect historical ordering and comparisons.

## Persistent storage

History is stored per model and serial number, for example:

```text
history/
  2920_<serial>.json
  2930_<serial>.json
  2930_<serial>_acp.json
```

The exact output file set depends on the device and which collection operations have been run.

HistoryStore retains:

- Device metadata.
- Retrieval metadata.
- Decoded history blocks.
- Decoded individual records.
- Individual measurement timestamps.
- Shared block timestamps.
- Raw packet data.
- Cumulative unique block and record counts.

Sensor history preserves both the nested block structure and the individual records used for chronological access and analysis.

ACP responses are stored separately in JSON Lines (JSONL) format, with each response represented as an individual JSON object.

Raw packet hex is retained in decoded history records to support later re-analysis.

HistoryStore is responsible for merging newly collected data with existing data and preventing duplicate blocks and records.

## Transfer completeness

Do not conflate these conditions:

- The device accepted a request.
- The device reported a packet count.
- The expected number of notifications arrived.
- The expected number of unique blocks arrived.
- The transfer timed out.

For Wave Plus, the six-byte acknowledgement reports packet count but is not a transfer-completion notification.

For Wave Mini, the command response can report the number of available packets and may confirm completion even when fewer packets exist than the requested maximum.

## Partial results

The generic collector can return packets received before a timeout.

Callers should preserve transfer metadata so downstream users can distinguish complete history from partial retrieval.

Successfully received packets should remain available for storage even when a transfer is incomplete. A later collection can retrieve additional history, with HistoryStore handling merging and deduplication.