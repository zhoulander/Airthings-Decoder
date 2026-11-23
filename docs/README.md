# Airthings Decoder Documentation

This directory documents the Airthings Decoder project: a local data collection and monitoring system for supported Airthings Wave devices.

The decoder communicates directly with Airthings devices over Bluetooth Low Energy (BLE), decodes live measurements and historical data, and stores collected data locally. It provides an independent alternative to relying on the Airthings cloud service.

The project includes a local API and web dashboard for accessing device data, managing collection, and viewing historical measurements.

## Supported devices

The decoder currently supports the following devices:

| Device | Model ID | Implementation |
|---|---:|---|
| Airthings Wave Mini | 2920 | `WaveMini.py` |
| Airthings Wave Plus | 2930 | `WavePlus.py` |

Both devices use shared BLE transport and generic history collection functionality through `WaveGeneric.py`. Their packet layouts, characteristics, and device-specific protocol behavior are implemented separately.

## How to run Airthings Decoder

### Requirements

- Python 3.11 or later
- Node.js
- Bluetooth Low Energy (BLE) adapter
- A computer within Bluetooth range of the Airthings Wave devices

The decoder has been tested on macOS with Apple Silicon. Other platforms may work but have not necessarily been verified.

### 1. Install Python dependencies

Clone the repository and navigate into the project directory.

Create and activate a Python virtual environment, then install the required dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Discover devices

Run `FindWave.py` to scan for nearby Airthings Wave devices and register discovered devices in `devices.json`.

```bash
python FindWave.py
```

This is normally a one-time setup step. Run it again whenever you want to discover and register additional devices.

### 3. Start the local API

From the project root, start the API service:

```bash
source .venv/bin/activate
python AirthingsAPI.py
```

The API runs on port `8000` and provides read-only access to locally stored device data.

Leave this process running.

### 4. Start the dashboard

Open a second terminal, navigate to the dashboard directory, and start the Node.js server:

```bash
cd dashboard
node server.js
```

The dashboard server automatically creates `server_config.json` with default settings if it does not already exist.

Open the dashboard in a browser using the configured port.  
http://localhost:3000/index.html

Leave this process running alongside the API service.

### Normal operation

Once both services are running, the dashboard provides the primary interface for operating the decoder.

- **Manual collection:** Trigger device collection through the dashboard.
- **Scheduled collection:** The dashboard server automatically schedules collection according to the configured polling interval.
- **Device management:** Manage registered devices through the dashboard.
- **Historical data:** View stored sensor measurements and ACP responses through the dashboard.

The dashboard server launches `QueryWave.py` when collection is requested or scheduled. It manages the collection jobs, so `QueryWave.py` does not normally need to be run manually.

`AirthingsAPI.py` does not communicate with devices or collect measurements. It provides access to data already collected and stored locally by the decoder.

### Component responsibilities

| Component | Operation | Responsibility |
|---|---|---|
| `FindWave.py` | Run manually when needed | Discovers nearby devices and registers them |
| `AirthingsAPI.py` | Run as a service | Provides read-only access to stored data |
| `dashboard/server.js` | Run as a service | Hosts the dashboard and manages collection jobs and scheduling |
| `QueryWave.py` | Launched by `server.js` | Communicates with devices over BLE and collects data |

Both `AirthingsAPI.py` and `dashboard/server.js` must remain running for the complete dashboard experience.

## Home Assistant integration

[Airthings Local](https://github.com/zhoulander/airthings-local) is a separate Home Assistant custom integration that consumes data from the decoder's local API.

This separates physical device communication from Home Assistant's normal data-update cycle. Home Assistant retrieves measurements from the API without requiring a new BLE connection to an Airthings device for every entity update.

The decoder's collection schedule can therefore be configured independently of Home Assistant's polling interval.

### Historical data retrieval

A key feature of Airthings Decoder is its ability to retrieve historical measurements stored internally by supported Airthings Wave devices.

The decoder communicates with devices through scheduled, periodic BLE sessions, retrieving measurements and historical records in batches. Rather than waking a device for every five-minute Home Assistant update, the decoder can collect data less frequently and retrieve measurements accumulated since its previous collection.

The historical collection system is designed to:

- Retrieve historical measurements directly from the device over BLE.
- Decode device-specific historical data packets.
- Preserve original measurement timestamps.
- Handle overlapping retrieval windows and avoid duplicate records.
- Store collected history locally so it remains available between BLE sessions.
- Expose historical measurements through the local API for use by Home Assistant.

### Entity history and long-term statistics

Home Assistant maintains two distinct forms of historical data:

- **Entity history:** Individual timestamped sensor states, which can preserve original measurement times when imported through an appropriate historical-record mechanism.
- **Long-term statistics:** Aggregated hourly statistics derived from sensor measurements, which can be imported separately through Home Assistant's statistics mechanisms.

Keeping these separate allows the integration to represent both original measurements and longer-term statistical summaries.

### Separation of responsibilities

The projects have distinct responsibilities:

- **Airthings Decoder:** BLE communication, device-specific decoding, historical retrieval, deduplication, persistent storage, and local API.
- **Airthings Local:** Home Assistant entities, data updates, and integration of available historical measurements into Home Assistant.

This architecture allows Airthings devices to be accessed locally while minimizing unnecessary BLE activity and preserving historical measurements independently of Home Assistant's polling schedule.

## Documentation

The following documents describe the implementation, architecture, and protocol research in greater detail.

| Document | Contents |
|---|---|
| [Architecture](architecture.md) | Project components and the data flow from device to Home Assistant |
| [Development](development.md) | Source layout, component responsibilities, and development workflow |
| [Protocol Methodology](protocol-methodology.md) | Capture analysis, evidence levels, and reverse-engineering methodology |
| [Protocol Comparison](protocol-comparison.md) | Shared protocol behavior and differences between Wave Mini and Wave Plus |
| [Wave Mini Protocol](wave-mini-protocol.md) | Wave Mini characteristics, live readings, ACP, and historical data |
| [Wave Plus Protocol](wave-plus-protocol.md) | Wave Plus characteristics, ACP, configuration, and historical data |
| [History Format](history-format.md) | Shared history collection, deduplication, timestamps, and persistent storage |
| [Local API](api.md) | AirthingsAPI endpoints and their relationship to Airthings Local |
| [Usage Examples](examples.md) | Standalone usage examples for Wave Mini and Wave Plus |

## Tested Hardware and Environment

Airthings Decoder has been developed and tested in the following environment:

| Component | Tested configuration |
|---|---|
| Computer | Apple MacBook with M1 processor |
| Operating system | macOS Sequoia 15.5 |
| Bluetooth | Built-in Bluetooth LE |
| Python | 3.11.0 |
| Devices | Airthings Wave Mini and Wave Plus |

### Hardware compatibility

The decoder communicates with Airthings devices over Bluetooth Low Energy (BLE). Compatibility may depend on the host's Bluetooth adapter, chipset, operating system, drivers, and BLE support.

The project has currently been tested on Apple Silicon using macOS. Linux systems, Raspberry Pi devices, and external Bluetooth adapters have not necessarily been tested.

Other platforms may work, but should be considered unverified until tested.

## Protocol documentation

The protocol documentation describes the observed BLE behavior and decoded data structures for each supported device.

The documentation distinguishes between different levels of certainty:

- **Confirmed:** Verified through captured packets, repeatable tests, or known device behavior.
- **Strongly supported:** Supported by multiple observations or consistent protocol behavior, but not yet fully verified.
- **Observed:** Seen in captures or device responses, but its meaning or behavior is not completely understood.
- **Unknown:** Not yet decoded or sufficiently investigated.

These labels are intended to make the distinction between verified behavior and ongoing reverse-engineering work clear.

## Project scope

This documentation describes the current implementation and research findings of Airthings Decoder. It is not an official Airthings protocol specification.

Where protocol behavior is uncertain, the documentation aims to preserve that uncertainty rather than assign unsupported meanings to packet fields. Raw packet data and the corresponding implementation should be treated as the primary references when investigating device behavior.

## Related projects

- [Airthings Local](https://github.com/trooperthorn/ha_int_airthings) — Home Assistant custom integration that consumes data from Airthings Decoder's local API.

## References and acknowledgements

This project builds on earlier community research, independent implementations, and resources published by Airthings.

### Earlier work and community projects

- [atw-mqtt](https://github.com/zhoulander/atw-mqtt/tree/master) — My original Airthings MQTT decoder implementation from 2020.
- [Airthings Wave+ Defacto API With History](https://sifter.org/simon/journal/20191210.1.html) — Simon Funk's research into the Wave Plus protocol and historical data.
- [airthingswave-mqtt](https://github.com/hpeyerl/airthingswave-mqtt) — Community implementation by hpeyerl.
- [waveplus-reader](https://github.com/stenjo/waveplus-reader) — Community Wave Plus implementation by stenjo.

### Airthings resources and implementations

- [Airthings Raspberry Pi resources](https://www.airthings.com/resources/raspberry-pi)
- [Airthings airthings-ble](https://github.com/Airthings/airthings-ble)
- [Airthings wave-reader](https://github.com/Airthings/wave-reader)
- [Airthings waveplus-reader](https://github.com/Airthings/waveplus-reader)
- [Airthings wavemini-reader](https://github.com/Airthings/wavemini-reader)

Thanks to the authors and contributors whose research and implementations helped make this work possible.

Airthings Decoder is an independent project and is not affiliated with or endorsed by Airthings.

## License

Airthings Decoder is released under the [MIT License](../LICENSE).

This project includes code derived from or adapted from other MIT-licensed work. Original copyright notices and license terms are retained where applicable.

See the `LICENSE` file in the repository for the full license text.