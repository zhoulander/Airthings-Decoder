# Development

## Source layout

The project is organized around device discovery, shared BLE communication, model-specific implementations, history persistence, and local data serving.

| File or directory | Responsibility |
|---|---|
| `FindWave.py` | BLE device discovery, model identification, and device registry enrollment |
| `QueryWave.py` | Operational device querying, live measurements, configuration retrieval, history collection, and ACP collection |
| `WaveGeneric.py` | Shared BLE transport, connection handling, and reusable collection infrastructure |
| `WaveMini.py` | Wave Mini characteristics, live sensor decoding, ACP handling, configuration behavior, and history protocol |
| `WavePlus.py` | Wave Plus characteristics, live sensor decoding, configuration behavior, and history protocol |
| `WaveMiniConfig.py` | Wave Mini configuration encoding and decoding |
| `WavePlusConfig.py` | Wave Plus configuration encoding and decoding |
| `HistoryStore.py` | Persistent sensor and ACP history, merging, deduplication, and retrieval metadata |
| `AirthingsAPI.py` | Read-only FastAPI service exposing registered devices and stored history |
| `devices.json` | Device registry, names, enabled status, hardware metadata, and decoded configuration |
| `history/` | Per-device persistent sensor history and ACP data |
| `dashboard/server.js` | Node.js dashboard backend, collection scheduler, job queue, device management, and dashboard API |
| `dashboard/public/` | Dashboard frontend assets |
| `dashboard/server_config.json` | Dashboard settings, including port, polling interval, job delay, and outdoor location |
| `Airthings Local/` | Separate Home Assistant integration consuming AirthingsAPI |

The exact set of files may evolve. Update this table when the source layout changes.

## Component responsibilities

### Device discovery

`FindWave.py` is responsible for discovering supported devices and enrolling them in `devices.json`.

It is separate from the recurring collection process. It should not implement historical data collection or persistent history management.

### Device querying and collection

`QueryWave.py` coordinates collection from registered devices.

It selects the appropriate model implementation, performs the requested collection operations, and passes collected data to the shared storage layer.

It should not duplicate model-specific BLE decoding or implement its own history persistence.

### Shared BLE behavior and model separation

`WaveGeneric.py` owns reusable BLE transport and collection behavior. Device classes provide model-specific hooks and constants.

Examples of model-specific behavior include:

- Sensor characteristic UUID and data format.
- ACP characteristic UUID and command.
- History data characteristic UUID.
- History packet length and validation.
- History request construction.
- History packet identity.
- History packet decoding.
- Configuration protocol.

Do not move a model-specific packet layout into the generic class merely because another model has a similarly named field.

Keep shared transport and reusable collection mechanics in `WaveGeneric.py`. Keep protocol-specific behavior in the appropriate model implementation.

### History persistence

`HistoryStore.py` owns persistent sensor and ACP history.

It is responsible for:

- Appending and merging collected history.
- Deduplicating historical blocks and readings.
- Maintaining per-device history files.
- Persisting ACP responses.
- Maintaining relevant retrieval metadata.

Other components should use HistoryStore for history persistence rather than independently writing or modifying history files.

### Local data API

`AirthingsAPI.py` provides a read-only FastAPI interface to the device registry and stored history.

It reads `devices.json` and the history maintained by HistoryStore. It does not perform BLE communication, run collection, schedule jobs, or modify stored history.

The API is consumed by both the dashboard backend and Airthings Local.

When changing the API:

- Keep its read-only responsibility.
- Preserve existing endpoint behavior unless a deliberate API change is intended.
- Keep timestamp filtering and pagination consistent.
- Preserve the distinction between individual measurement timestamps and block timestamps.
- Update `api.md` when endpoints, parameters, or response structures change.

### Dashboard backend

`dashboard/server.js` provides the dashboard's Node.js backend.

It is responsible for:

- Serving the dashboard frontend.
- Managing dashboard-specific HTTP routes.
- Reading and updating dashboard-managed device settings in `devices.json`.
- Scheduling automatic collection.
- Launching `QueryWave.py` as a child process.
- Managing the collection job queue and job status.
- Retrieving stored sensor history and ACP data through AirthingsAPI.
- Preparing data for dashboard frontend consumption.

The dashboard backend must not independently read or write persistent history files. History access belongs behind AirthingsAPI, while persistence belongs to HistoryStore.

The dashboard frontend communicates with `server.js`, not directly with AirthingsAPI.

## Development workflow

### Protocol investigation and decoding

1. Capture or obtain a raw packet from the target device.
2. Preserve the complete packet, including command and status bytes where present.
3. Identify the packet length and candidate field boundaries.
4. Compare multiple packets or controlled before-and-after changes.
5. Implement the smallest model-specific decoding change.
6. Test against the captured packet and, when possible, the physical device.
7. Confirm that raw data remains available in the output.
8. Update the relevant protocol document and evidence status.

### Collection and storage changes

When changing collection or history behavior:

1. Identify whether the behavior belongs in `QueryWave.py`, `WaveGeneric.py`, or a model-specific implementation.
2. Keep BLE communication and decoding separate from persistent storage.
3. Use HistoryStore for history writes, merging, and deduplication.
4. Test repeated collection to verify that existing history is not duplicated or lost.
5. Confirm that sensor history, ACP data, and retrieval metadata remain consistent.
6. Verify that the stored output can still be read by AirthingsAPI.

### API and dashboard changes

When changing AirthingsAPI or the dashboard:

1. Identify whether the change belongs in the shared read-only API or the dashboard-specific backend.
2. Keep AirthingsAPI independent of BLE collection and dashboard job management.
3. Keep dashboard collection scheduling and job management in `server.js`.
4. Use AirthingsAPI for dashboard access to stored sensor history and ACP data.
5. Test API endpoints and dashboard routes independently.
6. Confirm that the frontend continues to receive the expected response structures.
7. Update the relevant API or dashboard documentation.

## Testing principles

- Test Wave Mini and Wave Plus independently.
- Validate exact packet lengths before unpacking fixed-size structures.
- Check endianness explicitly.
- Keep raw bytes in saved ACP and history records.
- Test short, malformed, and unexpected BLE responses.
- Confirm that notification subscriptions are cleaned up after success and failure.
- Test history deduplication across repeated polls.
- Confirm that ACP responses are persisted and can be retrieved through AirthingsAPI.
- Verify API pagination, filtering, ordering, and timestamp handling.
- Test dashboard collection jobs independently of the frontend.
- Confirm that dashboard history requests go through AirthingsAPI.
- Avoid changing working BLE collection behavior without evidence of a defect.

## Local environment

The implementation uses Python and Bleak for BLE communication. The local data API uses FastAPI. The dashboard backend uses Node.js and serves its frontend from `dashboard/public/`.

Python dependencies are managed through the project's virtual environment.

The dashboard launches QueryWave using the project's virtual environment rather than relying on the system Python installation.

Install and launch commands should be maintained alongside the actual dependency manifest and service configuration. This document intentionally does not prescribe package versions or launch commands without verifying the repository's current environment files.

## Documentation maintenance

Keep documentation aligned with the component that owns the behavior:

- `architecture.md` describes the overall system and component relationships.
- `development.md` describes source layout, responsibilities, and development workflow.
- `protocol-methodology.md` describes the reverse-engineering approach and evidence standards.
- `protocol-comparison.md` describes shared protocol behavior and differences between supported devices.
- `wave-mini-protocol.md` and `wave-plus-protocol.md` describe device-specific protocol behavior.
- `history-format.md` describes history collection, storage, timestamps, and deduplication.
- `api.md` documents the read-only HTTP API.
- Dashboard documentation describes dashboard-specific routes, settings, and frontend behavior.
- Airthings Local documentation describes the Home Assistant integration.