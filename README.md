# magcubic-root - HY310 / L018

Root & debloat toolkit for Magcubic HY310, L018 and other Allwinner H713-based projectors (Hotack OEM).

Includes `awimg.py` - a standalone Allwinner IMAGEWTY firmware unpacker/repacker that handles the per-partition checksum verification used by PhoenixUSBPro.

## Tested Devices

| Model | SoC | Android | Build | Status |
|---|---|---|---|---|
| Magcubic HY310 | Allwinner H713 | 11 (API 30) | `Projector.20250214` | Rooted |
| Magcubic L018 | Allwinner H713 | 11 (API 30) | `Projector.20250514` | Rooted |

Both devices use the same Hotack OEM platform, same Allwinner H713 SoC (Cortex-A53 running in 32-bit mode, `sun50iw12p1`), and identical IMAGEWTY firmware format. Note: some AliExpress listings falsely advertise the L018 as having an Allwinner H726 - verified via `/proc/cpuinfo` and board platform to be H713.

## Root Procedure

### Prerequisites

- ADB access to projector (enable in projector settings, connect via `adb connect <IP>:5555`)
- Python 3.6+
- Firmware `.img` file for your projector (Allwinner IMAGEWTY format)
- PhoenixUSBPro for flashing (PhoenixSuit v1.19 did not work in our testing)
- USB-A to USB-A cable (for PhoenixUSBPro flashing)

### Steps

**1. Extract boot partition from firmware**

```bash
python awimg.py extract update.img extracted/
```

**2. Patch boot.fex with Magisk**

Rename `extracted/boot.fex` to `boot.img` and patch it using the [Online Magisk Patcher](https://circlecashteam.github.io/MagiskPatcher/).

Settings:
- **Architecture: `armeabi-v7a`** (both HY310 and L018 are 32-bit ARM despite Cortex-A53 being 64-bit capable - Hotack compiles the kernel in 32-bit mode). Verify via `adb shell getprop ro.product.cpu.abi`.
- **Patch VBMeta Flag: enabled**
- Recovery Mode: disabled

**3. Repack firmware with patched boot**

```bash
python awimg.py replace update.img boot.fex magisk_patched.img update_rooted.img
```

This performs an in-place byte-for-byte copy of the original firmware and only replaces the boot partition data + updates the Allwinner partition checksum (`Vboot.fex`).

**4. Flash**

Three options, from easiest to most involved:

#### Option A: USB stick (no cable needed)

1. Format a USB stick as FAT32
2. Create a folder `update` on the stick
3. Create a file `update/auto_update.txt` with the content: `sunxi_flash write update/update.img firmware`
4. Rename `update_rooted.img` to `update.img` and copy it into the `update` folder
5. **All file and folder names must be lowercase** - the projector is case-sensitive
6. Unplug the projector from power
7. Insert the USB stick into the projector
8. Plug the projector into power - **do not press the power button**. The flash starts automatically (green progress bar)
9. Wait for completion. Do not interrupt.
10. Unplug power, remove the USB stick (otherwise it will flash again on next boot), then power on normally

#### Option B: Local update via UI

If the projector still boots and you have ADB access, you can trigger a local update through the system UI:
1. Copy `update_rooted.img` (renamed to `update.img`) to a USB stick as described above
2. Insert the USB stick
3. Open **Settings > About > System Update > Local Update** and select the image

#### Option C: PhoenixUSBPro (FEL mode, for bricked devices)

1. Install PhoenixUSBPro and the Allwinner USB drivers (typically bundled with your projector's firmware package)
2. Connect a **USB-A to USB-A cable** between your PC and the projector's USB port
3. Power off the projector completely (unplug power)
4. Open PhoenixUSBPro, load `update_rooted.img`
5. Enter FEL mode: Hold the **reset pinhole button** (small hole near HDMI port, use a paperclip) -> connect the **USB-A cable** to PC -> plug in the **power cable** -> release the reset button after ~3 seconds. The device should show up as `VID_1F3A PID_EFE8` in Device Manager.
6. PhoenixUSBPro detects the device and starts flashing. **Do not interrupt** - it may appear stuck at 33-40%, this is normal.
7. Wait for 100%. The projector will **not** reboot automatically - disconnect power once PhoenixUSBPro confirms the flash is complete, then power on normally.

**5. Post-flash**

Install the Magisk app on the projector. If Magisk shows a "needs reinstall" warning, tap **Install -> Direct Install** within the app and reboot.

## awimg.py

Standalone tool for Allwinner IMAGEWTY firmware images. No dependencies beyond Python stdlib.

```bash
# List partitions
python awimg.py list update.img

# Extract all partitions
python awimg.py extract update.img output/

# Replace a single partition (in-place, preserves checksums)
python awimg.py replace update.img boot.fex patched_boot.img update_new.img

# Repack from extracted directory
python awimg.py repack output/ update_new.img
```

### Checksum handling

Allwinner firmware images use per-partition verification files (`Vboot.fex`, `Vsuper.fex`, etc.) containing a uint32 LE checksum (sum of all 32-bit LE words in the partition data). The `replace` command automatically recalculates this checksum. Without this, PhoenixUSBPro will fail at the corresponding partition with error `0x164`.

## Bloatware

These system apps were found on the HY310 and L018 and should be disabled or removed. Both devices ship with the same bloatware suite. All run as system (uid=1000) or with excessive permissions.

Some models (notably the HY300 Pro+) ship with additional malware including `com.hotack.silentsdk` (a full RAT/dropper) and `com.hotack.writesn`. See [this detailed analysis](https://zanestjohn.com/blog/reing-with-claude-code) for more information on the silentsdk malware ecosystem, including C2 infrastructure and residential proxy (KKOIP/Kookeey) connections.

| Package | Description | Permissions | Action |
|---|---|---|---|
| `com.hotack.silentsdk` | RAT / dropper, contacts api.pixelpioneerss.com, downloads stage 2 payload | System UID, INTERNET | **Remove** (not on all models) |
| `com.htc.expandsdk` | Ad injection & malware persistence, contacts pb-api.aodintech.com | System UID, INTERNET | **Remove** (found on L018, not on HY310) |
| `com.htc.eventuploadservice` | Telemetry / remote administration | INTERNET, CAMERA, RECORD_AUDIO, READ_LOGS, INJECT_EVENTS, LOCATION, READ_CONTACTS, INSTALL/DELETE_PACKAGES, MASTER_CLEAR | **Remove** |
| `com.htc.storeos` | Unverified app store | INTERNET, INSTALL/DELETE_PACKAGES, CLEAR_APP_USER_DATA, WRITE_SECURE_SETTINGS | **Remove** |
| `com.htc.htcotaupdate` | OTA updater (unknown source) | INTERNET, RECOVERY, REBOOT, INSTALL_PACKAGES | **Remove** |
| `com.android.toofifi` | Casting service, phones home to China | System UID, INTERNET | **Remove** |
| `com.toofifi.lineserver` | USB cast server (toofifi stack) | System UID | **Remove** |
| `com.huawei.connection` | Huawei service on Allwinner hardware | System UID | **Remove** (if present) |
| `com.htc.hyk_test` | Factory test (44MB, never removed) | INJECT_EVENTS, BOOT_COMPLETED | **Remove** |
| `com.htc.samescreen` | Screen sharing | INTERNET | Optional |
| `android.rockchip.update.service` | Rockchip updater on Allwinner hardware | INTERNET, INSTALL_PACKAGES | **Remove** |
| `com.hysd.vafocus` | Autofocus motor control | System UID | Keep (hardware) |
| `com.htc.magcubicos` | Stock launcher (HY310) | System UID | Keep if you need projector alignment tools |
| `com.htc.luminaos` | Stock launcher (L018) | System UID | Keep if you need projector alignment tools |

### Disable via ADB (reversible)

```bash
adb shell su -c 'pm disable-user --user 0 com.htc.eventuploadservice'
```

### Remove via ADB (requires root)

```bash
adb shell su -c 'mount -o remount,rw /product'
adb shell su -c 'rm -rf /product/app/EventUploadService'
adb shell su -c 'pm uninstall --user 0 com.htc.eventuploadservice'
```

Note: Apps on `/system` cannot be deleted (dm-verity protected) but `pm uninstall --user 0` effectively removes them for the user.

### Neutralize malicious boot scripts

The firmware ships with two scripts in `/system/bin/` that run at boot:

- **`appsdisable`** - disables all Google boot receivers including Play Protect on first boot
- **`preinstall`** - silently installs APKs from `/*/preinstall/` directories

With root, you can remount `/` as read-write and truncate `appsdisable` to neutralize it:

```bash
adb shell su -c 'mount -o remount,rw /'
adb shell su -c 'cp /dev/null /system/bin/appsdisable'
adb shell su -c 'settings put global start_disable 0'
```

The `/system` partition is typically 100% full, so `cp /dev/null` truncates the file to 0 bytes without needing free space. The `preinstall` script can be left alone as long as the preinstall directories are empty (verify with `find /*/preinstall -name "*.apk"`).

The L018 also has `/vendor/etc/init/init.hotack.rc` which starts a Zeasn TV platform service and sets permissions on `/vendor/zeasn/`. This is not directly malicious but is part of the Hotack OEM infrastructure.

## Enabling Developer Mode & ADB

1. Open the stock launcher settings (gear icon) or navigate to **Settings -> About**
2. Tap **Build Number** 7 times - a toast will confirm "You are now a developer"
3. Go back to **Settings -> System -> Developer options**
4. Enable **USB Debugging** (this enables ADB over the network)
5. Connect via `adb connect <projector-ip>:5555`

## eMMC Raw Access

On stock firmware, `/dev/block/mmcblk0` (the entire eMMC chip) is **world-readable and writable** (`rw-rw-rw-`) from the unprivileged `shell` user. No root required. This is a massive security flaw in the Hotack firmware.

In theory you could root directly via this vector without a firmware image:

```bash
# find boot partition (typically mmcblk0p5 but may vary)
ls /sys/block/mmcblk0/ | grep mmcblk0p
cat /proc/partitions | grep mmcblk0
# dump boot partition from adb shell (no root needed)
BOOT_PART=mmcblk0p5  # adjust based on your device
START=$(cat /sys/block/mmcblk0/$BOOT_PART/start)
SIZE=$(cat /sys/block/mmcblk0/$BOOT_PART/size)
dd if=/dev/block/mmcblk0 of=/data/local/tmp/boot.img bs=512 skip=$START count=$SIZE
# pull, patch with Magisk, push back, then:
dd if=/data/local/tmp/boot_patched.img of=/dev/block/mmcblk0 bs=512 seek=$START conv=notrunc
```

**Not recommended.** If the patched image has any issues (wrong architecture, bad Magisk config, corrupted data), the device will bootloop and recovery requires a USB-A to USB-A cable + PhoenixUSBPro + a stock firmware image. Use the firmware repack method above instead.

## Device Notes

- **SELinux**: Permissive on all tested firmware - Magisk has no restrictions
- **Architecture**: Both HY310 and L018 are armv7l (32-bit) despite Cortex-A53 cores. AliExpress listings claiming H726/arm64 for the L018 are false.
- **Settings app**: The stock firmware ships without a launcher intent-filter for `com.android.settings`. Launch manually via `adb shell am start -n com.android.settings/.Settings` or use a launcher that supports custom shortcuts (e.g. Projectivy Launcher).
- **Open ports on stock firmware**: AirPlay (7000/7002/9528), Audio HAL (14035), various casting services - all bound to `0.0.0.0`. Isolate the projector on a separate network segment.

## Credits

- [Ithamar/awutils](https://github.com/Ithamar/awutils) - IMAGEWTY header struct definitions that `awimg.py` is based on
- [circlecashteam/MagiskPatcher](https://circlecashteam.github.io/MagiskPatcher/) - Online Magisk boot image patcher
- [4PDA forum](https://4pda.to/forum/index.php?showtopic=1099940) - L018 firmware links and USB flash procedure
- [XDA forums](https://xdaforums.com/t/magcubic-hy300-smart-projector-4k-android-11-firmware-upgrade-how-to.4676913/) - HY300/HY310 firmware upgrade documentation

## License

MIT
