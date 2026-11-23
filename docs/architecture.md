# Architecture

## Overview

Airthings Decoder is a local data collection and monitoring system for supported Airthings Wave devices.

It provides an independent alternative to relying on the Airthings cloud service. The system communicates directly with Wave devices over Bluetooth Low Energy (BLE), decodes live measurements and historical data, and stores the results locally.

The project has two primary user-facing interfaces:

- **Airthings Dashboard:** A locally hosted web dashboard designed to provide an Airthings-style view of device measurements, historical trends, device comparisons, outdoor conditions, and collection status. It also manages automatic polling and manual collection jobs.
- **Airthings Local:** A separate custom Home Assistant integration that retrieves stored device and history data through AirthingsAPI.

The system is composed of several distinct components:

- Device discovery and enrollment.
- Shared BLE communication and device-specific protocol decoding.
- Live measurement and historical data collection.
- Persistent sensor and ACP history storage.
- A read-only HTTP API for stored data.
- A dashboard backend responsible for collection management and frontend services.
- A Home Assistant integration that consumes the local API.

The components are separated so that device communication, persistent storage, data access, and user-facing applications can operate independently.

## System architecture

```text
                     Airthings Wave devices
                              |
                       Bluetooth LE
                              |
                 +------------+------------+
                 |                         |
              FindWave                 QueryWave
                 |                         |
           Device discovery          Device querying
           Model identification     Live measurements
           Registry updates         Configuration
                                    History collection
                                    Mini ACP collection
                                          |
                                          v
                                WaveGeneric / Models
                                          |
                                          v
                                    HistoryStore
                                          |
                                          v
                                Local persistent data
                                devices.json
                                history/
                                          |
                                          v
                                    AirthingsAPI
                                     (FastAPI)
                                          |
                            +-------------+-------------+
                            |                           |
                            v                           v
                     dashboard/server.js        Airthings Local
                     (Node.js backend)           (Home Assistant)
                            |
                            v
                    Dashboard Frontend
```

The main data flow is:

1. FindWave discovers supported devices and maintains the device registry.
2. QueryWave connects to registered devices and performs collection.
3. Shared and model-specific device implementations handle BLE communication and decoding.
4. HistoryStore manages persistent sensor and ACP history.
5. AirthingsAPI exposes stored data through a read-only HTTP interface.
6. The dashboard backend consumes AirthingsAPI and manages collection jobs.
7. Airthings Local consumes AirthingsAPI independently of the dashboard.

The dashboard backend additionally manages the collection process by launching QueryWave as a separate Python process.

FindWave is a separate discovery utility. It is used to identify devices and populate the device registry; it is not part of the dashboard's recurring polling scheduler.

## Component responsibilities

### FindWave.py — Device discovery

FindWave discovers nearby Airthings Wave devices and adds them to the local device registry.

Its responsibilities include:

- Scanning for BLE advertisements using Bleak.
- Identifying Airthings advertisements using manufacturer company ID `0x0334`.
- Extracting the device serial number from manufacturer data.
- Identifying Wave Mini and Wave Plus devices using their advertised names.
- Optionally verifying the model by connecting and checking its sensor characteristic UUID.
- Creating new device entries or updating existing hardware metadata in `devices.json`.

When an existing device is found, FindWave updates its model, model ID, and Bluetooth address without overwriting existing user settings or a previously assigned device name.

Model verification through a BLE connection is optional and disabled by default.

FindWave is primarily an enrollment and discovery tool. It does not collect historical data or run continuously as part of the dashboard scheduler.

### QueryWave.py — Device querying and collection

QueryWave is the operational device-querying script.

It reads the registered devices from `devices.json` and queries enabled devices using their corresponding model implementations.

For each selected device, it:

1. Scans for the device's RSSI.
2. Connects over BLE.
3. Retrieves live sensor readings.
4. Reads and decodes device configuration.
5. Saves the decoded configuration and update timestamp in `devices.json`.
6. Collects historical readings.
7. Collects ACP history for Wave Mini devices.
8. Disconnects from the device.

QueryWave supports:

- Querying all enabled registered devices.
- Selecting a device by serial number.
- Selecting devices by model when run directly.
- Collecting a configurable history window.
- Collecting all available history with `--full`.

The dashboard launches QueryWave as a separate Python process. It supplies the history window and, when appropriate, a device serial number or full-history flag.

QueryWave uses the shared device classes and HistoryStore rather than implementing model-specific BLE packet handling or persistent history management itself.

### WaveGeneric, WaveMini and WavePlus — Device implementations

`WaveGeneric.py` contains shared BLE communication and collection infrastructure.

The model-specific implementations provide the protocol behavior required by each device.

- `WaveMini.py` implements Wave Mini characteristics, packet decoding, configuration, history, and ACP functionality.
- `WavePlus.py` implements Wave Plus characteristics, packet decoding, configuration, and history functionality.

The two devices share common infrastructure, but their model-specific packet layouts and protocol behavior remain separate.

WaveGeneric provides common operations while delegating device-specific decoding and historical retrieval behavior to the appropriate model implementation.

### HistoryStore.py — Persistent history

HistoryStore manages the local persistence of collected historical data.

Its responsibilities include:

- Maintaining per-device sensor history.
- Maintaining per-device ACP history.
- Merging newly collected history with previously stored data.
- Deduplicating historical blocks and readings.
- Retaining relevant device and retrieval metadata.
- Providing a consistent stored representation for downstream consumers.

History is stored under the project's `history/` directory, with device-specific filenames based on model ID and serial number.

The primary storage formats are:

| Data | Storage format |
|---|---|
| Sensor history | JSON |
| ACP responses | JSON Lines (JSONL) |

HistoryStore is the owner of persistent history. Other components should use its functionality for writing collected history rather than implementing their own persistence logic.

The dashboard backend and AirthingsAPI consume stored data without independently managing history persistence.

### AirthingsAPI.py — Read-only data API

AirthingsAPI is a separate, local, read-only FastAPI service.

It exposes locally stored device information and historical data to applications that consume Airthings Decoder data.

Its primary consumers are:

- Airthings Local, the Home Assistant integration.
- `dashboard/server.js`, the dashboard backend.

Its responsibilities include:

- Listing enabled registered devices.
- Returning device details.
- Serving individual sensor history.
- Returning the latest valid sensor reading.
- Serving historical blocks.
- Exposing historical retrieval metadata.
- Serving stored ACP responses.
- Supporting timestamp filtering and pagination where applicable.

AirthingsAPI reads `devices.json` and the persistent history maintained by HistoryStore. It does not modify these files.

AirthingsAPI does not:

- Connect to BLE devices.
- Discover Airthings sensors.
- Run QueryWave.
- Schedule history collection.
- Decode sensor or configuration packets.
- Manage dashboard jobs.
- Modify stored history.

It provides a shared read-only data interface, allowing the dashboard and Home Assistant integration to consume the same stored data without independently implementing history-file access.

The API's HTTP contract is documented in `api.md`.

### dashboard/server.js — Dashboard backend and collection manager

The dashboard backend is a Node.js HTTP server that serves the local web interface and provides the dashboard's own API.

Its primary purpose is to provide a locally hosted Airthings-style dashboard while keeping device communication and data collection independent of the frontend.

It serves static frontend files from `dashboard/public/` and exposes dashboard-specific functionality through `/api/` routes.

The dashboard backend has two main responsibilities:

1. Managing device collection and dashboard operations.
2. Retrieving stored data through AirthingsAPI and preparing it for the frontend.

#### Dashboard data and visualization

The dashboard backend consumes stored sensor history and ACP data through AirthingsAPI rather than reading history files directly.

It continues to read and write `devices.json` for dashboard device management, including device names and enabled status.

It provides the frontend with:

- Registered devices and their enabled status.
- Latest available readings.
- Historical measurements.
- Wave Mini ACP data.
- Per-device history and measurement details.
- Historical comparisons between selected devices.
- Collection status and job information.
- Outdoor weather and air-quality conditions.

The backend retrieves stored history through AirthingsAPI, including timestamp-filtered history requests for dashboard comparisons.

This allows the dashboard to request only the relevant measurement period instead of repeatedly loading the complete history dataset.

The backend may normalize and prepare API records for frontend consumption, but persistent history ownership remains with HistoryStore.

The dashboard exposes its own API routes for frontend operations. These routes are separate from the endpoints provided by AirthingsAPI.

#### Automatic history polling

The dashboard manages recurring history collection.

The polling interval is configurable through the dashboard settings.

The default interval is 180 minutes (3 hours). When the dashboard server starts, it:

1. Starts the HTTP server.
2. Initializes the history scheduler.
3. Immediately queues a startup history collection.
4. Continues scheduling collection jobs at the configured interval.

The history lookback window is calculated from the polling interval:

`ceil(history_interval_minutes / 60) + 1`

This provides an additional hour of overlap when requesting history, helping ensure that readings are not missed between collection runs.

For example, a 180-minute polling interval produces a four-hour history lookback.

#### Collection job management

The dashboard does not implement BLE communication itself.

Instead, it launches `QueryWave.py` as a child process using the project's Python virtual environment.

Jobs are placed in an in-memory queue and processed sequentially. The backend tracks:

- Job ID and type.
- Target device, when applicable.
- Queued, running, completed, or failed status.
- Creation, start, and completion timestamps.
- Captured standard output and standard error.
- Error information.

The backend exposes job and collector status to the dashboard so the user can monitor collection activity.

Supported operations include:

- Automatic scheduled history collection.
- Immediate startup collection.
- Manual history collection for all enabled devices.
- Manual full-history collection.
- Manual history collection for an individual device.
- Manual full-history collection for an individual device.

A configurable delay is applied between completed jobs before the next queued job starts.

The queue and job state are held in memory; they are not a persistent job database.

#### Device management

The dashboard can update device names and enabled status through its API.

These changes are written back to `devices.json`.

This allows the user to manage the registered device list without manually editing the registry file.

Device registry management remains a dashboard responsibility rather than an AirthingsAPI responsibility.

#### Outdoor conditions

The dashboard also provides an outdoor weather and air-quality panel.

It uses the configured outdoor location and retrieves current conditions from Open-Meteo.

Location searches use the public Nominatim geocoding service.

Outdoor data includes available weather measurements, sunrise and sunset, and air-quality measurements such as PM2.5 and ozone.

The backend caches outdoor conditions and geocoding results to reduce unnecessary external requests.

#### Dashboard configuration

The dashboard maintains its own configuration file at:

`dashboard/server_config.json`

Settings include:

- HTTP port.
- History polling interval.
- Delay between collection jobs.
- Outdoor location and coordinates.

This configuration is distinct from the root-level `server_config.json` used by QueryWave for its own collection settings, including RSSI scan timeout and inter-device connection delay.

### Airthings Local — Home Assistant integration

Airthings Local is a separate custom Home Assistant integration.

It retrieves device and historical data from AirthingsAPI and exposes that information to Home Assistant.

Its responsibilities include:

- Creating and managing Home Assistant entities.
- Retrieving current device data.
- Exposing supported sensor measurements.
- Integrating historical measurements where supported.
- Managing Home Assistant-specific entity and statistics behavior.

The integration depends on a running local AirthingsAPI service and the data collected by Airthings Decoder.

Home Assistant does not need to establish its own BLE connection to retrieve each sensor update.

The integration's documentation should describe its setup and Home Assistant behavior. The Decoder's `api.md` documents the HTTP interface it consumes.

## Data flow

### Device discovery and enrollment

1. FindWave scans for nearby BLE advertisements.
2. It identifies supported Airthings devices and extracts their serial numbers.
3. It identifies the model using the advertised device name.
4. It optionally verifies the model through a BLE connection.
5. It adds or updates the device in `devices.json`.

### Device collection

1. QueryWave loads registered devices and selects enabled devices.
2. It instantiates the appropriate WaveMini or WavePlus implementation.
3. It connects to the device over BLE.
4. It retrieves live readings and configuration.
5. It collects historical data and, for Wave Mini, ACP history.
6. Model-specific decoders convert protocol packets into structured data.
7. HistoryStore merges and persists collected history.
8. QueryWave disconnects from the device.

### Dashboard operation

1. The Node.js dashboard server starts.
2. Its scheduler queues an initial collection job.
3. The server launches QueryWave as a child process.
4. QueryWave collects data and updates the local device registry and history storage.
5. The dashboard backend retrieves stored sensor history and ACP data through AirthingsAPI.
6. The backend prepares the data for its frontend routes.
7. The frontend displays current readings, historical trends, comparisons, outdoor conditions, and collection status.
8. Subsequent collection jobs are queued according to the configured polling interval or user actions.

The dashboard backend does not directly manage the persistent history files.

### Home Assistant operation

1. QueryWave collects device data and HistoryStore persists it.
2. AirthingsAPI reads the stored device and history data.
3. Airthings Local requests data through the API.
4. The integration exposes the supported information as Home Assistant entities and associated history.

The Home Assistant data flow is independent of the dashboard frontend and its Node.js API.

## Storage and configuration

| File or directory | Purpose |
|---|---|
| `devices.json` | Device registry, enabled status, names, hardware metadata, and decoded configuration |
| `history/` | Persistent per-device sensor history and ACP data |
| `server_config.json` | QueryWave collection settings |
| `dashboard/server_config.json` | Dashboard port, polling interval, job delay, and outdoor location |
| `dashboard/public/` | Dashboard frontend assets |
| `.venv/` | Python virtual environment used by the dashboard to launch QueryWave |

The components have distinct responsibilities for these files:

- FindWave manages device discovery and registry enrollment.
- QueryWave updates device information as part of collection.
- HistoryStore manages persistent history.
- AirthingsAPI reads the registry and stored history.
- `server.js` reads and updates dashboard-managed device settings and consumes stored history through AirthingsAPI.

## Design principles

- Device communication and data collection remain local.
- The dashboard provides a local Airthings-style user experience without requiring the Airthings cloud dashboard.
- Dashboard polling and manual collection use QueryWave rather than duplicating BLE logic in Node.js.
- Shared BLE mechanics belong in `WaveGeneric`.
- Model-specific protocol structures belong in their corresponding device implementations.
- HistoryStore owns persistent history merging and deduplication.
- AirthingsAPI provides a shared, read-only interface to stored data.
- The dashboard backend and Home Assistant integration consume the same underlying stored data through AirthingsAPI.
- The dashboard backend retains responsibility for collection scheduling, job management, and dashboard-specific operations.
- Raw packet data should be retained where practical to support future analysis.
- Unknown protocol fields remain unclassified until evidence supports an interpretation.
- The dashboard API and Home Assistant API have separate responsibilities and documentation.

## Documentation boundaries

- `development.md` describes source layout, component responsibilities, and development workflow.
- `protocol-methodology.md` describes the reverse-engineering approach and evidence standards.
- `protocol-comparison.md` describes shared protocol behavior and differences between supported devices.
- `wave-mini-protocol.md` and `wave-plus-protocol.md` describe device-specific protocol behavior.
- `history-format.md` describes shared history collection, storage, timestamps, and deduplication.
- `api.md` documents the HTTP API consumed by Airthings Local and the dashboard backend.
- The Airthings Local repository documents the Home Assistant integration.
- Dashboard-specific routes, settings, and frontend behavior belong in dashboard documentation or the dashboard source documentation.