"""
Generic Airthings Wave device class.

BLE transport uses Bleak.
Device-specific sensor decoding and history request formats
are implemented by individual model classes.
"""

import asyncio
import math
from datetime import datetime, timezone
from pathlib import Path

from bleak import BleakClient, BleakScanner

from HistoryStore import HistoryStore


class WaveGeneric:

    PROJECT_DIR = Path(__file__).resolve().parent
    HISTORY_DIR = PROJECT_DIR / "history"

    SERIAL_UUID = "00002a25-0000-1000-8000-00805f9b34fb"

    MODEL_CHARACTERISTICS = {
        "b42e3b98-ade7-11e4-89d3-123b93f75cba": {
            "model_id": 2920,
            "model": "Airthings Wave Mini",
        },
        "b42e2a68-ade7-11e4-89d3-123b93f75cba": {
            "model_id": 2930,
            "model": "Airthings Wave+",
        },
    }

    DISCOVERY_TIMEOUT = 3.0
    CONNECTION_TIMEOUT = 20.0

    # Configured by model classes.
    ACP_CHARACTERISTIC_UUID = None
    HISTORY_DATA_CHARACTERISTIC_UUID = None
    PACKET_DURATION_MINUTES = None
    RECORDS_PER_PACKET = None

    ACP_COMMAND = bytes([0x6D])
    ACP_RESPONSE_TIMEOUT = 15

    class Sensors:
        CHARACTERISTIC_UUID = None
        DATA_FORMAT = None

        def __init__(self):
            self.sensor_version = None
            self.characteristic_uuid = self.CHARACTERISTIC_UUID
            self.data_format = self.DATA_FORMAT

        def conv2radon(self, radon_raw):
            if 0 <= radon_raw <= 16383:
                return radon_raw
            return None

        def decode(self, raw_data):
            raise NotImplementedError(
                "Sensor decoding must be implemented by the device class."
            )

    def __init__(self, SerialNumber, MAC=None):
        self.SN = str(SerialNumber).strip()
        self.MacAddr = MAC

        self.sensors = self.Sensors()
        self.actual_serial = None
        self.model_id = None
        self.model_name = None

        self.client = None
        self.periph = None
        self.curr_val_char = None

    @staticmethod
    def timestamp():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _normalize_serial(serial):
        serial = str(serial).strip()

        if serial.isdigit():
            return str(int(serial))

        return serial

    @classmethod
    def _serials_match(cls, first, second):
        return cls._normalize_serial(first) == cls._normalize_serial(second)

    @staticmethod
    def parseSerialNumber(manufacturer_data):
        """Decode an Airthings serial number from manufacturer bytes."""

        if manufacturer_data is None:
            return "Unknown"

        try:
            if isinstance(manufacturer_data, str):
                data = bytes.fromhex(manufacturer_data)
            else:
                data = bytes(manufacturer_data)

            if len(data) >= 6 and data[:2] == b"\x34\x03":
                data = data[2:]

            if len(data) < 4:
                return "Unknown"

            return int.from_bytes(data[:4], "little")

        except (TypeError, ValueError):
            return "Unknown"

    @classmethod
    async def identify_device(cls, device):
        """Connect to a discovered device and identify its model and serial."""

        client = BleakClient(device, timeout=cls.CONNECTION_TIMEOUT)

        try:
            await client.connect()

            if not client.is_connected:
                raise RuntimeError("Connection failed")

            serial_char = client.services.get_characteristic(cls.SERIAL_UUID)

            if serial_char is None:
                raise RuntimeError(
                    "Device has no serial-number characteristic"
                )

            raw_serial = await client.read_gatt_char(serial_char)
            actual_serial = raw_serial.decode("ascii").strip("\x00").strip()

            if not actual_serial:
                raise RuntimeError("Device returned an empty serial")

            model_info = next(
                (
                    info
                    for uuid, info in cls.MODEL_CHARACTERISTICS.items()
                    if client.services.get_characteristic(uuid) is not None
                ),
                None,
            )

            if model_info is None:
                raise RuntimeError(
                    "Unrecognized Airthings model characteristics"
                )

            return {
                "address": device.address,
                "serial": actual_serial,
                "model_id": model_info["model_id"],
                "model": model_info["model"],
            }

        finally:
            if client.is_connected:
                await client.disconnect()

    async def discover(self):
        """Find a device by verifying its GATT serial number."""

        print(f"Scanning for device {self.SN}...")

        discovered = await BleakScanner.discover(
            timeout=self.DISCOVERY_TIMEOUT,
            return_adv=True,
        )

        for address, (device, advertisement) in discovered.items():
            if 0x0334 not in advertisement.manufacturer_data:
                continue

            try:
                identity = await self.identify_device(device)
            except Exception as exc:
                print(f"Could not identify device at {address}: {exc}")
                continue

            print(
                f"Found candidate: {identity['model']} "
                f"serial {identity['serial']}"
            )

            if self._serials_match(identity["serial"], self.SN):
                self.MacAddr = address
                self.actual_serial = identity["serial"]
                self.model_id = identity["model_id"]
                self.model_name = identity["model"]

                print(
                    f"Found {self.model_name} "
                    f"serial {self.actual_serial} at {address}"
                )

                return address

        raise RuntimeError(
            f"Could not find Airthings device with serial {self.SN}"
        )

    async def connect(self):
        if self.client is not None and self.client.is_connected:
            return

        if self.MacAddr is None:
            await self.discover()

        client = BleakClient(
            self.MacAddr,
            timeout=self.CONNECTION_TIMEOUT,
        )

        try:
            await client.connect()

            if not client.is_connected:
                raise RuntimeError(f"Could not connect to {self.MacAddr}")

            serial_char = client.services.get_characteristic(self.SERIAL_UUID)

            if serial_char is None:
                raise RuntimeError(
                    "Device has no serial-number characteristic"
                )

            actual_serial = (
                await client.read_gatt_char(serial_char)
            ).decode("ascii").strip("\x00").strip()

            if not actual_serial:
                raise RuntimeError("Device returned an empty serial")

            if not self._serials_match(actual_serial, self.SN):
                raise RuntimeError(
                    f"Serial mismatch: expected {self.SN}, "
                    f"device reports {actual_serial}"
                )

            self.actual_serial = actual_serial

            model_info = next(
                (
                    info
                    for uuid, info in self.MODEL_CHARACTERISTICS.items()
                    if client.services.get_characteristic(uuid) is not None
                ),
                None,
            )

            if model_info is None:
                raise RuntimeError("Unrecognized Airthings model")

            self.model_id = model_info["model_id"]
            self.model_name = model_info["model"]

            sensor_char = client.services.get_characteristic(
                self.sensors.characteristic_uuid
            )

            if sensor_char is None:
                raise RuntimeError(
                    f"Sensor characteristic "
                    f"{self.sensors.characteristic_uuid} not found"
                )

            self.client = client
            self.periph = client
            self.curr_val_char = sensor_char

            print(f"Connected to Airthings device {self.SN}")

        except Exception:
            if client.is_connected:
                await client.disconnect()
            raise

    async def read(self):
        if self.client is None or not self.client.is_connected:
            raise RuntimeError("Device is not connected.")

        if self.curr_val_char is None:
            raise RuntimeError("Sensor characteristic is unavailable.")

        raw_data = await self.client.read_gatt_char(self.curr_val_char)
        return self.sensors.decode(raw_data)

    async def get_readings(self):
        readings = await self.read()
        responses = await self.collect_acp()

        if responses:
            decoded = responses[-1].get("decoded", {})

            if decoded.get("valid"):
                readings.update({
                    key: value
                    for key, value in decoded.items()
                    if key != "valid"
                })

        return readings

    async def disconnect(self):
        if self.client is not None and self.client.is_connected:
            await self.client.disconnect()

        self.client = None
        self.periph = None
        self.curr_val_char = None

    async def _write_config_and_verify(
        self,
        config,
        encode_config_write,
        decode_config,
        print_config,
        device_name,
        response_timeout=None,
    ):
        """Read, write, and verify device configuration over ACP."""

        if response_timeout is None:
            response_timeout = self.CONFIG_RESPONSE_TIMEOUT

        connected_here = (
            self.client is None or not self.client.is_connected
        )

        if connected_here:
            await self.connect()

        client = self.client
        notify_started = False

        responses = []
        response_event = asyncio.Event()

        def notification_handler(sender, data):
            raw = bytes(data)

            print(
                "RAW ACP NOTIFICATION:",
                raw.hex(" ").upper(),
                flush=True,
            )

            if raw.startswith(self.CONFIG_READ_COMMAND):
                responses.append(raw)
                response_event.set()
            else:
                print("Ignoring unrelated ACP response.")

        try:
            characteristic = client.services.get_characteristic(
                self.ACP_CHARACTERISTIC_UUID
            )

            if characteristic is None:
                raise RuntimeError("ACP characteristic not found")

            await client.start_notify(
                self.ACP_CHARACTERISTIC_UUID,
                notification_handler,
            )
            notify_started = True

            await asyncio.sleep(0.5)

            print(f"Reading current {device_name} configuration...")

            await client.write_gatt_char(
                self.ACP_CHARACTERISTIC_UUID,
                self.CONFIG_READ_COMMAND,
                response=False,
            )

            await asyncio.wait_for(
                response_event.wait(),
                timeout=response_timeout,
            )

            initial_config = decode_config(responses[-1])

            print("\nCurrent configuration:")
            print_config(initial_config)

            command = encode_config_write(config)

            response_event.clear()
            responses.clear()

            print(
                f"\nWriting {device_name} configuration:",
                command.hex(" ").upper(),
                flush=True,
            )

            await client.write_gatt_char(
                self.ACP_CHARACTERISTIC_UUID,
                command,
                response=False,
            )

            print("Write command sent. Waiting for device response...")

            try:
                await asyncio.wait_for(
                    response_event.wait(),
                    timeout=response_timeout,
                )

                post_write = decode_config(responses[-1])

                print("\nPost-write configuration notification received:")
                print_config(post_write)

            except asyncio.TimeoutError:
                print(
                    "No automatic configuration notification received. "
                    "Continuing to explicit readback."
                )

            response_event.clear()
            responses.clear()

            await asyncio.sleep(0.5)

            print(f"\nRequesting explicit {device_name} readback...")

            await client.write_gatt_char(
                self.ACP_CHARACTERISTIC_UUID,
                self.CONFIG_READ_COMMAND,
                response=False,
            )

            await asyncio.wait_for(
                response_event.wait(),
                timeout=response_timeout,
            )

            verified = decode_config(responses[-1])

            print(
                f"\n========== VERIFIED "
                f"{device_name.upper()} CONFIGURATION =========="
            )
            print_config(verified)

            print("\nConfiguration readback successful.")

            return verified

        finally:
            try:
                if notify_started and client is not None and client.is_connected:
                    await client.stop_notify(self.ACP_CHARACTERISTIC_UUID)
            finally:
                if connected_here:
                    await self.disconnect()

    def save_history(self, new_blocks, retrieval, storage_dir=None):
        if self.model_id is None:
            raise RuntimeError(
                "Device model is unknown. Connect before saving history."
            )

        serial = self.actual_serial or self.SN

        store = HistoryStore(
            model_id=self.model_id,
            serial=serial,
            storage_dir=storage_dir or self.HISTORY_DIR,
        )

        device = {
            "name": self.model_name,
            "model_id": self.model_id,
            "serial": serial,
            "address": self.MacAddr,
        }

        return store.merge_and_save_history(
            new_blocks=new_blocks,
            device=device,
            retrieval=retrieval,
        )

    def calculate_history_packets(self, hours):
        """Convert a requested history duration into packet count."""

        if self.PACKET_DURATION_MINUTES is None:
            raise NotImplementedError(
                "Packet duration is not configured for this device."
            )

        if hours <= 0:
            raise ValueError("hours must be greater than zero")

        packet_duration_hours = self.PACKET_DURATION_MINUTES / 60
        return math.ceil(hours / packet_duration_hours)

    def get_history_packet_identity(self, packet):
        """Return the identity used to deduplicate a history packet."""
        return bytes(packet)

    def is_valid_history_packet(self, packet):
        """Base implementation accepts all history packets."""
        return True

    def build_history_request(self, requested_blocks):
        """Build the model-specific history request payload."""
        raise NotImplementedError(
            "This device does not implement a history request."
        )

    def is_history_complete_response(self, data, requested_blocks):
        """Return whether a command response confirms history completion."""
        return False

    def report_history_packet(self, packet, received, requested):
        print(
            f"Received history block [{received}/{requested}]",
            flush=True,
        )

    async def collect_history(self, requested_blocks, timeout=None):
        """
        Collect raw history packets and command responses.

        Does not decode or save history. Partial results are returned
        if collection times out.
        """

        if not isinstance(requested_blocks, int):
            raise TypeError("requested_blocks must be an integer")

        if not 1 <= requested_blocks <= 65536:
            raise ValueError(
                "requested_blocks must be between 1 and 65536"
            )

        if (
            not self.ACP_CHARACTERISTIC_UUID
            or not self.HISTORY_DATA_CHARACTERISTIC_UUID
        ):
            raise NotImplementedError(
                "History characteristic UUIDs are not configured."
            )

        request = self.build_history_request(requested_blocks)

        if not isinstance(request, bytes):
            raise TypeError("build_history_request() must return bytes")

        connected_here = (
            self.client is None or not self.client.is_connected
        )

        if connected_here:
            await self.connect()

        packets = []
        seen_packets = {}
        command_responses = []

        notification_count = 0
        duplicate_count = 0

        history_complete = asyncio.Event()
        device_confirmed = False
        request_rejected = False
        reported_blocks = None
        timed_out = False

        def command_handler(sender, data):
            nonlocal device_confirmed, request_rejected, reported_blocks

            raw = bytes(data)
            command_responses.append(raw)

            if hasattr(self, "handle_history_command"):
                result = self.handle_history_command(raw)
                print(f"Decoded history response: {result}", flush=True)

                if result.get("status") == "error":
                    request_rejected = True
                    print(
                        "Device rejected history request. "
                        "Stopping collection.",
                        flush=True,
                    )
                    history_complete.set()
                    return

                if result.get("status") == "success":
                    reported_blocks = result.get("reported_packets")

            print(
                f"History command response: {raw.hex(' ')}",
                flush=True,
            )

            if self.is_history_complete_response(raw, requested_blocks):
                device_confirmed = True
                print("Device signalled history completion.", flush=True)
                history_complete.set()

        def history_handler(sender, data):
            nonlocal notification_count, duplicate_count

            raw = bytes(data)

            if not self.is_valid_history_packet(raw):
                print(
                    f"Ignoring invalid history packet ({len(raw)} bytes)",
                    flush=True,
                )
                return

            notification_count += 1
            identity = self.get_history_packet_identity(raw)

            if identity in seen_packets:
                duplicate_count += 1

                original = seen_packets[identity]
                identical = original == raw

                print(
                    f"DUPLICATE: {identity} | "
                    f"identical={identical} | "
                    f"notification #{notification_count}",
                    flush=True,
                )
                return

            seen_packets[identity] = raw
            packets.append(raw)

            self.report_history_packet(
                raw,
                len(packets),
                requested_blocks,
            )

            if notification_count >= requested_blocks:
                history_complete.set()

        command_notify_started = False
        history_notify_started = False

        try:
            client = self.client

            if client.services.get_characteristic(
                self.ACP_CHARACTERISTIC_UUID
            ) is None:
                raise RuntimeError("History command characteristic not found")

            if client.services.get_characteristic(
                self.HISTORY_DATA_CHARACTERISTIC_UUID
            ) is None:
                raise RuntimeError("History data characteristic not found")

            await client.start_notify(
                self.ACP_CHARACTERISTIC_UUID,
                command_handler,
            )
            command_notify_started = True

            await client.start_notify(
                self.HISTORY_DATA_CHARACTERISTIC_UUID,
                history_handler,
            )
            history_notify_started = True

            print(
                f"Requesting {requested_blocks} history blocks...",
                flush=True,
            )

            await client.write_gatt_char(
                self.ACP_CHARACTERISTIC_UUID,
                request,
                response=False,
            )

            if timeout is None:
                timeout = max(60, min(2400, requested_blocks * 0.3))

            try:
                await asyncio.wait_for(
                    history_complete.wait(),
                    timeout=timeout,
                )

            except asyncio.TimeoutError:
                timed_out = True
                print(
                    "History collection timed out. "
                    "Returning blocks received so far.",
                    flush=True,
                )

            await asyncio.sleep(0.5)

        finally:
            try:
                if self.client is not None and self.client.is_connected:
                    if history_notify_started:
                        await self.client.stop_notify(
                            self.HISTORY_DATA_CHARACTERISTIC_UUID
                        )

                    if command_notify_started:
                        await self.client.stop_notify(
                            self.ACP_CHARACTERISTIC_UUID
                        )
            finally:
                if connected_here:
                    await self.disconnect()

        return {
            "requested_blocks": requested_blocks,
            "received_blocks": len(packets),
            "notification_count": notification_count,
            "duplicate_count": duplicate_count,
            "complete": len(packets) >= requested_blocks,
            "notification_complete": (
                notification_count >= requested_blocks
                and not request_rejected
            ),
            "unique_complete": len(packets) >= requested_blocks,
            "device_confirmed": device_confirmed,
            "reported_blocks": reported_blocks,
            "request_rejected": request_rejected,
            "timed_out": timed_out,
            "packets": packets,
            "command_responses": command_responses,
        }

    def decode_acp_response(self, raw):
        """Preserve raw ACP responses unless a model overrides this."""
        return {}


    async def collect_acp(self, output_file=None, response_timeout=None):
        """
        Send the ACP command and save raw notification responses.

        Model-specific response decoding is handled by subclasses.
        """

        if not self.ACP_CHARACTERISTIC_UUID:
            raise NotImplementedError(
                "ACP characteristic is not configured for this device."
            )

        if response_timeout is None:
            response_timeout = self.ACP_RESPONSE_TIMEOUT

        connected_here = (
            self.client is None or not self.client.is_connected
        )

        if connected_here:
            await self.connect()

        responses = []
        response_event = asyncio.Event()
        request_time = self.timestamp()

        def notification_handler(sender, data):
            raw = bytes(data)
            received = self.timestamp()

            record = {
                "request_timestamp": request_time,
                "response_timestamp": received,
                "device": self.MacAddr,
                "serial": self.actual_serial or self.SN,
                "command": self.ACP_COMMAND.hex(" "),
                "length": len(raw),
                "raw_hex": raw.hex(" "),
                "raw_bytes": list(raw),
                "decoded": self.decode_acp_response(raw),
            }

            responses.append(record)
            response_event.set()

            print("\nACP response received:")
            print("Length:", len(raw))
            print("Hex:", raw.hex(" "))

        notify_started = False

        try:
            client = self.client
            characteristic = client.services.get_characteristic(
                self.ACP_CHARACTERISTIC_UUID
            )

            if characteristic is None:
                raise RuntimeError("ACP characteristic not found")

            await client.start_notify(
                self.ACP_CHARACTERISTIC_UUID,
                notification_handler,
            )
            notify_started = True

            await asyncio.sleep(1)

            print("Sending ACP command:", self.ACP_COMMAND.hex(" "))

            await client.write_gatt_char(
                self.ACP_CHARACTERISTIC_UUID,
                self.ACP_COMMAND,
                response=True,
            )

            try:
                await asyncio.wait_for(
                    response_event.wait(),
                    timeout=response_timeout,
                )

                await asyncio.sleep(1)

            except asyncio.TimeoutError:
                print("WARNING: No ACP response received.")

        finally:
            try:
                if (
                    notify_started
                    and self.client is not None
                    and self.client.is_connected
                ):
                    await self.client.stop_notify(
                        self.ACP_CHARACTERISTIC_UUID
                    )
            finally:
                if connected_here:
                    await self.disconnect()

        if not responses:
            print("No ACP responses to save.")
            return []

        if self.model_id is None:
            raise RuntimeError("Device model ID is not available.")

        store = HistoryStore(
            model_id=self.model_id,
            serial=self.actual_serial or self.SN,
            storage_dir=self.HISTORY_DIR,
        )

        saved_path = store.append_acp_responses(
            responses,
            output_file=output_file,
        )

        print(f"Saved to: {saved_path}")

        return responses
