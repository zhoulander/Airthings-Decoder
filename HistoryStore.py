
import json
from datetime import datetime, timezone
from pathlib import Path


class HistoryStore:
    """Persist and merge decoded device history."""

    def __init__(self, model_id, serial, storage_dir="history"):
        self.model_id = int(model_id)
        self.serial = str(serial).strip()

        self.storage_dir = Path(storage_dir)

        self.history_file = (
            self.storage_dir /
            f"{self.model_id}_{self.serial}.json"
        )

        self.acp_file = (
            self.storage_dir /
            f"{self.model_id}_{self.serial}_acp.json"
        )

    @staticmethod
    def timestamp():
        """Return the current UTC timestamp."""
        return datetime.now(timezone.utc).isoformat()

    def append_acp_responses(self, responses, output_file=None):
        """Append raw ACP responses in JSONL format."""

        if not responses:
            return None

        path = Path(output_file) if output_file else self.acp_file

        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("a", encoding="utf-8") as file:
            for response in responses:
                file.write(json.dumps(response) + "\n")

        return path

    @staticmethod
    def _without_collection_time(value):
        """Remove collection metadata for content comparisons."""
        if isinstance(value, dict):
            return {
                key: HistoryStore._without_collection_time(item)
                for key, item in value.items()
                if key != "collected_at_utc"
            }

        if isinstance(value, list):
            return [
                HistoryStore._without_collection_time(item)
                for item in value
            ]

        return value


    def merge_and_save_history(
        self,
        new_blocks,
        device,
        retrieval
    ):
        """Merge decoded history blocks and report deduplication results."""

        self.history_file.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        if self.history_file.exists():
            existing = json.loads(
                self.history_file.read_text(encoding="utf-8")
            )
        else:
            existing = {
                "blocks": [],
                "records": []
            }

        existing_device = existing.get("device")

        if existing_device is not None:
            existing_model_id = existing_device.get("model_id")
            existing_serial = existing_device.get("serial")

            if existing_model_id is not None and (
                int(existing_model_id) != self.model_id
            ):
                raise ValueError(
                    "Existing history belongs to a different model. "
                    "Refusing to merge."
                )

            if existing_serial is not None and (
                str(existing_serial).strip() != self.serial
            ):
                raise ValueError(
                    "Existing history belongs to a different device. "
                    "Refusing to merge."
                )

        def valid_timestamp(value):
            return (
                isinstance(value, int)
                and not isinstance(value, bool)
                and value not in (0, 0xFFFFFFFF)
            )

        def valid_block(block):
            if not valid_timestamp(block.get("block_timestamp")):
                return False

            # Some models include a series_start field.
            # If present, it must also be valid.
            if (
                "series_start" in block
                and not valid_timestamp(block["series_start"])
            ):
                return False

            return True

        # Remove previously persisted invalid blocks.
        existing_blocks = [
            block
            for block in existing.get("blocks", [])
            if valid_block(block)
        ]

        # Remove flattened records belonging to invalid blocks.
        existing_records = [
            record
            for record in existing.get("records", [])
            if (
                valid_timestamp(record.get("block_timestamp"))
                and (
                    "series_start" not in record
                    or valid_timestamp(record["series_start"])
                )
            )
        ]

        block_map = {
            f"{block['block_id']}:{block['block_timestamp']}": block
            for block in existing_blocks
        }

        record_map = {
            f"{record['block_timestamp']}:{record['index']}": record
            for record in existing_records
        }

        blocks_added = 0
        blocks_unchanged = 0
        blocks_updated = 0
        blocks_rejected = 0

        records_added = 0
        records_unchanged = 0
        records_updated = 0

        records_received = sum(
            len(block["records"])
            for block in new_blocks
        )

        collection_time = self.timestamp()

        for incoming_block in new_blocks:

            # Reject invalid blocks before storing anything.
            if not valid_block(incoming_block):
                blocks_rejected += 1
                continue

            block = dict(incoming_block)

            block["collected_at_utc"] = collection_time

            block["records"] = [
                {
                    **record,
                    "collected_at_utc": collection_time
                }
                for record in incoming_block["records"]
            ]

            block_key = (
                f"{block['block_id']}:{block['block_timestamp']}"
            )

            existing_block = block_map.get(block_key)

            if existing_block is None:
                blocks_added += 1

            elif (
                self._without_collection_time(existing_block)
                == self._without_collection_time(block)
            ):
                blocks_unchanged += 1

            else:
                blocks_updated += 1

            block_map[block_key] = block

            for record in block["records"]:

                record_key = (
                    f"{record['block_timestamp']}:{record['index']}"
                )

                existing_record = record_map.get(record_key)

                if existing_record is None:
                    records_added += 1

                elif (
                    self._without_collection_time(existing_record)
                    == self._without_collection_time(record)
                ):
                    records_unchanged += 1

                else:
                    records_updated += 1

                record_map[record_key] = record

        blocks = sorted(
            block_map.values(),
            key=lambda block: block["block_timestamp"]
        )

        records = sorted(
            record_map.values(),
            key=lambda record: (
                record["block_timestamp"],
                record["index"]
            )
        )

        result = {
            "device": device,
            "retrieval": {
                **retrieval,
                "last_fetched_at_utc": collection_time,
                "blocks_added": blocks_added,
                "blocks_duplicates": blocks_unchanged,
                "blocks_unchanged": blocks_unchanged,
                "blocks_updated": blocks_updated,
                "blocks_rejected_invalid_timestamp": blocks_rejected,
                "records_received": records_received,
                "records_added": records_added,
                "records_duplicates": records_unchanged,
                "records_unchanged": records_unchanged,
                "records_updated": records_updated,
                "total_blocks": len(blocks),
                "total_records": len(records)
            },
            "blocks": blocks,
            "records": records
        }

        temp_file = self.history_file.with_suffix(".tmp")

        temp_file.write_text(
            json.dumps(result, indent=2),
            encoding="utf-8"
        )

        temp_file.replace(self.history_file)

        return result

