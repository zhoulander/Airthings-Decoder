
#!/usr/bin/env python3
"""Read-only HTTP API for stored Airthings Wave data."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query


PROJECT_DIR = Path(__file__).resolve().parent
DEVICES_FILE = PROJECT_DIR / "devices.json"
HISTORY_DIR = PROJECT_DIR / "history"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_devices():
    """Load registered devices."""

    if not DEVICES_FILE.exists():
        raise HTTPException(
            status_code=500,
            detail="Device registry not found.",
        )

    with DEVICES_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    return [
        device for device in data.get("devices", [])
        if device.get("enabled", True)
    ]


def find_device(serial):
    """Find a registered device by serial number."""

    for device in load_devices():
        if str(device["serial"]) == str(serial):
            return device

    return None


def device_info(device):
    """Return public device metadata."""

    return {
        "serial": str(device["serial"]),
        "name": device.get("name", device["model"]),
        "model": device["model"],
        "model_id": device["model_id"],
        "mac": device.get("mac"),
    }


def history_path(device):
    return HISTORY_DIR / (
        f"{device['model_id']}_{device['serial']}.json"
    )


def acp_path(device):
    return HISTORY_DIR / (
        f"{device['model_id']}_{device['serial']}_acp.json"
    )


def load_history(device):
    """Load stored sensor history."""

    path = history_path(device)

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="No stored history for this device.",
        )

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_acp(device):
    """Load stored ACP responses from JSONL."""

    path = acp_path(device)

    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="No stored ACP history for this device.",
        )

    with path.open("r", encoding="utf-8") as file:
        return [
            json.loads(line)
            for line in file
            if line.strip()
        ]


def parse_time(value):
    """Convert an ISO timestamp into a Unix timestamp."""

    try:
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.timestamp()

    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timestamp: {value}",
        )

def record_timestamp(record):
    """Return the individual reading timestamp, falling back to block time."""

    return record.get("timestamp") or record.get("block_timestamp")

app = FastAPI(
    title="Airthings API",
    description="Read-only API for stored Airthings Wave data",
    version="1.0.0",
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": utc_now(),
    }


@app.get("/api/devices")
async def get_devices():
    """List registered devices and available stored data."""

    devices = []

    for device in load_devices():
        sensor_path = history_path(device)
        acp_file = acp_path(device)

        devices.append({
            **device_info(device),
            "history_available": sensor_path.exists(),
            "acp_available": acp_file.exists(),
        })

    return {"devices": devices}


@app.get("/api/devices/{serial}")
async def get_device(serial: str):
    """Return details for one registered device."""

    device = find_device(serial)

    if device is None:
        raise HTTPException(
            status_code=404,
            detail="Device not found.",
        )

    return {
        "device": {
            **device_info(device),
            "history_available": history_path(device).exists(),
            "acp_available": acp_path(device).exists(),
        }
    }




@app.get("/api/devices/{serial}/history")
async def get_device_history(
    serial: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(default=1000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    order: Literal["asc", "desc"] = "asc",
):
    """
    Return stored history records.

    start: inclusive ISO timestamp
    end: exclusive ISO timestamp
    limit: maximum records returned
    offset: pagination offset
    """

    device = find_device(serial)

    if device is None:
        raise HTTPException(
            status_code=404,
            detail="Device not found.",
        )

    history = load_history(device)
    records = history.get("records", [])

    start_ts = parse_time(start) if start else None
    end_ts = parse_time(end) if end else None

    filtered = []

    for record in records:
        timestamp = record_timestamp(record)

        if timestamp is None:
            continue

        if start_ts is not None and timestamp < start_ts:
            continue

        if end_ts is not None and timestamp >= end_ts:
            continue

        filtered.append(record)

    filtered.sort(
        key=record_timestamp,
        reverse=(order == "desc"),
    )

    total = len(filtered)
    page = filtered[offset:offset + limit]

    return {
        "device": device_info(device),
        "total": total,
        "offset": offset,
        "limit": limit,
        "returned": len(page),
        "next_offset": (
            offset + len(page) if offset + len(page) < total else None
        ),
        "records": page,
    }


@app.get("/api/devices/{serial}/latest")
async def get_latest_readings(serial: str):
    """Return the most recent stored sensor record."""

    device = find_device(serial)

    if device is None:
        raise HTTPException(status_code=404, detail="Device not found.")

    history = load_history(device)
    records = history.get("records", [])

    valid_records = [
        record for record in records
        if record_timestamp(record) is not None
    ]

    if not valid_records:
        raise HTTPException(
            status_code=404,
            detail="No valid stored readings for this device.",
        )

    latest = max(valid_records, key=record_timestamp)

    return {
        "device": device_info(device),
        "record": latest,
    }


@app.get("/api/devices/{serial}/blocks")
async def get_device_blocks(
    serial: str,
    limit: int = Query(default=1000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    order: Literal["asc", "desc"] = "asc",
):
    """Return stored history blocks."""

    device = find_device(serial)

    if device is None:
        raise HTTPException(status_code=404, detail="Device not found.")

    history = load_history(device)
    blocks = history.get("blocks", [])

    blocks = sorted(
        blocks,
        key=lambda block: block["block_timestamp"],
        reverse=(order == "desc"),
    )

    total = len(blocks)
    page = blocks[offset:offset + limit]

    return {
        "device": device_info(device),
        "total": total,
        "offset": offset,
        "limit": limit,
        "returned": len(page),
        "next_offset": (
            offset + len(page) if offset + len(page) < total else None
        ),
        "blocks": page,
    }


@app.get("/api/devices/{serial}/retrieval")
async def get_retrieval_info(serial: str):
    """Return the latest history retrieval metadata."""

    device = find_device(serial)

    if device is None:
        raise HTTPException(status_code=404, detail="Device not found.")

    history = load_history(device)

    return {
        "device": device_info(device),
        "retrieval": history.get("retrieval"),
    }


@app.get("/api/devices/{serial}/acp")
async def get_acp_history(
    serial: str,
    limit: int = Query(default=1000, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    order: Literal["asc", "desc"] = "asc",
):
    """Return stored ACP responses."""

    device = find_device(serial)

    if device is None:
        raise HTTPException(status_code=404, detail="Device not found.")

    responses = load_acp(device)

    responses.sort(
        key=lambda response: response["response_timestamp"],
        reverse=(order == "desc"),
    )

    total = len(responses)
    page = responses[offset:offset + limit]

    return {
        "device": device_info(device),
        "total": total,
        "offset": offset,
        "limit": limit,
        "returned": len(page),
        "next_offset": (
            offset + len(page) if offset + len(page) < total else None
        ),
        "responses": page,
    }


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.INFO,
    )

    uvicorn.run(
        "AirthingsAPI:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_config=None,
    )