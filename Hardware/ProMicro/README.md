# Rice Harvester Pro Micro HID Bridge

This firmware turns an Arduino Pro Micro 5V/16MHz ATmega32U4 board into a USB keyboard/mouse bridge for the Agent.

## Flash Firmware

1. Install Arduino IDE.
2. Connect the Pro Micro to the PC with a data USB cable.
3. Open `RiceHarvesterHidBridge/RiceHarvesterHidBridge.ino`.
4. Select a compatible ATmega32U4 board:
   - `Arduino Leonardo`, or
   - `SparkFun Pro Micro` if that board package is installed.
5. Select the COM port.
6. Upload.

## Run Agent With Pro Micro

After flashing, connect the Pro Micro to the Agent PC and run:

```powershell
.\Rice_Harvester_Agent.exe 9000 change-this-secret --hid=promicro --hid-port=COM3
```

Replace `COM3` with the port shown in Device Manager or Arduino IDE.

You can also set environment variables:

```powershell
setx RICE_HARVESTER_HID_MODE promicro
setx RICE_HARVESTER_PRO_MICRO_PORT COM3
```

Then run the Agent normally.
