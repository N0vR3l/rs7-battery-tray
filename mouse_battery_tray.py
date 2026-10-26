#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
System-tray icon: RS7 mouse battery and a low-charge notification.

Start (no console):
    pythonw mouse_battery_tray.py
Or:
    python mouse_battery_tray.py

Right-click: language, notification threshold, poll interval, autostart, quit.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

# --------------------------------------------------------------------------- GUI
try:
    import tkinter as tk
    from tkinter import simpledialog, messagebox
except ImportError:
    tk = None
    simpledialog = None
    messagebox = None

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("Install: pip install pystray pillow")
    print("Установите: pip install pystray pillow")
    sys.exit(1)

from mouse_autonomous_monitor import read_battery

APP_NAME = "RS7 Battery"
CONFIG_NAME = "mouse_battery_tray_config.json"
RUN_VALUE_NAME = "RS7MouseBatteryTray"
LANGS = ("en", "ru")

STRINGS = {
    "en": {
        "waiting": "RS7 mouse: waiting…",
        "status_unknown": "Charge: no data",
        "status_unknown_src": "Charge: no data ({src})",
        "status_ok": "Charge: {pct}%  |  threshold {th}%",
        "title_unknown": "RS7 mouse: no data ({src})",
        "title_ok": "RS7 mouse: {pct}% (threshold {th}%)",
        "title_error": "RS7 mouse: poll error",
        "notify": "Notify on low battery",
        "autostart": "Start with Windows",
        "threshold_menu": "Notification threshold",
        "poll_menu": "Poll interval",
        "language_menu": "Language",
        "lang_en": "English",
        "lang_ru": "Русский",
        "other": "Other…",
        "refresh": "Refresh now",
        "quit": "Quit",
        "poll_15": "15 s",
        "poll_30": "30 s",
        "poll_60": "1 min",
        "poll_300": "5 min",
        "ask_title": "Notification threshold",
        "ask_prompt": "Notify when mouse charge falls to (%):",
        "autostart_err_title": "Autostart",
        "autostart_err": "Could not change autostart:\n{err}",
        "toast_title": "RS7 mouse battery low",
        "toast_body": "Charge is {pct}% (threshold {th}%). Time to charge the mouse.",
        "src_not_found": "device not found",
        "src_no_data": "no data from device",
        "src_error": "poll error",
        "src_vendor": "vendor command",
    },
    "ru": {
        "waiting": "Мышь RS7: ожидание…",
        "status_unknown": "Заряд: нет данных",
        "status_unknown_src": "Заряд: нет данных ({src})",
        "status_ok": "Заряд: {pct}%  |  порог {th}%",
        "title_unknown": "Мышь RS7: нет данных ({src})",
        "title_ok": "Мышь RS7: {pct}% (порог {th}%)",
        "title_error": "Мышь RS7: ошибка опроса",
        "notify": "Уведомлять при низком заряде",
        "autostart": "Запускать с Windows",
        "threshold_menu": "Порог уведомления",
        "poll_menu": "Интервал опроса",
        "language_menu": "Язык",
        "lang_en": "English",
        "lang_ru": "Русский",
        "other": "Другое…",
        "refresh": "Обновить сейчас",
        "quit": "Выход",
        "poll_15": "15 с",
        "poll_30": "30 с",
        "poll_60": "1 мин",
        "poll_300": "5 мин",
        "ask_title": "Порог уведомления",
        "ask_prompt": "Уведомить, когда заряд мыши опустится до (%):",
        "autostart_err_title": "Автозапуск",
        "autostart_err": "Не удалось изменить автозапуск:\n{err}",
        "toast_title": "Низкий заряд мыши RS7",
        "toast_body": "Заряд {pct}% (порог {th}%). Пора поставить мышь на зарядку.",
        "src_not_found": "устройство не найдено",
        "src_no_data": "нет данных от устройства",
        "src_error": "ошибка опроса",
        "src_vendor": "вендорская команда",
    },
}

SOURCE_MAP = {
    "устройство не найдено": "src_not_found",
    "нет данных от устройства": "src_no_data",
    "ошибка опроса": "src_error",
    "vendor command": "src_vendor",
    "device not found": "src_not_found",
    "no data from device": "src_no_data",
    "poll error": "src_error",
}

DEFAULTS = {
    "threshold": 20,
    "poll_seconds": 30,
    "notify_enabled": True,
    "autostart": False,
    "language": None,
}


def detect_language():
    for env in ("LANG", "LANGUAGE", "LC_ALL"):
        val = os.environ.get(env, "")
        if val.lower().startswith("ru"):
            return "ru"
    try:
        import ctypes
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if (langid & 0xFF) == 0x19:
            return "ru"
    except Exception:
        pass
    return "en"


def config_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_NAME)


def load_config():
    data = dict(DEFAULTS)
    path = config_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                data.update(stored)
        except (OSError, json.JSONDecodeError):
            pass
    data["threshold"] = int(max(1, min(99, int(data.get("threshold", 20)))))
    data["poll_seconds"] = int(max(5, min(3600, int(data.get("poll_seconds", 30)))))
    data["notify_enabled"] = bool(data.get("notify_enabled", True))
    data["autostart"] = bool(data.get("autostart", False))
    lang = data.get("language") or detect_language()
    data["language"] = lang if lang in LANGS else "en"
    return data


def save_config(cfg):
    path = config_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def autostart_command():
    script = os.path.abspath(__file__)
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = sys.executable
    return '"%s" "%s"' % (pythonw, script)


def set_autostart(enabled):
    import winreg
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_SET_VALUE,
    )
    try:
        if enabled:
            winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_VALUE_NAME)
            except FileNotFoundError:
                pass
    finally:
        winreg.CloseKey(key)


def _font(size):
    for name in ("segoeui.ttf", "arialbd.ttf", "arial.ttf", "tahoma.ttf"):
        path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_icon(percent, disconnected=False):
    """Square icon with the percentage (or '?' if the mouse does not answer)."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if disconnected or percent is None:
        fill = (90, 90, 90, 255)
        text = "?"
        font = _font(42)
    else:
        if percent <= 15:
            fill = (200, 40, 40, 255)
        elif percent <= 35:
            fill = (210, 150, 20, 255)
        else:
            fill = (40, 160, 70, 255)
        text = str(int(percent))
        font = _font(36 if percent >= 100 else 42)

    draw.rounded_rectangle((1, 1, size - 2, size - 2), radius=12, fill=fill)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1] - 1
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    return img


class TrayApp:
    def __init__(self):
        self.cfg = load_config()
        if self.cfg["autostart"]:
            try:
                set_autostart(True)
            except OSError:
                pass
        self.battery = None
        self.source = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._alerted = False
        self._last_notify_at = 0.0
        self.icon = pystray.Icon(
            APP_NAME,
            make_icon(None, disconnected=True),
            self.t("waiting"),
            menu=self._build_menu(),
        )

    def t(self, key, **kwargs):
        lang = self.cfg.get("language") or "en"
        table = STRINGS.get(lang) or STRINGS["en"]
        text = table.get(key) or STRINGS["en"].get(key, key)
        if kwargs:
            return text.format(**kwargs)
        return text

    def _localize_source(self, src):
        key = SOURCE_MAP.get(src)
        if key:
            return self.t(key)
        return src

    def _build_menu(self):
        def radio_threshold(value):
            def inner(item=None):
                return self.cfg["threshold"] == value
            return inner

        def set_threshold(value):
            def inner(icon, item):
                self._update_cfg(threshold=value)
            return inner

        def radio_poll(value):
            def inner(item=None):
                return self.cfg["poll_seconds"] == value
            return inner

        def set_poll(value):
            def inner(icon, item):
                self._update_cfg(poll_seconds=value)
            return inner

        def radio_lang(value):
            def inner(item=None):
                return self.cfg["language"] == value
            return inner

        def set_lang(value):
            def inner(icon, item):
                self._set_language(value)
            return inner

        def label(key):
            return lambda item: self.t(key)

        status = pystray.MenuItem(
            lambda item: self._status_text(),
            None,
            enabled=False,
        )
        notify_item = pystray.MenuItem(
            label("notify"),
            self._toggle_notify,
            checked=lambda item: self.cfg["notify_enabled"],
        )
        autostart_item = pystray.MenuItem(
            label("autostart"),
            self._toggle_autostart,
            checked=lambda item: self.cfg["autostart"],
        )
        thresholds = [
            pystray.MenuItem("%d%%" % v, set_threshold(v), checked=radio_threshold(v), radio=True)
            for v in (10, 15, 20, 25, 30, 40, 50)
        ]
        thresholds.append(pystray.MenuItem(label("other"), self._ask_threshold))
        polls = [
            pystray.MenuItem(label(key), set_poll(sec), checked=radio_poll(sec), radio=True)
            for key, sec in (("poll_15", 15), ("poll_30", 30), ("poll_60", 60), ("poll_300", 300))
        ]
        languages = [
            pystray.MenuItem(label("lang_en"), set_lang("en"), checked=radio_lang("en"), radio=True),
            pystray.MenuItem(label("lang_ru"), set_lang("ru"), checked=radio_lang("ru"), radio=True),
        ]
        return pystray.Menu(
            status,
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(label("language_menu"), pystray.Menu(*languages)),
            pystray.MenuItem(label("threshold_menu"), pystray.Menu(*thresholds)),
            pystray.MenuItem(label("poll_menu"), pystray.Menu(*polls)),
            notify_item,
            autostart_item,
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(label("refresh"), self._refresh_now),
            pystray.MenuItem(label("quit"), self._quit),
        )

    def _set_language(self, lang):
        if lang not in LANGS:
            lang = "en"
        self.cfg["language"] = lang
        save_config(self.cfg)
        self.icon.menu = self._build_menu()
        try:
            self.icon.update_menu()
        except Exception:
            pass
        self._apply_title()

    def _status_text(self):
        with self._lock:
            b = self.battery
            src = self.source
        if b is None:
            if src:
                return self.t("status_unknown_src", src=self._localize_source(src))
            return self.t("status_unknown")
        return self.t("status_ok", pct=b, th=self.cfg["threshold"])

    def _apply_title(self):
        with self._lock:
            battery = self.battery
            src = self.source
        if battery is None:
            if src in ("ошибка опроса", "poll error"):
                self.icon.title = self.t("title_error")
            elif src:
                self.icon.title = self.t("title_unknown", src=self._localize_source(src))
            else:
                self.icon.title = self.t("waiting")
        else:
            self.icon.title = self.t("title_ok", pct=battery, th=self.cfg["threshold"])

    def _update_cfg(self, **kwargs):
        self.cfg.update(kwargs)
        save_config(self.cfg)
        self.icon.update_menu()
        self._apply_alert_state()
        self._apply_title()

    def _toggle_notify(self, icon, item):
        self._update_cfg(notify_enabled=not self.cfg["notify_enabled"])
        if not self.cfg["notify_enabled"]:
            self._alerted = False

    def _toggle_autostart(self, icon, item):
        enabled = not self.cfg["autostart"]
        try:
            set_autostart(enabled)
            self._update_cfg(autostart=enabled)
        except OSError as exc:
            self._tk_message(self.t("autostart_err_title"), self.t("autostart_err", err=exc))

    def _ask_threshold(self, icon, item):
        if tk is None:
            return

        def run():
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            value = simpledialog.askinteger(
                self.t("ask_title"),
                self.t("ask_prompt"),
                parent=root,
                minvalue=1,
                maxvalue=99,
                initialvalue=self.cfg["threshold"],
            )
            root.destroy()
            if value is not None:
                self._update_cfg(threshold=int(value))

        threading.Thread(target=run, daemon=True).start()

    def _tk_message(self, title, text):
        if tk is None:
            return

        def run():
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(title, text)
            root.destroy()

        threading.Thread(target=run, daemon=True).start()

    def _refresh_now(self, icon, item):
        threading.Thread(target=self._poll_once, daemon=True).start()

    def _quit(self, icon, item):
        self._stop.set()
        icon.stop()

    def _notify(self, title, message):
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def _apply_alert_state(self):
        with self._lock:
            battery = self.battery
        if battery is None:
            return
        if battery > self.cfg["threshold"]:
            self._alerted = False
            return
        if not self.cfg["notify_enabled"]:
            return
        now = time.time()
        if self._alerted and now - self._last_notify_at < 3600:
            return
        self._alerted = True
        self._last_notify_at = now
        self._notify(
            self.t("toast_title"),
            self.t("toast_body", pct=battery, th=self.cfg["threshold"]),
        )

    def _poll_once(self):
        battery, src = read_battery()
        with self._lock:
            self.battery = battery
            self.source = src
        disconnected = battery is None
        self.icon.icon = make_icon(battery, disconnected=disconnected)
        self._apply_title()
        try:
            self.icon.update_menu()
        except Exception:
            pass
        self._apply_alert_state()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception:
                with self._lock:
                    self.battery = None
                    self.source = "poll error"
                self.icon.icon = make_icon(None, disconnected=True)
                self._apply_title()
            self._stop.wait(self.cfg["poll_seconds"])

    def run(self):
        threading.Thread(target=self._loop, daemon=True).start()
        self.icon.run()


def main():
    TrayApp().run()


if __name__ == "__main__":
    main()
