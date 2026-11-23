# Usage Examples

Airthings Decoder includes standalone Python examples demonstrating how to communicate with supported Airthings Wave devices using their model-specific implementations.

These examples provide a starting point for experimenting with the device classes without running the full collection system or dashboard.

## Requirements

Before running an example:

- Python environment with the project dependencies installed.
- Bluetooth Low Energy (BLE) adapter.
- A supported Airthings Wave device within Bluetooth range.
- Permission for the Python process to access Bluetooth.

The examples use the project's existing device implementations and shared `WaveGeneric` functionality.

## Wave Mini

`UseMini.py` demonstrates communication with an Airthings Wave Mini using the `WaveMini` implementation.

Run:

```bash
python UseMini.py
```

The example demonstrates connecting to a Wave Mini and retrieving device information and sensor data.

Depending on the operations implemented in the example, it can also demonstrate device configuration, history collection, and Mini-specific ACP functionality.

The Wave Mini implementation is responsible for decoding its own sensor packets, configuration responses, and history data.

## Wave Plus

`UsePlus.py` demonstrates communication with an Airthings Wave Plus using the `WavePlus` implementation.

Run:

```bash
python UsePlus.py
```

The example demonstrates connecting to a Wave Plus and retrieving device information and sensor data.

Depending on the operations implemented in the example, it can also demonstrate device configuration and historical data collection.

The Wave Plus implementation handles its own model-specific sensor packets, configuration responses, and history data.

## Shared implementation

Both examples use model-specific classes that inherit shared functionality from `WaveGeneric`.

This allows common BLE communication and collection behavior to be reused while keeping device-specific protocol decoding separate.

The examples are useful starting points when exploring the device implementations or testing changes to the BLE communication and decoding code.

For details about the individual device protocols, see:

- [Wave Mini protocol](wave-mini-protocol.md)
- [Wave Plus protocol](wave-plus-protocol.md)
- [Protocol comparison](protocol-comparison.md)
- [History format](history-format.md)

## Notes

These are standalone usage examples, not replacements for the main collection workflow.

For device discovery, registry management, scheduled collection, persistent history, and the local dashboard, see [Architecture](architecture.md) and [Development](development.md).