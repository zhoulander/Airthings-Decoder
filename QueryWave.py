
import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakScanner

from WaveMini import WaveMini
from WaveMiniConfig import config_to_dict as mini_config_to_dict
from WavePlus import WavePlus
from WavePlusConfig import config_to_dict as plus_config_to_dict


PROJECT_DIR = Path(__file__).resolve().parent
DEVICES_FILE = PROJECT_DIR / "devices.json"
CONFIG_FILE = PROJECT_DIR / "server_config.json"

MODEL_CLASSES = {
    "WaveMini": WaveMini,
    "WavePlus": WavePlus,
}

DEFAULT_HISTORY_HOURS = 3
RSSI_SCAN_TIMEOUT = 5
DEVICE_CONNECT_DELAY = 5

MAX_DEVICE_ATTEMPTS = 3
DEVICE_RETRY_DELAY = 5

def emit_event(event_data):
    """Emit a structured event for server.js to capture."""
    print(
        f"EVENT_JSON:{json.dumps(event_data)}",
        flush=True,
    )

def load_config():
    defaults = {
        "history_hours": DEFAULT_HISTORY_HOURS,
        "device_connect_delay_seconds": DEVICE_CONNECT_DELAY,
        "rssi_scan_timeout_seconds": RSSI_SCAN_TIMEOUT,
    }

    if not CONFIG_FILE.exists():
        print("Config not found; using defaults.")
        return defaults

    try:
        with CONFIG_FILE.open("r") as file:
            config = json.load(file)

        for key, default in defaults.items():
            try:
                value = float(config.get(key, default))
                if value < 0:
                    raise ValueError
                defaults[key] = value
            except (TypeError, ValueError):
                print(f"Invalid config value for {key}; using {default}.")

    except (OSError, json.JSONDecodeError) as error:
        print(f"Could not read server_config.json: {error}")
        print("Using defaults.")

    return defaults


def load_devices():
    if not DEVICES_FILE.exists():
        raise FileNotFoundError(f"Device registry not found: {DEVICES_FILE}")

    with DEVICES_FILE.open("r") as file:
        registry = json.load(file)

    return registry.get("devices", [])


def save_device_config(serial, config_data):
    with DEVICES_FILE.open("r") as file:
        registry = json.load(file)

    for device in registry.get("devices", []):
        if str(device.get("serial")) != str(serial):
            continue

        device["config"] = config_data
        device["config_updated"] = datetime.now(timezone.utc).isoformat()

        temp_file = DEVICES_FILE.with_suffix(".tmp")
        with temp_file.open("w") as file:
            json.dump(registry, file, indent=4)
            file.write("\n")

        temp_file.replace(DEVICES_FILE)
        print(f"Saved configuration for device {serial}.")
        return

    raise ValueError(f"Device {serial} not found in devices.json")


def select_devices(devices, serial=None, model=None):
    if serial:
        devices = [
            device for device in devices
            if str(device.get("serial")) == str(serial)
        ]

    if model:
        devices = [
            device for device in devices
            if device.get("model") == model
        ]

    return devices


async def get_device_rssi(target_address):
    devices = await BleakScanner.discover(
        timeout=RSSI_SCAN_TIMEOUT,
        return_adv=True,
    )

    for address, (_, advertisement) in devices.items():
        if address.upper() == target_address.upper():
            return advertisement.rssi

    return None


async def query_device(device_info, args):
    serial = str(device_info["serial"])
    model_name = device_info["model"]
    mac = device_info["mac"]

    model_class = MODEL_CLASSES.get(model_name)
    if model_class is None:
        raise ValueError(f"Unsupported model: {model_name}")

    sensor = model_class(serial, mac)
    connected = False

    print(f"\n{'=' * 55}")
    print(f"DEVICE: {device_info.get('name', model_name)}")
    print(f"{'=' * 55}")
    print(f"Serial:  {serial}")
    print(f"Model:   {model_name}")
    print(f"Model ID: {device_info.get('model_id')}")
    print(f"Address: {mac}")

    try:
        if args.scan_rssi:
            rssi = await get_device_rssi(mac)
            print(f"RSSI:    {rssi} dBm" if rssi is not None else
                  "RSSI:    Not detected during scan")
        else:
            print("RSSI:    Scan skipped.")

        print("\nConnecting...")
        await sensor.connect()
        connected = True
        print("Connected.")

        if args.include_config:
            print("\n========== DEVICE CONFIGURATION ==========")
            config = await sensor.collect_config()

            config_data = (
                mini_config_to_dict(config)
                if model_class is WaveMini
                else plus_config_to_dict(config)
            )
            save_device_config(serial, config_data)
        else:
            print("\nSkipping device configuration.")

        print("\n========== HISTORY ==========")
        if args.full:
            print("Collecting full history...")
            await sensor.collect_history(full=True)
        else:
            print(f"Collecting last {args.hours} hours...")
            await sensor.collect_history(hours=args.hours)


        print("\n========== ACP HISTORY ==========")
        await sensor.collect_acp()

        return True, None

    except Exception as error:
        error_message = f"{type(error).__name__}: {error}"
        print(f"\nFAILED: {error_message}")
        return False, error_message

    finally:
        if connected:
            print("\nDisconnecting...")
            try:
                await sensor.disconnect()
                print("Disconnected.")
            except Exception as error:
                print(f"Disconnect error: {type(error).__name__}: {error}")


async def main():
    global RSSI_SCAN_TIMEOUT, DEVICE_CONNECT_DELAY

    parser = argparse.ArgumentParser(
        description="Query registered Airthings Wave devices."
    )

    history = parser.add_mutually_exclusive_group()
    history.add_argument(
        "--hours",
        type=int,
        help="History window in hours (overrides server_config.json).",
    )
    history.add_argument(
        "--full",
        action="store_true",
        help="Collect all available history.",
    )

    parser.add_argument(
        "--include-config",
        action="store_true",
        help="Include device configuration collection.",
    )

    parser.add_argument(
        "--scan-rssi",
        action="store_true",
        help="Scan for device RSSI before connecting.",
    )

    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--serial",
        help="Query one device by serial number.",
    )
    selection.add_argument(
        "--model",
        choices=MODEL_CLASSES.keys(),
        help="Query all devices of a specific model.",
    )

    args = parser.parse_args()
    config = load_config()

    RSSI_SCAN_TIMEOUT = config["rssi_scan_timeout_seconds"]
    DEVICE_CONNECT_DELAY = config["device_connect_delay_seconds"]

    if not args.full:
        args.hours = (
            args.hours
            if args.hours is not None
            else int(config["history_hours"])
        )

    if args.hours is not None and args.hours <= 0:
        parser.error("--hours must be greater than zero")

    print(f"\n{'=' * 55}")
    print("AIRTHINGS QUERY")
    print(f"{'=' * 55}")
    print(f"History hours:        {'Full' if args.full else args.hours}")
    print(f"Device connect delay: {DEVICE_CONNECT_DELAY}s")
    print(f"RSSI scan timeout:    {RSSI_SCAN_TIMEOUT}s")

    devices = load_devices()
    selected = select_devices(
        devices,
        serial=args.serial,
        model=args.model,
    )
    selected = [
        device for device in selected
        if device.get("enabled", True) is not False
    ]

    if not selected:
        print("No enabled matching devices found in devices.json.")
        return

    print(f"Registered devices:      {len(devices)}")
    print(f"Enabled devices selected: {len(selected)}")

    successful = 0
    failed_devices = []

    for index, device_info in enumerate(selected):
        if index > 0:
            print(f"\nWaiting {DEVICE_CONNECT_DELAY} seconds for Bluetooth...")
            await asyncio.sleep(DEVICE_CONNECT_DELAY)

        device_name = device_info.get("name", device_info.get("serial"))
        last_error = None
        timeout_seconds = 300 if args.full else 120
        print(f"Query timeout: {timeout_seconds}s")

        for attempt in range(1, MAX_DEVICE_ATTEMPTS + 1):
            print(
                f"\nQuerying {device_name} "
                f"(attempt {attempt}/{MAX_DEVICE_ATTEMPTS})..."
            )

            timeout_seconds = 300 if args.full else 120

            try:
                success, error = await asyncio.wait_for(
                    query_device(device_info, args),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                success = False
                error = f"TimeoutError: Query timed out after {timeout_seconds} seconds"
                print(f"\nFAILED: {error}")

            # Emit a structured event for server.js.
            error_type = (
                error.split(":", 1)[0]
                if error and ":" in error
                else None
            )

            emit_event({
                "event": "device_attempt",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "device": device_name,
                "serial": str(device_info.get("serial")),
                "model": device_info.get("model"),
                "model_id": device_info.get("model_id"),
                "attempt": attempt,
                "max_attempts": MAX_DEVICE_ATTEMPTS,
                "success": success,
                "error_type": error_type,
                "error": error,
            })

            if success:
                successful += 1

                if attempt > 1:
                    print(f"\n{device_name} recovered on attempt {attempt}.")

                break

            last_error = error

            if attempt < MAX_DEVICE_ATTEMPTS:
                print(
                    f"\n{device_name} failed. "
                    f"Retrying in {DEVICE_RETRY_DELAY} seconds..."
                )
                await asyncio.sleep(DEVICE_RETRY_DELAY)

        else:
            failed_devices.append({
                "name": device_name,
                "serial": device_info.get("serial"),
                "error": last_error,
            })

    print(f"\n{'=' * 55}")
    print("QUERY COMPLETE")
    print(f"{'=' * 55}")
    print(f"Devices successful: {successful}")
    print(f"Devices failed:     {len(failed_devices)}")

    if failed_devices:
        print("\nFAILED DEVICES:")

        for device in failed_devices:
            print(f"\n  Device: {device['name']}")
            print(f"  Serial: {device['serial']}")
            print(f"  Error:  {device['error']}")

        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())