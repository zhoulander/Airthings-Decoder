# BLE Protocol Research Methodology

## Purpose

This document describes how protocol findings are established and how uncertainty is represented in the Wave Mini and Wave Plus protocol references.

Research is based on BLE traffic captured from the user's own devices and phone, together with repeatable tests against the physical sensors.

The project does not incorporate Airthings application source code or proprietary firmware.

## Capture workflow

1. Enable Bluetooth HCI snoop logging on the Android test device.
2. Perform one controlled operation in the Airthings application or against the physical device.
3. Export the capture.
4. Extract relevant ATT/GATT traffic with Wireshark or `tshark`.
5. Identify the characteristic and command involved.
6. Compare request and response bytes.
7. Repeat with one setting or condition changed.
8. Record the complete raw packet and the resulting interpretation.

Large binary captures are best analyzed locally. Share focused packet extracts and the surrounding command sequence when practical.

## Evidence levels

### Confirmed

Use when a field or behavior has been validated by repeatable tests, controlled before/after packet comparisons, or an independently verified measurement.

Examples include the Wave Plus humidity threshold bytes and the Wave Mini illuminance/battery measurements.

### Strongly supported

Use when a mapping consistently matches captured values and device behavior but has not been independently established.

### Observed

Use for facts about a particular capture, such as a byte sequence, packet length, or notification order, when broader meaning is not yet established.

### Unknown

Use when a field can be extracted but its meaning is not known.

Do not promote an unknown field to a semantic name merely because its value looks plausible.

## Packet analysis rules

- Preserve complete raw packets.
- Record whether offsets are relative to the complete packet or to a payload after a header.
- State byte order for multi-byte values.
- Distinguish ATT handles from characteristic UUIDs.
- Distinguish notifications from indications and write acknowledgements.
- Do not assume one command produces exactly one notification.
- Compare packets from the same model and firmware where possible.
- Keep Wave Mini and Wave Plus layouts separate.
- Use controlled single-setting changes to identify configuration fields.
- Retain unexplained bytes in decoded output.

## Source-code comparison

Upstream libraries and protocol documentation can help identify structures and corroborate interpretations. They are supporting references, not a substitute for validating behavior on the user's hardware.

When adapting code, preserve applicable license and attribution requirements. Keep the independent packet observations and the implementation's own validation history clear.

## Recording a finding

For each new finding, record:

- Device model and model ID.
- Characteristic UUID, if known.
- Command and response bytes.
- Total packet length.
- Offset origin and endianness.
- Decoding expression.
- Example raw and decoded values.
- Evidence level.
- Remaining uncertainties.
