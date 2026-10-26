#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Автономный монитор заряда мыши RS7 (VID A8A4 / A8A5, PID 2255).

Читает уровень заряда напрямую через Windows HID API (hid.dll) с помощью ctypes,
БЕЗ запуска официального приложения DeviceDriver.exe.

Порядок определения заряда:
  1. Стандартное HID-поле "Battery Strength" (Usage Page 0x06, Usage 0x20) —
     именно его выставляют беспроводные мыши/донглы. Извлекается из feature- и
     input-отчётов через HidP_GetUsageValue.
  2. Поле "Relative/Absolute StateOfCharge" (Usage Page 0x85, Battery System) —
     для устройств с SMBus-батареей.
  3. Фолбэк: сканирование feature-отчётов с реально существующими Report ID
     в поисках байта 1..100 (эвристика).

Режимы:
  python mouse_autonomous_monitor.py            — непрерывный мониторинг (каждые 5 с)
  python mouse_autonomous_monitor.py --once     — однократный опрос и выход
  python mouse_autonomous_monitor.py --dump     — детальный дамп интерфейсов мыши
                                                  (нужен для реверса вендорского
                                                  протокола, если стандартный способ
                                                  не дал результата)

Примечание: чтение feature-отчётов (HidD_GetFeature) обычно требует прав
администратора. Без них заработает только чтение input-отчётов.

РЕЗУЛЬТАТ ДИАГНОСТИКИ КОНКРЕТНОЙ МЫШИ RS7 (VID A8A4/A8A5, PID 2255):
  * Стандартного HID-поля "Battery Strength" (0x06:0x20) в дескрипторе НЕТ —
    поэтому базовый способ вернёт None.
  * Заряд передаётся по вендорскому протоколу на интерфейсе MI_02
    (UsagePage 0xFF01): input=65 / output=65 байт, БЕЗ Report ID и БЕЗ
    feature-отчётов. Официальный софт пишет команду через WriteFile и читает
    ответ через ReadFile.
  * Команда (см. VENDOR_BATTERY_COMMAND) — 65 байт, заголовок 00 55 30.
    Ответ начинается с 00 AA 30, процент заряда лежит в байте 9.
"""

import ctypes
from ctypes import wintypes
import sys
import time
import winreg

# ------------------------------------------------------------ Перенастройка вывода
def _setup_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_setup_console()

# ----------------------------------------------------------------------- Константы
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000

WAIT_OBJECT_0 = 0
ERROR_IO_PENDING = 997

INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

HIDP_REPORT_TYPE_INPUT = 0
HIDP_REPORT_TYPE_OUTPUT = 1
HIDP_REPORT_TYPE_FEATURE = 2

# ВАЖНО: HIDP-функции (HidP_GetCaps/GetValueCaps/GetUsageValue) возвращают
# успех как 0x00110000 (HIDP_STATUS_SUCCESS), а НЕ 0.
HIDP_STATUS_SUCCESS = 0x00110000

# Usage Page "Generic Device Controls" -> Usage "Battery Strength"
HID_USAGE_PAGE_GENERIC_DEVICE = 0x0006
HID_USAGE_BATTERY_STRENGTH = 0x0020
# Usage Page "Battery System" (SMBus), usages Relative/Absolute StateOfCharge
HID_USAGE_PAGE_BATTERY_SYSTEM = 0x0085

VID_LIST = (0xA8A4, 0xA8A5)
PID = 0x2255

# --- Вендорский протокол RS7 (MI_02, 65 байт, без Report ID) ---
# Снято с DeviceDriver.exe: WriteFile на MI_02, затем ReadFile.
# Запрос заряда: 00 55 30 A5 | сумма байт [5:] | 2E и нули.
# Байт [4] — сумма байт [5..64] по модулю 256 (здесь 0x2E).
# Ответ: 00 AA 30 ..., процент — байт [9] (первый аргумент SetBatteryInfo).
VENDOR_BATTERY_COMMAND = (0x00, 0x55, 0x30, 0xA5, 0x2E, 0x2E) + (0x00,) * 59
VENDOR_BATTERY_BYTE_INDEX = 9
VENDOR_BATTERY_ACK_INDEX = 1
VENDOR_BATTERY_ACK = 0xAA
VENDOR_BATTERY_ECHO_INDEX = 2
VENDOR_BATTERY_ECHO = 0x30
VENDOR_BATTERY_INTERFACE = "MI_02"

HID_CLASS_GUID = "{4d1e55b2-f16f-11cf-88cb-001111000030}"
DEVICE_CLASSES_PATH = "SYSTEM\\CurrentControlSet\\Control\\DeviceClasses\\" + HID_CLASS_GUID

# ------------------------------------------------------------------- Структуры HID
class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.ULONG),
        ("VendorID", wintypes.USHORT),
        ("ProductID", wintypes.USHORT),
        ("VersionNumber", wintypes.USHORT),
    ]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wintypes.USHORT),
        ("UsagePage", wintypes.USHORT),
        ("InputReportByteLength", wintypes.USHORT),
        ("OutputReportByteLength", wintypes.USHORT),
        ("FeatureReportByteLength", wintypes.USHORT),
        ("Reserved", wintypes.USHORT * 17),
        ("NumberLinkCollectionNodes", wintypes.USHORT),
        ("NumberInputButtonCaps", wintypes.USHORT),
        ("NumberInputValueCaps", wintypes.USHORT),
        ("NumberInputDataIndices", wintypes.USHORT),
        ("NumberOutputButtonCaps", wintypes.USHORT),
        ("NumberOutputValueCaps", wintypes.USHORT),
        ("NumberOutputDataIndices", wintypes.USHORT),
        ("NumberFeatureButtonCaps", wintypes.USHORT),
        ("NumberFeatureValueCaps", wintypes.USHORT),
        ("NumberFeatureDataIndices", wintypes.USHORT),
    ]


class HIDP_VALUE_CAPS(ctypes.Structure):
    _fields_ = [
        ("UsagePage", wintypes.USHORT),
        ("ReportID", ctypes.c_ubyte),
        ("IsAlias", ctypes.c_ubyte),
        ("BitField", wintypes.USHORT),
        ("LinkCollection", wintypes.USHORT),
        ("LinkUsage", wintypes.USHORT),
        ("LinkUsagePage", wintypes.USHORT),
        ("IsRange", ctypes.c_ubyte),
        ("IsStringRange", ctypes.c_ubyte),
        ("IsDesignatorRange", ctypes.c_ubyte),
        ("IsAbsolute", ctypes.c_ubyte),
        ("HasNull", ctypes.c_ubyte),
        ("Reserved", ctypes.c_ubyte),
        ("BitSize", wintypes.USHORT),
        ("ReportCount", wintypes.USHORT),
        ("Reserved2", wintypes.USHORT * 5),
        ("UnitsExp", wintypes.ULONG),
        ("Units", wintypes.ULONG),
        ("LogicalMin", wintypes.LONG),
        ("LogicalMax", wintypes.LONG),
        ("PhysicalMin", wintypes.LONG),
        ("PhysicalMax", wintypes.LONG),
        # union { Range {...}; NotRange {...} } — 8 x USHORT (16 байт).
        # Для NotRange: u[0] = Usage, u[6] = DataIndex.
        # Для Range:    u[0] = UsageMin, u[1] = UsageMax.
        ("u", wintypes.USHORT * 8),
    ]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


# ------------------------------------------------------------------- Сигнатуры API
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_CreateFileW = _kernel32.CreateFileW
_CreateFileW.restype = wintypes.HANDLE
_CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
_CloseHandle = _kernel32.CloseHandle
_CloseHandle.restype = wintypes.BOOL
_CloseHandle.argtypes = [wintypes.HANDLE]

_ReadFile = _kernel32.ReadFile
_ReadFile.restype = wintypes.BOOL
_ReadFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                      ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]

_WriteFile = _kernel32.WriteFile
_WriteFile.restype = wintypes.BOOL
_WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                       ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]

_CreateEventW = _kernel32.CreateEventW
_CreateEventW.restype = wintypes.HANDLE
_CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]

_WaitForSingleObject = _kernel32.WaitForSingleObject
_WaitForSingleObject.restype = wintypes.DWORD
_WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

_GetOverlappedResult = _kernel32.GetOverlappedResult
_GetOverlappedResult.restype = wintypes.BOOL
_GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
                                 ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]

_CancelIo = _kernel32.CancelIo
_CancelIo.restype = wintypes.BOOL
_CancelIo.argtypes = [wintypes.HANDLE]

_CancelIoEx = _kernel32.CancelIoEx
_CancelIoEx.restype = wintypes.BOOL
_CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)]


_hid = ctypes.WinDLL("hid")

_HidD_GetAttributes = _hid.HidD_GetAttributes
_HidD_GetAttributes.restype = wintypes.BOOL
_HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]

_HidD_GetPreparsedData = _hid.HidD_GetPreparsedData
_HidD_GetPreparsedData.restype = wintypes.BOOL
_HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]

_HidD_FreePreparsedData = _hid.HidD_FreePreparsedData
_HidD_FreePreparsedData.restype = wintypes.BOOL
_HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]

_HidD_GetFeature = _hid.HidD_GetFeature
_HidD_GetFeature.restype = wintypes.BOOL
_HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ubyte), wintypes.ULONG]

_HidD_GetInputReport = _hid.HidD_GetInputReport
_HidD_GetInputReport.restype = wintypes.BOOL
_HidD_GetInputReport.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ubyte), wintypes.ULONG]

_HidD_SetOutputReport = _hid.HidD_SetOutputReport
_HidD_SetOutputReport.restype = wintypes.BOOL
_HidD_SetOutputReport.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ubyte), wintypes.ULONG]

_HidP_GetCaps = _hid.HidP_GetCaps
_HidP_GetCaps.restype = ctypes.c_long  # NTSTATUS
_HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]

_HidP_GetValueCaps = _hid.HidP_GetValueCaps
_HidP_GetValueCaps.restype = ctypes.c_long  # NTSTATUS
_HidP_GetValueCaps.argtypes = [
    ctypes.c_long,
    ctypes.POINTER(HIDP_VALUE_CAPS),
    ctypes.POINTER(wintypes.USHORT),
    ctypes.c_void_p,
]

_HidP_GetUsageValue = _hid.HidP_GetUsageValue
_HidP_GetUsageValue.restype = ctypes.c_long  # NTSTATUS
_HidP_GetUsageValue.argtypes = [
    ctypes.c_long,
    wintypes.USHORT,
    wintypes.USHORT,
    wintypes.USHORT,
    ctypes.POINTER(wintypes.ULONG),
    ctypes.c_void_p,
    ctypes.POINTER(ctypes.c_ubyte),
    wintypes.ULONG,
]


# --------------------------------------------------------------------- Перечисление
def enumerate_hid_interface_paths():
    """Возвращает список путей вида \\?\\HID\\... ко всем HID-интерфейсам."""
    paths = []
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, DEVICE_CLASSES_PATH)
    except OSError:
        return paths
    i = 0
    while True:
        try:
            sub = winreg.EnumKey(key, i)
            i += 1
        except OSError:
            break
        # Имя подключа: "##?#HID#VID_xxxx&PID_yyyy#instance#{class_guid}".
        # Корректный путь для CreateFileW: "\\?\HID#VID_...#instance#{class_guid}"
        # (символы '#' сохраняются, завершающий GUID интерфейсного класса нужен).
        if sub.startswith("##?#"):
            paths.append("\\\\?\\" + sub[4:])
    winreg.CloseKey(key)
    return paths


def open_device(path):
    """Открывает HID-устройство. Возвращает handle или None."""
    handle = _CreateFileW(
        path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        # Без прав администратора запись может быть недоступна;
        # пробуем открыть только на чтение (для input-отчётов и атрибутов).
        handle = _CreateFileW(
            path,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
    if handle == INVALID_HANDLE_VALUE:
        return None
    return handle


def get_attributes(handle):
    attrs = HIDD_ATTRIBUTES()
    attrs.Size = ctypes.sizeof(HIDD_ATTRIBUTES)
    if not _HidD_GetAttributes(handle, ctypes.byref(attrs)):
        return None
    return attrs


def find_matching_devices():
    """Находит все HID-интерфейсы мыши RS7. Возвращает список (path, VID, PID)."""
    result = []
    for path in enumerate_hid_interface_paths():
        handle = open_device(path)
        if handle is None:
            continue
        attrs = get_attributes(handle)
        if attrs is not None and attrs.VendorID in VID_LIST and attrs.ProductID == PID:
            result.append((path, attrs.VendorID, attrs.ProductID))
        _CloseHandle(handle)
    return result


def get_value_caps(preparsed, report_type):
    """Возвращает список HIDP_VALUE_CAPS для заданного типа отчёта."""
    caps = HIDP_CAPS()
    if _HidP_GetCaps(preparsed, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS:
        return []
    count = {
        HIDP_REPORT_TYPE_INPUT: caps.NumberInputValueCaps,
        HIDP_REPORT_TYPE_FEATURE: caps.NumberFeatureValueCaps,
        HIDP_REPORT_TYPE_OUTPUT: caps.NumberOutputValueCaps,
    }.get(report_type, 0)
    if count <= 0:
        return []
    arr = (HIDP_VALUE_CAPS * count)()
    length = wintypes.USHORT(count)
    if _HidP_GetValueCaps(report_type, arr, ctypes.byref(length), preparsed) != HIDP_STATUS_SUCCESS:
        return []
    return [arr[i] for i in range(length.value)]


def read_report_value(handle, preparsed, report_type, report_len, value_cap):
    """Читает отчёт (feature/input) и извлекает значение usage через HidP_GetUsageValue."""
    if report_len <= 0:
        return None
    buf = (ctypes.c_ubyte * report_len)()
    buf[0] = value_cap.ReportID
    if report_type == HIDP_REPORT_TYPE_FEATURE:
        ok = _HidD_GetFeature(handle, buf, report_len)
    else:
        ok = _HidD_GetInputReport(handle, buf, report_len)
    if not ok:
        return None
    usage = value_cap.u[0]  # для NotRange это Usage; для Range — UsageMin
    value = wintypes.ULONG(0)
    status = _HidP_GetUsageValue(
        report_type,
        value_cap.UsagePage,
        value_cap.LinkCollection,
        usage,
        ctypes.byref(value),
        preparsed,
        buf,
        report_len,
    )
    if status != HIDP_STATUS_SUCCESS:
        return None
    return value.value


def is_battery_cap(vc):
    """Проверяет, описывает ли value-cap поле заряда батареи."""
    if vc.UsagePage == HID_USAGE_PAGE_GENERIC_DEVICE and vc.u[0] == HID_USAGE_BATTERY_STRENGTH:
        return True
    if vc.UsagePage == HID_USAGE_PAGE_BATTERY_SYSTEM and vc.u[0] in (0x64, 0x65):
        return True
    return False


def fallback_feature_scan(handle, preparsed, caps):
    """Эвристика: перебираем реальные Report ID feature-отчётов в поисках байта 1..100."""
    report_len = caps.FeatureReportByteLength
    if report_len <= 0:
        return None
    report_ids = {vc.ReportID for vc in get_value_caps(preparsed, HIDP_REPORT_TYPE_FEATURE)}
    if not report_ids:
        report_ids = {0}
    for rid in sorted(report_ids):
        buf = (ctypes.c_ubyte * report_len)()
        buf[0] = rid
        if not _HidD_GetFeature(handle, buf, report_len):
            continue
        for b in buf[1:]:
            if 1 <= b <= 100:
                return b
    return None


def read_battery_from_handle(handle, use_fallback=True):
    """Пытается прочитать заряд (0-100) из открытого HID-устройства. None при неудаче."""
    preparsed = ctypes.c_void_p()
    if not _HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
        return None
    try:
        caps = HIDP_CAPS()
        if _HidP_GetCaps(preparsed, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS:
            return None

        # Сначала feature-отчёты (обычно требуют прав администратора),
        # затем input-отчёты.
        for report_type, report_len in (
            (HIDP_REPORT_TYPE_FEATURE, caps.FeatureReportByteLength),
            (HIDP_REPORT_TYPE_INPUT, caps.InputReportByteLength),
        ):
            for vc in get_value_caps(preparsed, report_type):
                if not is_battery_cap(vc):
                    continue
                val = read_report_value(handle, preparsed, report_type, report_len, vc)
                if val is not None and 0 <= val <= 100:
                    return val

        if use_fallback:
            return fallback_feature_scan(handle, preparsed, caps)
        return None
    finally:
        _HidD_FreePreparsedData(preparsed)


def read_battery_vendor_overall():
    """Отправляет вендорскую команду RS7 и читает байт заряда из ответа."""
    if not VENDOR_BATTERY_COMMAND:
        return None
    for path, vid, pid in find_matching_devices():
        if VENDOR_BATTERY_INTERFACE and VENDOR_BATTERY_INTERFACE.upper() not in path.upper():
            continue
        handle = open_device_overlapped(path)
        if handle is None:
            continue
        preparsed = ctypes.c_void_p()
        if not _HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
            _CloseHandle(handle)
            continue
        caps = HIDP_CAPS()
        if _HidP_GetCaps(preparsed, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS or caps.OutputReportByteLength <= 0:
            _HidD_FreePreparsedData(preparsed)
            _CloseHandle(handle)
            continue
        _report_id, buf = build_output_buffer(preparsed, caps, VENDOR_BATTERY_COMMAND)
        _wrote, resp = exchange_report(handle, buf, caps.InputReportByteLength, timeout_ms=500)
        _HidD_FreePreparsedData(preparsed)
        _CloseHandle(handle)
        if resp is None:
            continue
        ack = VENDOR_BATTERY_ACK_INDEX
        echo = VENDOR_BATTERY_ECHO_INDEX
        idx = VENDOR_BATTERY_BYTE_INDEX
        if (ack < len(resp) and resp[ack] == VENDOR_BATTERY_ACK
                and echo < len(resp) and resp[echo] == VENDOR_BATTERY_ECHO
                and 0 <= idx < len(resp) and 0 <= resp[idx] <= 100):
            return resp[idx]
    return None


def read_battery():
    """Ищет мышь и возвращает (battery_or_None, source_string)."""
    devices = find_matching_devices()
    if not devices:
        return None, "устройство не найдено"
    for path, vid, pid in devices:
        handle = open_device(path)
        if handle is None:
            continue
        val = read_battery_from_handle(handle)
        _CloseHandle(handle)
        if val is not None:
            return val, "VID %04X PID %04X" % (vid, pid)
    # Вендорский протокол RS7 (активируется, когда известна команда).
    val = read_battery_vendor_overall()
    if val is not None:
        return val, "vendor command"
    return None, "нет данных от устройства"


# ------------------------------------------------------------------------- Дамп
def dump_devices():
    devices = find_matching_devices()
    if not devices:
        print("Мышь RS7 (VID A8A4/A8A5, PID 2255) не найдена среди HID-устройств.")
        print("Убедитесь, что мышь/донгл подключены и не в спящем режиме.")
        return
    for path, vid, pid in devices:
        print("=" * 70)
        print("Интерфейс: %s" % path)
        print("VID: 0x%04X  PID: 0x%04X" % (vid, pid))
        handle = open_device(path)
        if handle is None:
            print("  (не удалось открыть устройство — вероятно, нужны права администратора)")
            continue
        preparsed = ctypes.c_void_p()
        if not _HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
            print("  (не удалось получить preparsed data)")
            _CloseHandle(handle)
            continue
        try:
            caps = HIDP_CAPS()
            if _HidP_GetCaps(preparsed, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS:
                print("  (не удалось получить HIDP_CAPS)")
                continue
            print("  Top-level collection: UsagePage=0x%04X Usage=0x%04X" % (caps.UsagePage, caps.Usage))
            print("  Длины отчётов: input=%d output=%d feature=%d" % (
                caps.InputReportByteLength, caps.OutputReportByteLength, caps.FeatureReportByteLength))
            print("  Value caps: input=%d output=%d feature=%d" % (
                caps.NumberInputValueCaps, caps.NumberOutputValueCaps, caps.NumberFeatureValueCaps))
            for rt, name in (
                (HIDP_REPORT_TYPE_INPUT, "INPUT"),
                (HIDP_REPORT_TYPE_FEATURE, "FEATURE"),
                (HIDP_REPORT_TYPE_OUTPUT, "OUTPUT"),
            ):
                vcs = get_value_caps(preparsed, rt)
                if not vcs:
                    continue
                print("  [%s] value-caps:" % name)
                for vc in vcs:
                    usage = vc.u[0]
                    range_suffix = ("..%04X" % vc.u[1]) if vc.IsRange else ""
                    print("    UsagePage=0x%04X Usage=0x%04X%s ReportID=%d BitSize=%d "
                          "LogMin=%d LogMax=%d Link=%d" % (
                              vc.UsagePage, usage, range_suffix, vc.ReportID,
                              vc.BitSize, vc.LogicalMin, vc.LogicalMax, vc.LinkCollection))
        finally:
            _HidD_FreePreparsedData(preparsed)
            _CloseHandle(handle)


# ------------------------------------------------------ Отправка команд / прослушка
def hex_str(data):
    return " ".join("%02X" % b for b in data)


def open_device_overlapped(path):
    """Открывает устройство с FILE_FLAG_OVERLAPPED (для асинхронного ReadFile)."""
    handle = _CreateFileW(path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                          None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
    if handle == INVALID_HANDLE_VALUE:
        handle = _CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                              None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
    if handle == INVALID_HANDLE_VALUE:
        return None
    return handle


def read_input_report_timeout(handle, length, timeout_ms=1500):
    """Асинхронно читает input-отчёт через ReadFile. Возвращает bytes или None."""
    if length <= 0:
        return None
    buf = (ctypes.c_ubyte * length)()
    event = _CreateEventW(None, True, False, None)
    if not event:
        return None
    ov = OVERLAPPED()
    ov.hEvent = event
    nread = wintypes.DWORD(0)
    ok = _ReadFile(handle, buf, length, ctypes.byref(nread), ctypes.byref(ov))
    if not ok and ctypes.get_last_error() != ERROR_IO_PENDING:
        _CloseHandle(event)
        return None
    if ok:
        _CloseHandle(event)
        return bytes(buf[:nread.value])
    res = _WaitForSingleObject(event, timeout_ms)
    if res == WAIT_OBJECT_0:
        _GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(nread), False)
        _CloseHandle(event)
        return bytes(buf[:nread.value])
    _CancelIo(handle)
    _WaitForSingleObject(event, 500)
    _CloseHandle(event)
    return None


def get_output_report_id(preparsed):
    """Report ID первого output-отчёта (0, если отчёты без ID)."""
    vcs = get_value_caps(preparsed, HIDP_REPORT_TYPE_OUTPUT)
    return vcs[0].ReportID if vcs else 0


def build_output_buffer(preparsed, caps, payload):
    """Собирает output-отчёт длины OutputReportByteLength. Без Report ID байт 0 — данные."""
    report_id = get_output_report_id(preparsed)
    out_len = caps.OutputReportByteLength
    buf = (ctypes.c_ubyte * out_len)()
    off = 1 if report_id != 0 else 0
    if report_id != 0:
        buf[0] = report_id
    for i, b in enumerate(payload):
        if off + i < out_len:
            buf[off + i] = b
    return report_id, buf


def _write_overlapped(handle, buf, timeout_ms):
    """Пишет выходной HID-отчёт через WriteFile. Хэндл должен быть overlapped."""
    event = _CreateEventW(None, True, False, None)
    if not event:
        return False
    ov = OVERLAPPED()
    ov.hEvent = event
    nwritten = wintypes.DWORD(0)
    ok = _WriteFile(handle, buf, len(buf), ctypes.byref(nwritten), ctypes.byref(ov))
    if not ok and ctypes.get_last_error() != ERROR_IO_PENDING:
        _CloseHandle(event)
        return False
    if not ok:
        if _WaitForSingleObject(event, timeout_ms) != WAIT_OBJECT_0:
            _CancelIoEx(handle, ctypes.byref(ov))
            _WaitForSingleObject(event, 500)
            _CloseHandle(event)
            return False
        if not _GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(nwritten), False):
            _CloseHandle(event)
            return False
    _CloseHandle(event)
    return True


def exchange_report(handle, out_buf, in_len, timeout_ms):
    """Вешает ReadFile, затем пишет out_buf через WriteFile и дожидается ответа.

    Чтение ставится раньше записи: ответ MI_02 короткий, и поздний ReadFile его теряет.
    Возвращает (write_ok, bytes|None).
    """
    reader = None
    if in_len > 0:
        in_buf = (ctypes.c_ubyte * in_len)()
        read_event = _CreateEventW(None, True, False, None)
        if not read_event:
            return False, None
        read_ov = OVERLAPPED()
        read_ov.hEvent = read_event
        nread = wintypes.DWORD(0)
        read_ok = _ReadFile(handle, in_buf, in_len, ctypes.byref(nread), ctypes.byref(read_ov))
        if not read_ok and ctypes.get_last_error() != ERROR_IO_PENDING:
            _CloseHandle(read_event)
            return False, None
        reader = (in_buf, read_event, read_ov, nread, bool(read_ok))

    wrote = _write_overlapped(handle, out_buf, timeout_ms)
    if reader is None:
        return wrote, None
    in_buf, read_event, read_ov, nread, already = reader
    if not wrote:
        _CancelIoEx(handle, ctypes.byref(read_ov))
        _WaitForSingleObject(read_event, 500)
        _CloseHandle(read_event)
        return False, None
    if not already:
        if _WaitForSingleObject(read_event, timeout_ms) != WAIT_OBJECT_0:
            _CancelIoEx(handle, ctypes.byref(read_ov))
            _WaitForSingleObject(read_event, 500)
            _CloseHandle(read_event)
            return True, None
        if not _GetOverlappedResult(handle, ctypes.byref(read_ov), ctypes.byref(nread), False):
            _CloseHandle(read_event)
            return True, None
    _CloseHandle(read_event)
    return True, bytes(in_buf[:nread.value])


def probe_send(hex_bytes, interface_filter=None, timeout_ms=1500):
    """Пишет output-отчёт через WriteFile и печатает ответный input-отчёт."""
    devices = find_matching_devices()
    if not devices:
        print("Мышь RS7 не найдена.")
        return
    sent_any = False
    for path, vid, pid in devices:
        if interface_filter and interface_filter.upper() not in path.upper():
            continue
        handle = open_device_overlapped(path)
        if handle is None:
            continue
        preparsed = ctypes.c_void_p()
        if not _HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
            _CloseHandle(handle)
            continue
        caps = HIDP_CAPS()
        if _HidP_GetCaps(preparsed, ctypes.byref(caps)) != HIDP_STATUS_SUCCESS or caps.OutputReportByteLength <= 0:
            _HidD_FreePreparsedData(preparsed)
            _CloseHandle(handle)
            continue
        report_id, buf = build_output_buffer(preparsed, caps, hex_bytes)
        wrote, resp = exchange_report(handle, buf, caps.InputReportByteLength, timeout_ms)
        print("-> %s (VID %04X)" % (path.split("HID", 1)[-1][:55], vid))
        print("   WRITEFILE id=%d len=%d: %s -> %s" % (report_id, len(buf), hex_str(buf), "OK" if wrote else "FAIL"))
        if resp is not None:
            pct = [i for i, b in enumerate(resp) if 1 <= b <= 100]
            print("   INPUT len=%d: %s  battery-like idx=%s" % (len(resp), hex_str(resp), pct))
        else:
            print("   INPUT: (нет ответа за %d мс)" % timeout_ms)
        sent_any = True
        _HidD_FreePreparsedData(preparsed)
        _CloseHandle(handle)
    if not sent_any:
        print("Нет интерфейсов с output-отчётом" + (" (фильтр: %s)" % interface_filter if interface_filter else "") + ".")


def probe_listen(seconds, interface_filter=None):
    """Слушает input-отчёты выбранных интерфейсов."""
    devices = find_matching_devices()
    if not devices:
        print("Мышь RS7 не найдена.")
        return
    for path, vid, pid in devices:
        if interface_filter and interface_filter.upper() not in path.upper():
            continue
        handle = open_device_overlapped(path)
        if handle is None:
            continue
        preparsed = ctypes.c_void_p()
        if not _HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
            _CloseHandle(handle)
            continue
        caps = HIDP_CAPS()
        in_len = 0
        if _HidP_GetCaps(preparsed, ctypes.byref(caps)) == HIDP_STATUS_SUCCESS:
            in_len = caps.InputReportByteLength
        _HidD_FreePreparsedData(preparsed)
        if in_len <= 0:
            _CloseHandle(handle)
            continue
        print("Слушаю %s (input=%d байт) %d c..." % (path.split("HID", 1)[-1][:55], in_len, seconds))
        t0 = time.time()
        got = 0
        while time.time() - t0 < seconds:
            resp = read_input_report_timeout(handle, in_len, timeout_ms=1000)
            if resp is None:
                continue
            got += 1
            pct = [i for i, b in enumerate(resp) if 1 <= b <= 100]
            print("   [%d] %s  battery-like idx=%s" % (got, hex_str(resp), pct))
        if got == 0:
            print("   (отчётов нет — интерфейс молчит без команды)")
        _CloseHandle(handle)


def _arg_value(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args) and not args[i + 1].startswith("-"):
            return args[i + 1]
    return default


def _arg_tokens(args, name):
    """Все подряд идущие значения флага до следующего флага (для `--send 02 01 00`)."""
    if name not in args:
        return []
    i = args.index(name) + 1
    tokens = []
    while i < len(args) and not args[i].startswith("-"):
        tokens.append(args[i])
        i += 1
    return tokens


# -------------------------------------------------------------------------- main
def main():
    args = sys.argv[1:]
    if "--help" in args or "-h" in args:
        print(__doc__)
        return

    if "--dump" in args:
        dump_devices()
        return

    if "--once" in args:
        battery, src = read_battery()
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        if battery is not None:
            print("[%s] Заряд батареи мыши: %d%%  (источник: %s)" % (ts, battery, src))
        else:
            print("[%s] Заряд не определён (%s). Попробуйте --dump." % (ts, src))
        return

    if "--send" in args:
        tokens = _arg_tokens(args, "--send")
        hexstr = "".join(tokens)
        if not hexstr:
            print("Использование: --send HEX [--interface SUBSTR] [--timeout MS]")
            print("Пример:       --send 02 01 00 --interface MI_02")
            return
        try:
            data = bytes.fromhex(hexstr.replace(" ", "").replace(",", "").replace("0x", ""))
        except ValueError:
            print("Неверный HEX. Пример: --send 02 01 00")
            return
        ifilter = _arg_value(args, "--interface")
        tmo = int(_arg_value(args, "--timeout", "1500"))
        print("ВНИМАНИЕ: отправка произвольной команды может изменить настройки мыши.")
        probe_send(data, ifilter, tmo)
        return

    if "--listen" in args:
        sec = int(_arg_value(args, "--listen", "5"))
        ifilter = _arg_value(args, "--interface")
        probe_listen(sec, ifilter)
        return

    print("=" * 68)
    print(" Автономный монитор заряда мыши RS7 (без DeviceDriver.exe) ")
    print("=" * 68)
    print("Опрос напрямую через Windows HID API (hid.dll).")
    print("Для чтения feature-отчётов может потребоваться запуск от имени")
    print("администратора. Ctrl+C — выход.\n")

    while True:
        battery, src = read_battery()
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        if battery is not None:
            print("[%s] Заряд батареи мыши: %d%%  (источник: %s)" % (ts, battery, src))
        else:
            print("[%s] Мышь не отвечает напрямую (%s). "
                  "Пошевелите мышь или запустите --dump." % (ts, src))
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            print("\nВыход.")
            break


if __name__ == "__main__":
    main()
