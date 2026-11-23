import asyncio

from WaveMini import WaveMini
from WaveMiniConfig import update_config




async def main():
    mini = WaveMini(
        "009661",
        "C5D87590-60CE-0A72-F5C5-C6FE5CA1F85B"
    )

    try:
        await mini.connect()

        print()
        print("=" * 50)
        print("DEVICE INFORMATION")
        print("=" * 50)
        print(f"Model:       {mini.model_name}")
        print(f"Model ID:    {mini.model_id}")
        print(f"Serial:      {mini.actual_serial}")
        print(f"BLE Address: {mini.MacAddr}")
        print("=" * 50)
        print()

        # Live sensors
        print(await mini.get_readings())

        # Three history blocks
        await mini.collect_history(hours=5000)

        print("Valid packet:", mini.is_valid_history_packet(bytes(205)))
        print("Short packet:", mini.is_valid_history_packet(bytes(100)))
        print("Long packet:", mini.is_valid_history_packet(bytes(206)))

        bad_count = bytearray(205)
        bad_count[3] = 13
        print("Invalid record count:", mini.is_valid_history_packet(bad_count))

        # ACP poll
        await mini.collect_acp()

        # Configuration
        print("\nCollecting configuration...")
        config = await mini.collect_config()
        print("\nConfiguration object:")
        print(config)


        updated = update_config(
            config,
            voc_low=200,
            voc_high=2000
        )

   #     verified = await mini.write_config_and_verify(updated)

     #   print("\nVerified configuration:")
    #    print(verified)

    finally:
        await mini.disconnect()


asyncio.run(main())