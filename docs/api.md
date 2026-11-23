# AirthingsAPI

## 1. Purpose

AirthingsAPI is a local, read-only HTTP API developed to expose data collected by Airthings Decoder.

It provides a structured interface to locally stored device information, sensor history, historical retrieval metadata, and ACP responses.

The API is implemented as a separate FastAPI service. It does not communicate directly with Airthings devices or perform data collection. Instead, it reads the device registry and persistent history maintained by Airthings Decoder.

Its primary consumer is the Airthings Local Home Assistant integration. Other local applications, including the Airthings Decoder dashboard server, can also consume the API.

AirthingsAPI does not:

- Connect to BLE devices.
- Discover Airthings sensors.
- Decode BLE packets.
- Request device history.
- Collect sensor measurements.
- Write or modify stored history.
- Manage device configuration.
- Provide the Home Assistant integration itself.

Those responsibilities belong to Airthings Decoder or its consumers.

## 2. Architecture

```text
Wave Mini / Wave Plus
        |
        | Bluetooth LE
        v
WaveGeneric / Device Models
        |
        | Decoded measurements
        | Historical retrieval
        v
HistoryStore.py
        |
        | Persistent storage
        v
devices.json + history/
        |
        v
AirthingsAPI (FastAPI)
        |
        | Local HTTP API
        |
        +----------------------+
        |                      |
        v                      v
Airthings Local          Dashboard Server
(Home Assistant)         (server.js)
        |                      |
        v                      v
Home Assistant           Dashboard Frontend
```

Responsibilities are separated as follows:

| Component | Responsibility |
|---|---|
| Device model classes | Device-specific BLE behavior and decoding |
| `WaveGeneric.py` | Shared BLE transport and generic device operations |
| `HistoryStore.py` | Persistent sensor history and ACP history |
| `devices.json` | Device registry and configuration |
| `AirthingsAPI.py` | Read-only HTTP access to stored data |
| `server.js` | Dashboard server, device management, scheduling, and dashboard-specific API |
| Dashboard frontend | Visualization and interaction |
| Airthings Local | Home Assistant entities and historical data integration |

AirthingsAPI is the boundary between persistent Decoder data and applications that consume it.

## 3. Data Sources

The API reads files relative to the directory containing `AirthingsAPI.py`.

| File or directory | Purpose |
|---|---|
| `devices.json` | Configured device registry |
| `history/` | Persisted device data |
| `history/{model_id}_{serial}.json` | Sensor history for an individual device |
| `history/{model_id}_{serial}_acp.json` | ACP response history for an individual device |

Sensor history is stored as JSON. ACP history is stored as JSON Lines (JSONL), with each line representing an individual response.

The API uses the device registry to identify configured devices and locate their associated history files.

Device serial numbers are treated as strings to preserve leading zeros.

Devices without an explicit `enabled` field are treated as enabled. Devices explicitly configured with `enabled: false` are excluded from API access.

The API does not modify these files.

## 4. API Information

| Property | Value |
|---|---|
| Framework | FastAPI |
| Server | Uvicorn |
| Application title | Airthings API |
| Default bind address | `0.0.0.0` |
| Default port | `8000` |
| Authentication | None implemented |
| Data access | Read-only |
| CORS configuration | No explicit CORS middleware configured |

The API is intended for trusted local-network use.

**Security note:** The service currently has no authentication or authorization layer. Binding to `0.0.0.0` makes it listen on all available network interfaces. Access should be restricted through appropriate firewall and network controls.

## 5. HTTP Endpoints

The current implementation exposes the following GET endpoints.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | API health check |
| GET | `/api/devices` | List enabled devices |
| GET | `/api/devices/{serial}` | Retrieve device information |
| GET | `/api/devices/{serial}/history` | Retrieve individual sensor history records |
| GET | `/api/devices/{serial}/latest` | Retrieve the latest valid sensor reading |
| GET | `/api/devices/{serial}/blocks` | Retrieve historical block data |
| GET | `/api/devices/{serial}/retrieval` | Retrieve historical retrieval metadata |
| GET | `/api/devices/{serial}/acp` | Retrieve stored ACP responses |

All endpoints are read-only. No API endpoint initiates BLE communication or changes persistent data.

### 5.1 Health Check

**Endpoint:**

```http
GET /health
```

Returns a basic health response and the current UTC timestamp.

This endpoint confirms that the API application is responding. It does not verify that every device has stored history or that BLE collection is operating.

### 5.2 List Devices

**Endpoint:**

```http
GET /api/devices
```

Returns configured, enabled devices.

The response includes device identification and information about the availability of associated stored data.

Device serial numbers are returned as strings.

The registry is the source of device configuration. The presence of a device in the response does not guarantee that it has valid history records.

### 5.3 Device Details

**Endpoint:**

```http
GET /api/devices/{serial}
```

Returns information for a specific configured device.

The serial number is matched as a string, preserving leading zeros.

This endpoint provides device-level information, including configured identification details and available stored-data information.

It does not retrieve or return the complete sensor history.

### 5.4 Sensor History

**Endpoint:**

```http
GET /api/devices/{serial}/history
```

Returns individual timestamped sensor measurements stored for the specified device.

The endpoint supports timestamp filtering, pagination, and ascending or descending ordering.

**Path parameter**

| Parameter | Required | Description |
|---|---|---|
| `serial` | Yes | Device serial number |

**Query parameters**

| Parameter | Default | Description |
|---|---:|---|
| `start` | None | Inclusive lower timestamp boundary |
| `end` | None | Exclusive upper timestamp boundary |
| `limit` | 1000 | Maximum records returned (1–10000) |
| `offset` | 0 | Number of filtered records to skip |
| `order` | `asc` | Timestamp ordering: `asc` or `desc` |

**Timestamp filtering**

The `start` and `end` parameters accept ISO-formatted timestamps.

Examples:

```text
2026-11-21T00:00:00Z
2026-11-21T12:30:00+00:00
2026-11-21T12:30:00
```

Timezone-aware timestamps are converted to Unix timestamps. Timestamps without an explicit timezone are interpreted as UTC.

The boundaries are:

- `start`: inclusive (`timestamp >= start`)
- `end`: exclusive (`timestamp < end`)

Example:

```http
GET /api/devices/008654/history?start=2026-11-21T00:00:00Z&end=2026-11-22T00:00:00Z
```

**Timestamp semantics**

Individual sensor records have their own measurement timestamps.

The API uses the individual `timestamp` when filtering, ordering, and identifying the latest measurement. It can also use supported legacy timestamp fields where necessary.

The `block_timestamp` field represents the timestamp associated with a historical block. It is not interchangeable with the individual measurement timestamp.

This distinction is important because multiple measurements within a block can have different individual timestamps.

**Ordering and pagination**

Records are ordered by their individual measurement timestamps.

Pagination is applied after timestamp filtering and sorting.

Example:

```http
GET /api/devices/008654/history?limit=500&offset=0&order=asc
```

Next page:

```http
GET /api/devices/008654/history?limit=500&offset=500&order=asc
```

The response includes:

| Field | Description |
|---|---|
| `total` | Number of matching records before pagination |
| `offset` | Current pagination offset |
| `limit` | Requested maximum page size |
| `returned` | Number of records returned |
| `next_offset` | Offset for the next page, or `null` when complete |
| `records` | Returned sensor history records |

The API preserves the stored record dictionaries rather than applying additional model-specific measurement conversions.

### 5.5 Latest Reading

**Endpoint:**

```http
GET /api/devices/{serial}/latest
```

Returns the latest valid sensor history record for a device.

The latest record is determined using the individual measurement timestamp rather than the enclosing historical block timestamp.

This endpoint is intended for consumers that need the most recent measurement without downloading the complete history.

### 5.6 Historical Blocks

**Endpoint:**

```http
GET /api/devices/{serial}/blocks
```

Returns stored historical block data for a device.

Historical blocks preserve the grouping of measurements as retrieved from the device.

Unlike the individual history endpoint, block retrieval is based on block-level timestamps and retains the nested records associated with each block.

The endpoint supports pagination.

This is useful for applications that need to inspect the original historical block structure rather than work exclusively with flattened individual measurements.

### 5.7 Retrieval Metadata

**Endpoint:**

```http
GET /api/devices/{serial}/retrieval
```

Returns historical retrieval metadata stored for a device.

This information describes the Decoder's historical collection process and provides context about retrieved data and collection progress.

Retrieval metadata is separate from individual sensor measurements and should not be interpreted as another sensor history stream.

The endpoint supports pagination.

### 5.8 ACP Responses

**Endpoint:**

```http
GET /api/devices/{serial}/acp
```

Returns stored ACP responses for a device.

ACP records are persisted separately from ordinary sensor history in JSONL format.

The API exposes these stored responses without initiating a new ACP request or BLE connection.

The endpoint supports pagination and returns the stored response objects.

ACP data may contain raw protocol fields, decoded information, and other response metadata. Their meaning remains dependent on the device-specific protocol implementation.

## 6. Error Handling

The API uses FastAPI request validation and HTTP exceptions for expected request errors.

Common conditions include:

| HTTP status | Condition |
|---|---|
| 400 | Invalid timestamp parameter |
| 404 | Device does not exist or is disabled |
| 404 | Requested stored data is unavailable |
| 422 | Invalid query parameter or validation constraint |

FastAPI also handles parameter validation, including invalid pagination values and unsupported ordering values.

Unexpected file access errors, malformed stored data, and other internal exceptions may result in server errors rather than a custom API response.

## 7. Data Responsibilities and Timestamp Semantics

Airthings Decoder owns the meaning and structure of device measurements and historical records.

AirthingsAPI exposes the stored data without silently changing device-specific protocol semantics.

Important principles:

- Preserve model IDs and serial numbers.
- Preserve original measurement timestamps.
- Preserve block-level timestamps separately from individual measurement timestamps.
- Preserve measurement units.
- Keep Wave Mini and Wave Plus fields distinct.
- Do not assign unsupported meanings to undecoded protocol fields.
- Preserve retrieval and completeness metadata where present.
- Do not assume every device model exposes identical measurement fields.

**Individual measurements and historical blocks**

The API exposes two related but distinct views of historical data:

- Individual history records are used for timestamp-based sensor queries and charting.
- Historical blocks preserve the original grouping and associated block metadata.

Applications should use the individual history endpoint for measurement timelines and the blocks endpoint when the original retrieval structure is needed.

## 8. Startup and Configuration

The API can be started directly through its Python entry point:

```bash
python3 AirthingsAPI.py
```

The application exposes the FastAPI instance as:

```python
app
```

It can also be started through an ASGI server:

```bash
uvicorn AirthingsAPI:app --host 0.0.0.0 --port 8000
```

The default service listens on port `8000` on all network interfaces.

The current implementation does not provide environment-variable configuration for the bind address, port, storage paths, or authentication.

## 9. Consumers

AirthingsAPI is designed to serve multiple local applications without duplicating access to the underlying history files.

### Airthings Local

Airthings Local is a separate Home Assistant custom integration that consumes AirthingsAPI.

Its responsibilities include:

- Creating and managing Home Assistant entities.
- Polling the local API for current device data.
- Exposing supported measurements to Home Assistant.
- Integrating historical measurements where supported.

The integration does not need to establish its own BLE connection to retrieve each sensor update.

### Dashboard Server

The Airthings Decoder dashboard uses a separate Node.js server implemented in `dashboard/server.js`.

The dashboard server consumes AirthingsAPI for stored sensor history and ACP data. It also handles dashboard-specific responsibilities such as device management, scheduling, and its own HTTP routes.

The dashboard frontend communicates with `server.js`, not directly with AirthingsAPI.

This distinction keeps the dashboard's application-specific routes separate from the underlying data API.

## 10. Current API Scope

| Feature | Status |
|---|---|
| Health endpoint | Implemented |
| Device listing | Implemented |
| Device detail endpoint | Implemented |
| Latest sensor reading | Implemented |
| Individual sensor history | Implemented |
| Start/end timestamp filtering | Implemented |
| History pagination | Implemented |
| Ascending/descending history ordering | Implemented |
| Historical block retrieval | Implemented |
| Retrieval metadata | Implemented |
| ACP response retrieval | Implemented |
| History write endpoints | Not implemented |
| Device configuration endpoints | Not implemented |
| BLE communication | Not implemented |
| Authentication | Not implemented |

## 11. API Contract Ownership

`AirthingsAPI.py` is the source of truth for:

- HTTP routes and methods.
- Query parameters.
- Request validation.
- Response structures.
- Error handling.
- Service startup and configuration.

Whenever the API implementation changes, update this document and the Airthings Local integration documentation where applicable.

Do not infer API routes from `dashboard/server.js`. The dashboard server is a separate application with its own routes and responsibilities.

---

**Project principle:** AirthingsAPI is a lightweight, read-only interface to locally collected Airthings data. BLE communication, device-specific decoding, historical collection, and persistent storage remain responsibilities of Airthings Decoder.