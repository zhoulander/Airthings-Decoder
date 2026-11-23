
import asyncio


from WavePlus import WavePlus
# Change only radon thresholds
from WavePlusConfig import update_config

async def main():
    plus = WavePlus(
        "008654",
        "124FB521-A83A-C0E8-A204-AB7093CCC90A"
    )

    try:
        await plus.connect()

        print()
        print("=" * 50)
        print("DEVICE INFORMATION")
        print("=" * 50)
        print(f"Model:       {plus.model_name}")
        print(f"Model ID:    {plus.model_id}")
        print(f"Serial:      {plus.actual_serial}")
        print(f"BLE Address: {plus.MacAddr}")
        print("=" * 50)
        print()

        # Live sensors
        print(await plus.get_readings())

        # Retrieve three hours of history
        await plus.collect_history(hours=3)
#        await plus.collect_history(full=True)



        # Configuration
        config = await plus.collect_config()
        print("\nConfiguration object:")
        print(config)


        updated = update_config(
            config,
            radon_low=105,
            radon_high=205
        )

        verified = await plus.write_config_and_verify(updated)

        print("\nVerified configuration:")
        print(verified)

        # Write and read back to verify
#        verified = await plus.write_config(updated)

 #       print("\nVerified configuration:")
 #       print(verified)

    finally:
        await plus.disconnect()


asyncio.run(main())
