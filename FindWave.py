
import asyncio
import json
from pathlib import Path

from bleak import BleakScanner, BleakClient

from WaveMini import WaveMini
from WavePlus import WavePlus


PROJECT_DIR = Path(__file__).resolve().parent
DEVICES_FILE = PROJECT_DIR / "devices.json"

AIRTHINGS_COMPANY_ID = 0x0334
SCAN_TIMEOUT = 60
CONNECT_TIMEOUT = 15
VERIFY_CONNECTION = False

MODEL_CLASSES = (WaveMini, WavePlus)


def load_registry():
    if not DEVICES_FILE.exists():
        return {"devices": []}

    with DEVICES_FILE.open("r") as file:
        return json.load(file)


def save_device(device_info):
    registry = load_registry()
    devices = registry.setdefault("devices", [])

    existing = next(
        (
            device for device in devices
            if str(device.get("serial")) == device_info["serial"]
        ),
        None,
    )

    if existing:
        existing.update({
            "model": device_info["model"],
            "model_id": device_info["model_id"],
            "mac": device_info["mac"],
        })

        if not existing.get("name"):
            existing["name"] = device_info["name"]

        print(f"Updated existing device: {device_info['serial']}")
    else:
        devices.append(device_info)
        print(f"Added new device: {device_info['serial']}")

    with DEVICES_FILE.open("w") as file:
        json.dump(registry, file, indent=4)
        file.write("\n")

    print(f"Registry saved: {DEVICES_FILE}")


def get_serial(advertisement):
    data = advertisement.manufacturer_data.get(AIRTHINGS_COMPANY_ID)

    if data is None or len(data) < 4:
        return None

    combined_id = int.from_bytes(data[:4], byteorder="little")
    return f"{combined_id % 1_000_000:06d}"


def identify_model_from_name(device):
    name = (device.name or "").lower()

    if "wave mini" in name:
        return WaveMini
    if "wave+" in name:
        return WavePlus

    return None


async def identify_model(client):
    available_uuids = {
        characteristic.uuid.lower()
        for service in client.services
        for characteristic in service.characteristics
    }

    for model_class in MODEL_CLASSES:
        if model_class.Sensors.CHARACTERISTIC_UUID.lower() in available_uuids:
            return model_class

    return None

async def identify_device(device, advertisement):
    serial = get_serial(advertisement)
    if serial is None:
        return

    print(f"\n{'=' * 50}")
    print("AIRTHINGS DEVICE DETECTED")
    print(f"{'=' * 50}")
    print(f"Serial:  {serial}")
    print(f"Address: {device.address}")
    print(f"Name:    {device.name}")
    print(f"RSSI:    {advertisement.rssi} dBm")

    model_class = identify_model_from_name(device)

    # Connect when the advertisement doesn't identify the model,
    # or when connection verification is enabled.
    if model_class is None or VERIFY_CONNECTION:
        try:
            async with BleakClient(device, timeout=CONNECT_TIMEOUT) as client:
                print("Connected. Identifying/verifying model...")
                verified_model = await identify_model(client)

                if verified_model is None:
                    print("Could not identify model from GATT characteristics.")
                    return

                if model_class is None:
                    model_class = verified_model
                    print("Model identified from GATT characteristics.")

                elif verified_model != model_class:
                    print("Model verification failed.")
                    return

                print("Model verified.")

        except Exception as error:
            print(f"Connection/identification failed: {type(error).__name__}: {error}")
            return

    print(f"Model:   {model_class.MODEL_NAME}")
    print(f"Model ID: {model_class.MODEL_ID}")

    save_device({
        "serial": serial,
        "model": model_class.__name__,
        "model_id": model_class.MODEL_ID,
        "mac": device.address,
        "name": model_class.MODEL_NAME,
    })



async def main():
    print("Scanning for Airthings devices...")
    print(f"Scan duration: {SCAN_TIMEOUT} seconds")

    discovered = await BleakScanner.discover(
        timeout=SCAN_TIMEOUT,
        return_adv=True,
    )

    processed = set()

    for device, advertisement in discovered.values():
        if AIRTHINGS_COMPANY_ID not in advertisement.manufacturer_data:
            continue

        serial = get_serial(advertisement)
        if serial is None or serial in processed:
            continue

        processed.add(serial)
        await identify_device(device, advertisement)

    if not processed:
        print("No Airthings devices found.")

    print("\nDiscovery complete.")


if __name__ == "__main__":
    asyncio.run(main())
