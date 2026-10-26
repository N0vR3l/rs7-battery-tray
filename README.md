# RS7 Battery Tray

**English** | [Русский](README.ru.md)

Windows system-tray app for the **RS7 wireless mouse** (VID `A8A4` / `A8A5`, PID `2255`). It shows the battery percentage in the tray and sends a notification when the charge drops to a threshold you choose.

Official `DeviceDriver.exe` is **not** required. The app talks to the dongle over the Windows HID API.

---

## Using the app

### Requirements

- Windows 10 or 11
- Python 3.8+ (`python` / `pythonw` on `PATH`)
- RS7 mouse connected over 2.4 GHz (USB dongle)

### Install

From this folder:

```bat
pip install -r requirements.txt
```

### Start

Double-click `run_mouse_battery_tray.bat`, or:

```bat
pythonw mouse_battery_tray.py
```

`pythonw` starts it without a console window. If the icon is missing, open the overflow chevron next to the clock.

The icon is the current percentage:

| Color | Meaning |
| --- | --- |
| Green | Above 35% |
| Yellow | 16–35% |
| Red | 15% or below |
| Gray `?` | Mouse not found / no reply (sleep, unplugged dongle) |

Hover the icon for the exact percentage and the alert threshold.

### Tray menu (right-click)

| Item | What it does |
| --- | --- |
| Status line | Current charge and threshold (not clickable) |
| **Language** | **English** or **Русский** — menu, tooltip, and toasts switch immediately |
| **Notification threshold** | Alert at 10 / 15 / 20 / 25 / 30 / 40 / 50%, or **Other…** for a custom value |
| **Poll interval** | How often to query the mouse: 15 s, 30 s, 1 min, 5 min |
| **Notify on low battery** | Enable / disable Windows toasts |
| **Start with Windows** | Add or remove a logon entry under the current user |
| **Refresh now** | Query immediately |
| **Quit** | Exit the tray app |

Settings (including language) are saved in `mouse_battery_tray_config.json` next to the script. On first run the UI follows Windows display language (`ru` vs everything else → `en`).

### Notifications

A toast is sent when charge is **at or below** the threshold. It does not repeat on every poll. The next alert is allowed after:

- charge rises **above** the threshold again, or
- about **one hour** if it stays low.

### Autostart after moving this folder

If you already turned on **Start with Windows**, toggle it off and on again (or start the app once from the new path). Windows stores the full path to `mouse_battery_tray.py`.

---

## How the code works

There are two layers:

1. **`mouse_autonomous_monitor.py`** — find the mouse and read battery.
2. **`mouse_battery_tray.py`** — tray icon, menu, config, notifications.

### 1. Finding the device

Windows lists HID interfaces under:

`HKLM\SYSTEM\CurrentControlSet\Control\DeviceClasses\{4d1e55b2-f16f-11cf-88cb-001111000030}`

Each subkey is turned into a `\\?\HID\...` path and opened with `CreateFileW`. `HidD_GetAttributes` keeps only VID `0xA8A4` / `0xA8A5` and PID `0x2255`. One physical mouse exposes several interfaces (`MI_00`, `MI_01`, `MI_02`, …).

### 2. Reading charge (standard HID first)

Some mice expose **Battery Strength** (`Usage Page 0x06`, `Usage 0x20`) or SMBus **State of Charge** (`Usage Page 0x85`). Those are parsed with `HidP_GetValueCaps` / `HidP_GetUsageValue`.

**This RS7 does not.** There is no standard battery usage in the descriptor.

### 3. Vendor protocol on `MI_02` (what actually works)

Charge is a custom 65-byte report on interface **`MI_02`** (usage page `0xFF01`): input 65 / output 65, **no Report ID**, **no feature reports**.

Flow:

1. Open `MI_02` with overlapped I/O.
2. Arm `ReadFile` first (the reply is short; a late read misses it).
3. `WriteFile` the command, then wait for the input report.

Command (65 bytes):

```text
00 55 30 A5 2E 2E  +  59 zero bytes
```

- Byte `[4]` is the sum of bytes `[5..64]` modulo 256 (here `0x2E`).
- Reply starts with `00 AA 30`.
- **Percentage is byte `[9]`** (0–100).

That sequence was captured from official `DeviceDriver.exe` (`WriteFile` / `ReadFile`). Constants live at the top of `mouse_autonomous_monitor.py` (`VENDOR_BATTERY_*`).

CLI helpers on the monitor (not used by the tray):

```bat
python mouse_autonomous_monitor.py --once
python mouse_autonomous_monitor.py --dump
python mouse_autonomous_monitor.py --send 00 55 30 A5 2E 2E --interface MI_02
python mouse_autonomous_monitor.py --listen 5 --interface MI_02
```

### 4. Tray UI

`mouse_battery_tray.py`:

- Imports `read_battery()` from the monitor.
- Polls on a background thread (`poll_seconds`).
- Draws a 64×64 icon with **Pillow** (percentage text).
- Runs the Windows tray with **pystray**.
- Uses `icon.notify()` for toasts and a Tk dialog for a custom threshold.
- Writes `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` for autostart.

`run_mouse_battery_tray.bat` switches to this folder and starts `pythonw`.

### File map

| File | Role |
| --- | --- |
| `mouse_battery_tray.py` | Tray app |
| `mouse_autonomous_monitor.py` | HID / vendor protocol |
| `run_mouse_battery_tray.bat` | One-click launch |
| `mouse_battery_tray_config.json` | Saved settings |
| `requirements.txt` | `pystray`, `pillow` |
| `tools/capture_rs7_command.js` | Optional Frida script to log HID traffic from `DeviceDriver.exe` if the protocol ever changes |

Older experiments (`mouse_battery.py`, registry scraping, and so on) are **not** part of this folder and are not used at runtime.
