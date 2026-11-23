
#!/usr/bin/env python3
"""Airthings Wave Mini device implementation."""

import asyncio
import struct
from datetime import datetime, timezone

from WaveGeneric import WaveGeneric


class WaveMini(WaveGeneric):

    # Device characteristics
    MODEL_NAME = "Wave Mini"
    MODEL_ID = 2920

    SERVICE_UUID = "b42e3882-ade7-11e4-89d3-123b93f75cba"
    ACP_CHARACTERISTIC_UUID = "b42e3ef4-ade7-11e4-89d3-123b93f75cba"
    HISTORY_DATA_CHARACTERISTIC_UUID = "b42e41c4-ade7-11e4-89d3-123b93f75cba"

    # History protocol
    MODE = 2
    HOURS = 168  # Protocol field; purpose not fully understood for Mini.

    ROUTINE_PACKETS = 3
    FULL_PACKETS = 5000  # Up to ~208 days; excess packets return empty notifications.

    HISTORY_PACKET_LENGTH = 205
    MAX_HISTORY_RECORDS = 12
    RECORDS_PER_PACKET = 12
    PACKET_DURATION_MINUTES = 60
    SAMPLE_INTERVAL_SECONDS = 300
    RECORD_OFFSET = 25
    RECORD_SIZE = 15

    # Configuration commands
    CONFIG_READ_COMMAND = bytes.fromhex("66 00")
    CONFIG_WRITE_COMMAND = bytes.fromhex("66 01")
    CONFIG_RESPONSE_TIMEOUT = 5

    class Sensors(WaveGeneric.Sensors):
        CHARACTERISTIC_UUID = "b42e3b98-ade7-11e4-89d3-123b93f75cba"
        DATA_FORMAT = "<HHHHHHLL"

        def decode(self, raw_data):
            (
                unused01,
                temperature,
                pressure,
                humidity,
                voc,
                unused02,
                unused03,
                unused04,
            ) = struct.unpack(self.DATA_FORMAT, raw_data)

            return {
                "temperature_c": round(temperature / 100 - 273.15, 2),
                "pressure_hpa": pressure / 50.0,
                "humidity_pct": round(humidity / 100, 2),
                "voc_ppb": voc,
            }

    @staticmethod
    def decode_firmware_version(raw):
        if raw == 0xFFFFFFFF:
            return None

        major = (raw >> 24) & 0xFF
        minor = (raw >> 16) & 0xFF
        patch = (raw >> 8) & 0xFF

        if major == minor == patch == 0:
            return None

        return f"{major}.{minor}.{patch}"

    # ACP decoder
    def decode_acp_response(self, raw):
        """Decode Wave Mini ACP response fields."""

        raw = bytes(raw)

        if len(raw) != 34:
            return {
                "valid": False,
                "error": f"Unexpected ACP response length: {len(raw)}",
            }

        if raw[0] != self.ACP_COMMAND[0]:
            return {
                "valid": False,
                "error": "Unexpected ACP response command",
            }

        values = struct.unpack("<2L4B2HL4HL", raw[2:])
        illuminance_lux = int.from_bytes(raw[22:24], "little")
        battery_mv = values[11]

        return {
            "valid": True,
            "airthingschip": {
                "ble": values[1],
                "sub": values[8],
            },
            "illuminance_lux": illuminance_lux,
            "battery_mv": battery_mv,
            "battery_voltage_v": battery_mv / 1000.0,
            "raw_hex": raw.hex(" "),
        }

    # Configuration
    async def collect_config(self, response_timeout=None):
        """
        Read and decode the Wave Mini configuration.

        Sends 66 00 through the ACP characteristic and decodes
        the configuration response.
        """

        from WaveMiniConfig import decode_config, print_config

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

            print(
                "Requesting Wave Mini configuration:",
                self.CONFIG_READ_COMMAND.hex(" "),
                flush=True,
            )

            await client.write_gatt_char(
                self.ACP_CHARACTERISTIC_UUID,
                self.CONFIG_READ_COMMAND,
                response=True,
            )

            await asyncio.wait_for(
                response_event.wait(),
                timeout=response_timeout,
            )

        except asyncio.TimeoutError:
            raise TimeoutError(
                "Wave Mini did not return a configuration response."
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

        print("\n========== WAVE MINI CONFIGURATION ==========")
        print_config(config)
        print("\nConfiguration read successful.")

        return config

    async def write_config_and_verify(self, config, response_timeout=None):
        from WaveMiniConfig import (
            encode_config_write,
            decode_config,
            print_config,
        )

        return await self._write_config_and_verify(
            config,
            encode_config_write,
            decode_config,
            print_config,
            "Wave Mini",
            response_timeout,
        )

    # History request and response
    def report_history_packet(self, packet, received, requested):
        """Report a received Wave Mini history block."""

        packet = bytes(packet)

        print(
            f"Received block {packet[0]:02x} "
            f"({packet[3]} records) [{received}/{requested}]",
            flush=True,
        )

    def build_history_request(self, requested_blocks):
        """Build the Wave Mini history request."""

        return struct.pack(
            "<BHHHH",
            0x01,
            self.MODE,
            requested_blocks - 1,
            self.HOURS,
            0,
        )

    def handle_history_command(self, data):
        """Decode the Wave Mini history command response."""

        data = bytes(data)

        if len(data) < 4:
            return {
                "status": "unknown",
                "raw": data.hex(" "),
            }

        command = data[0]
        status = data[1]
        reported_packets = int.from_bytes(data[-2:], "big")

        if command == 0x01 and status == 0x00:
            return {
                "status": "success",
                "reported_packets": reported_packets,
                "raw": data.hex(" "),
            }

        if command == 0x01:
            return {
                "status": "error",
                "status_code": status,
                "reported_packets": reported_packets,
                "raw": data.hex(" "),
            }

        return {
            "status": "unknown",
            "raw": data.hex(" "),
        }

    def is_history_complete_response(self, data, requested_blocks):
        """
        Wave Mini reports how many history blocks are available.

        The reported count may be smaller than the requested count.
        """

        data = bytes(data)

        if len(data) < 4:
            return False

        if data[0] != 0x01 or data[1] != 0x00:
            return False

        response_count = int.from_bytes(data[-2:], "big")
        return 0 <= response_count <= requested_blocks

    # History packet validation
    def get_history_packet_identity(self, packet):
        """Identify a history block by ID and timestamp."""

        packet = bytes(packet)

        if len(packet) < 8:
            return packet

        block_id = packet[0]
        block_timestamp = struct.unpack_from("<I", packet, 4)[0]

        return block_id, block_timestamp

    def is_valid_history_packet(self, packet):
        """Validate a Wave Mini history packet."""

        if len(packet) != self.HISTORY_PACKET_LENGTH:
            return False

        return packet[3] <= self.MAX_HISTORY_RECORDS

    # History decoder
    @classmethod
    def decode_history_block(cls, data):
        """Decode one 205-byte Wave Mini history packet."""

        data = bytes(data)

        if len(data) != cls.HISTORY_PACKET_LENGTH:
            raise ValueError(f"Unexpected packet length: {len(data)}")

        block_id = data[0]
        count = min(data[3], cls.RECORDS_PER_PACKET)
        block_ts = struct.unpack_from("<I", data, 4)[0]

        block_time = datetime.fromtimestamp(
            block_ts,
            timezone.utc,
        ).isoformat()

        records = []

        for index in range(count):
            timestamp = block_ts + index * cls.SAMPLE_INTERVAL_SECONDS

            sample_time = datetime.fromtimestamp(
                timestamp,
                timezone.utc,
            ).isoformat()

            pos = cls.RECORD_OFFSET + index * cls.RECORD_SIZE
            flag = data[pos]

            temp_raw, pressure_raw, rh_raw, voc, u2 = struct.unpack_from(
                "<HHHHH",
                data,
                pos + 1,
            )

            counter = struct.unpack_from("<I", data, pos + 11)[0]
            raw = data[pos:pos + cls.RECORD_SIZE].hex(" ")

            records.append({
                "id": raw.replace(" ", ""),
                "block_id": block_id,
                "block_timestamp": block_ts,
                "block_time_utc": block_time,
                "timestamp": timestamp,
                "timestamp_utc": sample_time,
                "index": index,
                "sample": index + 1,
                "temperature_c": round(temp_raw / 100 - 273.15, 2),
                "humidity_pct": round(rh_raw / 100, 2),
                "voc_ppb": voc,
                "flag": flag,
                "pressure_hpa": pressure_raw / 50.0,
                "unknown2": u2,
                "counter": counter,
                "raw_hex": raw,
            })

        return {
            "block_id": block_id,
            "block_id_hex": f"0x{block_id:02x}",
            "block_timestamp": block_ts,
            "block_time_utc": block_time,
            "record_count": count,
            "header_status": data[24],
            "raw_hex": data.hex(" "),
            "records": records,
        }

    # History collection
    async def collect_history(self, hours=1, full=False, timeout=None):
        """Collect and store Wave Mini history."""

        if full:
            requested_packets = self.FULL_PACKETS
            hours = requested_packets
        else:
            if hours is None:
                raise ValueError("Specify hours or use full=True")

            requested_packets = self.calculate_history_packets(hours)

        transfer = await super().collect_history(
            requested_blocks=requested_packets,
            timeout=timeout,
        )

        transfer["complete"] = (
            transfer["complete"] or transfer["device_confirmed"]
        )

        blocks = [
            self.decode_history_block(packet)
            for packet in transfer["packets"]
        ]
        blocks.sort(key=lambda block: block["block_timestamp"])

        command_responses = [
            response.hex(" ")
            for response in transfer["command_responses"]
        ]

        retrieval = {
            "mode": self.MODE,
            "requested_hours": hours,
            "protocol_hours_field": self.HOURS,
            "requested_blocks_per_poll": requested_packets,
            "last_poll_received_blocks": len(blocks),
            "command_responses": command_responses,
        }

        result = self.save_history(
            new_blocks=blocks,
            retrieval=retrieval,
            storage_dir=self.HISTORY_DIR,
        )

        print("========== MINI HISTORY SUMMARY ==========")
        print(f"Requested history: {hours} hours ({requested_packets} packets)")
        print(
            f"Blocks received this poll: "
            f"{transfer['received_blocks']}/{requested_packets}"
        )
        print(f"Total unique blocks stored: {result['retrieval']['total_blocks']}")
        print(f"Total unique readings stored: {result['retrieval']['total_records']}")
        print(f"Complete: {transfer['complete']}")
        print(
            f"Saved: {self.HISTORY_DIR / f'{self.model_id}_{self.actual_serial or self.SN}.json'}"
        )

        return result
