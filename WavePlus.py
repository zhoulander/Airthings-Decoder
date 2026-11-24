
#!/usr/bin/env python3
"""Airthings Wave Plus device implementation."""

import asyncio
import struct
from datetime import datetime, timezone

from WaveGeneric import WaveGeneric


class WavePlus(WaveGeneric):

    # Device characteristics
    MODEL_NAME = "Wave Plus"
    MODEL_ID = 2930

    SERVICE_UUID = "b42e1c08-ade7-11e4-89d3-123b93f75cba"
    ACP_CHARACTERISTIC_UUID = "b42e2d06-ade7-11e4-89d3-123b93f75cba"
    HISTORY_DATA_CHARACTERISTIC_UUID = "b42e2fc2-ade7-11e4-89d3-123b93f75cba"

    # History protocol
    MODE = 2
    DEFAULT_HOURS = 3

    HISTORY_PACKET_LENGTH = 230
    RECORDS_PER_PACKET = 12
    PACKET_DURATION_MINUTES = 60
    SAMPLE_INTERVAL_SECONDS = 300

    METADATA_TIMEOUT = 60
    METADATA_RETRIES = 1
    METADATA_RETRY_DELAY = 2

    # Configuration commands
    CONFIG_READ_COMMAND = bytes.fromhex("66 00")
    CONFIG_RESPONSE_TIMEOUT = 5

    class Sensors(WaveGeneric.Sensors):
        CHARACTERISTIC_UUID = "b42e2a68-ade7-11e4-89d3-123b93f75cba"
        DATA_FORMAT = "<BBBBHHHHHHHH"

        def decode(self, raw_data):
            (
                version,
                humidity,
                ambient_light,
                waves,
                radon,
                radon_lt,
                temperature,
                pressure,
                co2,
                voc,
                mode,
                x3,
            ) = struct.unpack_from(self.DATA_FORMAT, raw_data)

            if version != 1:
                raise ValueError(
                    f"Unsupported WavePlus sensor version: {version}"
                )

            return {
                "humidity_pct": humidity / 2.0,
                "illuminance_raw": ambient_light,
                "waves": waves,
                "radon_st": self.conv2radon(radon),
                "radon_lt": self.conv2radon(radon_lt),
                "temperature_c": round(temperature / 100.0, 2),
                "pressure_hpa": pressure / 50.0,
                "co2_ppm": co2,
                "voc_ppb": voc,
                "mode": mode,
                "x3": round(x3 / 256.0, 4),
            }

    @staticmethod
    def decode_msp_version(device_type, raw):
        """Decode the Wave Plus MSP firmware version."""

        if raw == 0xFFFF:
            return None

        date_coded_versions = (0x0798, 0x1E98, 0x03C8, 0x04C8)

        if device_type == 2 and raw in date_coded_versions:
            return (
                f"{2010 + (raw & 0x0F)}-"
                f"{(raw >> 4) & 0x0F:02d}-"
                f"{raw >> 8:02d}"
            )

        major = raw >> 14
        minor = (raw >> 8) & 0x3F
        patch = (raw >> 6) & 0x03

        if major == minor == patch == 0:
            return None

        return f"{major}.{minor}.{patch}"

    # ACP decoder
    def decode_acp_response(self, raw):
        """Decode the Wave Plus 0x6D ACP response."""

        raw = bytes(raw)

        if len(raw) != 30:
            return {
                "valid": False,
                "error": f"Unexpected ACP response length: {len(raw)}",
                "raw_hex": raw.hex(" "),
            }

        if raw[:2] != bytes([0x6D, 0x00]):
            return {
                "valid": False,
                "error": "Unexpected WavePlus ACP response header",
                "raw_hex": raw.hex(" "),
            }

        values = struct.unpack("<L2BH2B9H", raw[2:])

        received_time = datetime.now(timezone.utc).timestamp()
        elapsed = values[0]
        cycle_start = received_time - elapsed

        device_type = values[1]
        msp_raw = values[3]
        battery_mv = values[13]

        return {
            "valid": True,
            "time": received_time,
            "time_utc": datetime.fromtimestamp(
                received_time, timezone.utc
            ).isoformat(),
            "time_elapsed": elapsed,
            "cycle_start": cycle_start,
            "cycle_start_utc": datetime.fromtimestamp(
                cycle_start, timezone.utc
            ).isoformat(),
            "illuminance_raw": values[2],
            "airthingschip": {
                "msp": self.decode_msp_version(device_type, msp_raw),
            },
            "msp_firmware_raw": msp_raw,
            "battery_mv": battery_mv,
            "battery_voltage_v": battery_mv / 1000.0,
            "device_type": device_type,
            "unclassified_fields": list(values[4:13]) + [values[14]],
            "raw_hex": raw.hex(" "),
        }

    # Device commands
    async def _execute_acp_command(self, command, response_prefix, timeout=None):
        """
        Send an ACP command and wait for its matching response.

        Returns the complete raw notification, including
        the command and status bytes.
        """

        connected_here = (
            self.client is None or not self.client.is_connected
        )

        if connected_here:
            await self.connect()

        loop = asyncio.get_running_loop()
        response_future = loop.create_future()

        if timeout is None:
            timeout = self.ACP_RESPONSE_TIMEOUT

        command = bytes(command)
        response_prefix = bytes(response_prefix)

        def command_handler(sender, data):
            raw = bytes(data)

            if response_future.done():
                return

            if raw.startswith(response_prefix):
                response_future.set_result(raw)
                return

            if len(raw) >= 2 and raw[0] == command[0] and raw[1] != 0:
                response_future.set_exception(
                    RuntimeError(f"ACP command failed: {raw.hex(' ')}")
                )

        notify_started = False

        try:
            client = self.client

            if client.services.get_characteristic(
                self.ACP_CHARACTERISTIC_UUID
            ) is None:
                raise RuntimeError("ACP characteristic not found")

            await client.start_notify(
                self.ACP_CHARACTERISTIC_UUID,
                command_handler,
            )
            notify_started = True

            await client.write_gatt_char(
                self.ACP_CHARACTERISTIC_UUID,
                command,
                response=True,
            )

            return await asyncio.wait_for(
                response_future,
                timeout=timeout,
            )

        finally:
            if (
                notify_started
                and self.client is not None
                and self.client.is_connected
            ):
                await self.client.stop_notify(
                    self.ACP_CHARACTERISTIC_UUID
                )

            if connected_here:
                await self.disconnect()

    async def flash_light(self):
        """Pulse the Wave Plus light ring."""

        await self._execute_acp_command(
            command=bytes([0x67, 0x08]),
            response_prefix=bytes([0x67, 0x00]),
        )

    async def query1(self):
        """Retrieve the Wave Plus Query 1 response."""

        raw = await self._execute_acp_command(
            command=bytes([0x66, 0x00]),
            response_prefix=bytes([0x66, 0x00]),
        )

        payload = raw[2:]

        if len(payload) != 21:
            raise ValueError(
                f"Unexpected Query 1 response length: {len(payload)}"
            )

        values = struct.unpack("<bBB9H", payload)

        return {
            "values": list(values),
            "raw_hex": raw.hex(" "),
        }

    async def query2(self):
        """Retrieve Wave Plus sampling cycle information."""

        raw = await self._execute_acp_command(
            command=bytes([0x6D]),
            response_prefix=bytes([0x6D, 0x00]),
        )

        payload = raw[2:]

        if len(payload) != 28:
            raise ValueError(
                f"Unexpected Query 2 response length: {len(payload)}"
            )

        values = struct.unpack("<L24B", payload)

        received_time = datetime.now(timezone.utc).timestamp()
        time_elapsed = values[0]
        cycle_start = received_time - time_elapsed

        return {
            "time": received_time,
            "time_utc": datetime.fromtimestamp(
                received_time, timezone.utc
            ).isoformat(),
            "time_elapsed": time_elapsed,
            "cycle_start": cycle_start,
            "cycle_start_utc": datetime.fromtimestamp(
                cycle_start, timezone.utc
            ).isoformat(),
            "illuminance_raw": values[2],
            "raw_hex": raw.hex(" "),
        }

    # Configuration
    async def collect_config(self, response_timeout=None):
        """
        Read and decode the Wave Plus configuration.

        Sends 66 00 through the ACP characteristic and receives
        the configuration response.
        """

        from WavePlusConfig import decode_config, print_config

        if response_timeout is None:
            response_timeout = self.CONFIG_RESPONSE_TIMEOUT

        connected_here = (
            self.client is None or not self.client.is_connected
        )

        if connected_here:
            await self.connect()

        responses = []
        response_event = asyncio.Event()

        def notification_handler(sender, data):
            raw = bytes(data)

            if not raw.startswith(self.CONFIG_READ_COMMAND):
                print("Ignoring unrelated ACP response.")
                return

            print(
                "Configuration response received:",
                raw.hex(" ").upper(),
                flush=True,
            )

            responses.append(raw)
            response_event.set()

        notify_started = False

        try:
            client = self.client

            if client.services.get_characteristic(
                self.ACP_CHARACTERISTIC_UUID
            ) is None:
                raise RuntimeError("ACP characteristic not found")

            await client.start_notify(
                self.ACP_CHARACTERISTIC_UUID,
                notification_handler,
            )
            notify_started = True

            await asyncio.sleep(0.5)

            print(
                "Requesting Wave Plus configuration:",
                self.CONFIG_READ_COMMAND.hex(" "),
                flush=True,
            )

            await client.write_gatt_char(
                self.ACP_CHARACTERISTIC_UUID,
                self.CONFIG_READ_COMMAND,
                response=False,
            )

            await asyncio.wait_for(
                response_event.wait(),
                timeout=response_timeout,
            )

        except asyncio.TimeoutError:
            raise TimeoutError(
                "Wave Plus did not return a configuration response."
            )

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

        config = decode_config(responses[-1])

        print("\n========== WAVE PLUS CONFIGURATION ==========")
        print_config(config)
        print("\nConfiguration read successful.")

        return config

    async def write_config_and_verify(self, config, response_timeout=None):
        from WavePlusConfig import (
            encode_config_write,
            decode_config,
            print_config,
        )

        return await self._write_config_and_verify(
            config,
            encode_config_write,
            decode_config,
            print_config,
            "Wave Plus",
            response_timeout,
        )

    async def send_time(self):
        """Send the current Unix timestamp to the Wave Plus."""

        now = int(datetime.now(timezone.utc).timestamp())

        command = struct.pack("<BBLL", 0x71, 0x52, 1, now)

        raw = await self._execute_acp_command(
            command=command,
            response_prefix=bytes([0x71, 0x00, 0x52]),
        )

        payload = raw[2:]

        if len(payload) != 9:
            raise ValueError(
                f"Unexpected Set Time response length: {len(payload)}"
            )

        response_type, confirmation, device_time = struct.unpack(
            "<BLL", payload
        )

        return {
            "sent_timestamp": now,
            "sent_time_utc": datetime.fromtimestamp(
                now, timezone.utc
            ).isoformat(),
            "confirmation": confirmation,
            "device_timestamp": device_time,
            "device_time_utc": datetime.fromtimestamp(
                device_time, timezone.utc
            ).isoformat(),
            "raw_hex": raw.hex(" "),
        }

    # History metadata
    def decode_history_metadata(self, raw):
        """Decode the Wave Plus history metadata response."""

        raw = bytes(raw)

        if len(raw) != 15:
            raise ValueError(
                f"Unexpected metadata response length: {len(raw)}"
            )

        if raw[:2] != bytes([0x71, 0x00]):
            raise ValueError("Unexpected WavePlus metadata response")

        (
            metadata_type,
            series_start,
            unknown1,
            unknown2,
            num_records,
            unknown3,
        ) = struct.unpack("<BL4H", raw[2:])

        return {
            "type": metadata_type,
            "series_start": series_start,
            "series_start_utc": datetime.fromtimestamp(
                series_start, timezone.utc
            ).isoformat(),
            "num_records": num_records,
            "unknown": [unknown1, unknown2, unknown3],
            "raw_hex": raw.hex(" "),
        }

    async def get_history_metadata(self):
        """Request and retrieve Wave Plus history metadata."""

        connected_here = (
            self.client is None or not self.client.is_connected
        )

        if connected_here:
            await self.connect()

        metadata_future = asyncio.get_running_loop().create_future()
        notify_started = False

        def command_handler(sender, data):
            raw = bytes(data)

            if (
                len(raw) == 15
                and raw[:2] == bytes([0x71, 0x00])
                and not metadata_future.done()
            ):
                metadata_future.set_result(raw)

        try:
            client = self.client

            if client.services.get_characteristic(
                self.ACP_CHARACTERISTIC_UUID
            ) is None:
                raise RuntimeError(
                    "Wave Plus command characteristic not found"
                )

            await client.start_notify(
                self.ACP_CHARACTERISTIC_UUID,
                command_handler,
            )
            notify_started = True

            await client.write_gatt_char(
                self.ACP_CHARACTERISTIC_UUID,
                bytes([0x71, 0x54, 0x00]),
                response=True,
            )

            raw = await asyncio.wait_for(
                metadata_future,
                timeout=self.METADATA_TIMEOUT,
            )

            return self.decode_history_metadata(raw)

        finally:
            if (
                self.client is not None
                and self.client.is_connected
                and notify_started
            ):
                await self.client.stop_notify(
                    self.ACP_CHARACTERISTIC_UUID
                )

            if connected_here:
                await self.disconnect()

    # History request and response
    def build_history_request(self, requested_blocks):
        if not hasattr(self, "_history_request_hours"):
            raise RuntimeError(
                "History request hours have not been configured."
            )

        return struct.pack(
            "<BHHHH",
            0x01,
            self.MODE,
            0,
            self._history_request_hours,
            0,
        )

    def handle_history_command(self, data):
        """Process Wave Plus history command responses."""

        data = bytes(data)

        if len(data) != 6:
            return {
                "status": "unknown",
                "raw": data.hex(" "),
            }

        command = data[0]
        status = data[1]
        value = struct.unpack("<I", data[2:6])[0]

        if command == 0x01 and status == 0x00:
            self.reported_packets = value
            return {
                "status": "success",
                "reported_packets": value,
                "raw": data.hex(" "),
            }

        return {
            "status": "error",
            "command": command,
            "status_code": status,
            "value": value,
            "raw": data.hex(" "),
        }

    def is_history_complete_response(self, data, requested_blocks):
        """Wave Plus acknowledgement is not a transfer-completion signal."""

        return False

    # History packet validation
    def get_history_packet_identity(self, packet):
        """Identify a Wave Plus history block by series and record number."""

        packet = bytes(packet)

        if len(packet) != self.HISTORY_PACKET_LENGTH:
            return packet

        series_start = struct.unpack_from("<I", packet, 218)[0]
        record_number = struct.unpack_from("<H", packet, 228)[0]

        return series_start, record_number

    # History decoder
    @classmethod
    def decode_history_block(cls, data):
        """Decode one 230-byte Wave Plus history packet."""

        data = bytes(data)

        if len(data) != cls.HISTORY_PACKET_LENGTH:
            raise ValueError(f"Unexpected packet length: {len(data)}")

        parts = struct.unpack("<8H HH 12H 12B 12H 12H", data[:104])

        radon_st = parts[8]
        radon_lt = parts[9]

        temperatures = parts[10:22]
        humidities = parts[22:34]
        pressures = parts[34:46]
        co2_values = parts[46:58]

        sample_extras = []

        for index in range(cls.RECORDS_PER_PACKET):
            pos = 104 + index * 8
            x4, voc, x3 = struct.unpack_from("<2HL", data, pos)

            sample_extras.append({
                "x4": x4,
                "voc_ppb": voc,
                "x3": x3,
            })

        tail = struct.unpack("<12B 6B L 4H", data[200:230])

        ambient_lights = tail[:12]
        series_start = tail[18]
        record_number = tail[22]

        hour_start = series_start + record_number * 3600

        block_time = datetime.fromtimestamp(
            hour_start, timezone.utc
        ).isoformat()

        series_start_time = datetime.fromtimestamp(
            series_start, timezone.utc
        ).isoformat()

        records = []

        for index in range(cls.RECORDS_PER_PACKET):
            timestamp = hour_start + index * cls.SAMPLE_INTERVAL_SECONDS

            sample_time = datetime.fromtimestamp(
                timestamp, timezone.utc
            ).isoformat()

            extras = sample_extras[index]

            records.append({
                "id": f"{series_start}:{record_number}:{index}",
                "series_start": series_start,
                "record_number": record_number,
                "block_timestamp": hour_start,
                "block_time_utc": block_time,
                "timestamp": timestamp,
                "timestamp_utc": sample_time,
                "index": index,
                "sample": index + 1,
                "temperature_c": round(
                    (temperatures[index] - 27315) / 100, 2
                ),
                "humidity_pct": round(humidities[index] / 2, 2),
                "pressure_hpa": round(pressures[index] / 50, 2),
                "co2_ppm": co2_values[index],
                "voc_ppb": extras["voc_ppb"],
                "illuminance_raw": ambient_lights[index],
                "radon_st": radon_st,
                "radon_lt": radon_lt,
                "x3": round(extras["x3"] / 256, 4),
                "x4": extras["x4"],
            })

        return {
            "block_id": f"{series_start}:{record_number}",
            "series_start": series_start,
            "series_start_utc": series_start_time,
            "record_number": record_number,
            "block_timestamp": hour_start,
            "block_time_utc": block_time,
            "record_count": len(records),
            "radon_st": radon_st,
            "radon_lt": radon_lt,
            "raw_hex": data.hex(" "),
            "records": records,
        }


    async def _get_history_sync_state(self):
        """Return the current Wave Plus history position."""

        metadata = await self.get_history_metadata()

        available_blocks = metadata["num_records"]

        if available_blocks <= 0:
            raise RuntimeError(
                "Wave Plus reported no available history."
            )

        return {
            "series_id": metadata["series_start"],
            "latest_index": available_blocks - 1,
            "available_blocks": available_blocks,
        }

    def _parse_history_checkpoint(self, block_id):
        """Parse a Wave Plus block ID: series_start:record_number."""

        try:
            series_id, record_number = map(int, block_id.split(":"))
        except (AttributeError, TypeError, ValueError):
            raise ValueError(
                "Wave Plus block ID must be "
                "'series_start:record_number'"
            )

        if series_id <= 0 or record_number < 0:
            raise ValueError("Invalid Wave Plus block ID")

        return series_id, record_number

    async def _collect_history_blocks(
        self,
        requested_blocks,
        timeout=None,
    ):
        """
        Convert a block count into the Wave Plus hours-based request.
        """

        requested_hours = max(1, requested_blocks - 1)

        return await self.collect_history(
            hours=requested_hours,
            timeout=timeout,
        )

    def format_history_checkpoint(self, block):
        """Return the stored Plus checkpoint."""

        if block is None:
            return None

        return block["block_id"]

    # History collection
    async def collect_history(
        self,
        hours=DEFAULT_HOURS,
        full=False,
        timeout=None,
    ):
        """
        Collect and store Wave Plus history.

        Incremental mode retrieves the requested number of hours.
        Full mode retrieves all history reported by the device.
        """

        if not full:
            if not isinstance(hours, int):
                raise TypeError("hours must be an integer")
            if hours <= 0:
                raise ValueError("hours must be greater than zero")

        metadata = None

        for attempt in range(self.METADATA_RETRIES + 1):
            try:
                metadata = await self.get_history_metadata()
                break
            except asyncio.TimeoutError:
                if attempt >= self.METADATA_RETRIES:
                    raise

                print(
                    "History metadata request timed out. "
                    f"Retrying in {self.METADATA_RETRY_DELAY} seconds..."
                )
                await asyncio.sleep(self.METADATA_RETRY_DELAY)

        available_blocks = metadata["num_records"]

        if available_blocks <= 0:
            raise RuntimeError("Wave Plus reported no available history.")

        if full:
            requested_blocks = available_blocks
        else:
            requested_blocks = min(available_blocks, hours + 1)

        requested_hours = requested_blocks - 1
        self._history_request_hours = requested_hours

        print("========== WAVE+ HISTORY REQUEST ==========")
        print(f"Metadata: {available_blocks}")
        print(f"Requested hours: {requested_hours}")
        print(f"Expected blocks: {requested_blocks}")

        transfer = await super().collect_history(
            requested_blocks=requested_blocks,
            timeout=timeout,
        )

        reported_packets = next(
            (
                struct.unpack("<I", response[2:6])[0]
                for response in transfer["command_responses"]
                if len(response) == 6 and response[:2] == b"\x01\x00"
            ),
            None,
        )

        valid_packets = [
            packet for packet in transfer["packets"]
            if self.get_history_packet_identity(packet) != (0, 0)
        ]

        blocks = [
            self.decode_history_block(packet)
            for packet in valid_packets
        ]

        blocks.sort(
            key=lambda block: (
                block["series_start"],
                block["record_number"],
            )
        )

        command_responses = [
            response.hex(" ")
            for response in transfer["command_responses"]
        ]

        retrieval = {
            "mode": self.MODE,
            "full": full,
            "requested_hours": requested_hours,
            "requested_blocks": requested_blocks,
            "available_blocks": available_blocks,
            "last_poll_received_blocks": len(blocks),
            "last_poll_sentinel_packets": (
                len(transfer["packets"]) - len(valid_packets)
            ),
            "metadata": metadata,
            "command_responses": command_responses,
            "reported_packets": reported_packets,
            "device_confirmed": transfer["device_confirmed"],
            "timed_out": transfer["timed_out"],
        }

        result = self.save_history(
            new_blocks=blocks,
            retrieval=retrieval,
            storage_dir=self.HISTORY_DIR,
        )

        print("========== WAVE+ HISTORY SUMMARY ==========")
        print(f"Metadata record count: {available_blocks}")
        print(f"Requested blocks: {requested_blocks}")

        print("\n--- BLE Transfer ---")
        print(
            f"Notifications received: "
            f"{transfer['notification_count']}/{requested_blocks}"
        )
        print(f"Unique raw packets received: {transfer['received_blocks']}")
        print(f"Duplicate notifications: {transfer['duplicate_count']}")
        print(f"Device reported packets: {transfer['reported_blocks']}")
        print(f"Notification complete: {transfer['notification_complete']}")
        print(f"Unique packet complete: {transfer['unique_complete']}")
        print(f"Request rejected: {transfer['request_rejected']}")
        print(f"Timed out: {transfer['timed_out']}")

        print("\n--- Decoded History ---")
        print(f"Valid history blocks: {len(blocks)}")
        print(
            f"Empty sentinel packets: "
            f"{len(transfer['packets']) - len(valid_packets)}"
        )
        print(
            f"Valid readings decoded: "
            f"{sum(block['record_count'] for block in blocks)}"
        )

        print("\n--- HistoryStore ---")
        print(
            f"Total unique blocks stored: "
            f"{result['retrieval']['total_blocks']}"
        )
        print(
            f"Total unique readings stored: "
            f"{result['retrieval']['total_records']}"
        )
        print(
            f"Saved: "
            f"{self.HISTORY_DIR / f'{self.model_id}_{self.actual_serial or self.SN}.json'}"
        )

        return result
