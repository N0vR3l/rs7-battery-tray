/*
 * Логгер HID-обмена DeviceDriver.exe для реверса вендорской команды заряда RS7.
 *
 * Как пользоваться (на машине, где мышь подключена по 2.4G — VID A8A5):
 *   1) pip install frida-tools
 *   2) Скачать frida-server для Windows x64 с https://github.com/frida/frida/releases
 *      (файл вида frida-server-<ver>-windows-x86_64.exe) и запустить его.
 *   3) Запустить DeviceDriver.exe (обычный запуск, заряд виден в его GUI).
 *   4) Узнать PID:  tasklist | findstr DeviceDriver
 *   5) frida -p <PID> -l capture_rs7_command.js
 *
 * В выводе ищите WriteFile/ReadFile с длиной 65 (это отчёты MI_02, без Report ID):
 *   - WriteFile len=65 -> это КОМАНДА (байты, которые нужно отправить).
 *   - ReadFile  len=65 -> это ОТВЕТ (байт заряда — среди значений 0..100).
 *
 * Полученные байты команды впишите в mouse_autonomous_monitor.py:
 *   VENDOR_BATTERY_COMMAND = (<байты через запятую>)
 *   VENDOR_BATTERY_BYTE_INDEX = <индекс байта заряда в ответе>
 */

function dumpBytes(ptr, len) {
  if (ptr.isNull() || len <= 0 || len > 4096) return "<empty>";
  var bytes = new Uint8Array(ptr.readByteArray(len));
  var s = "";
  for (var i = 0; i < bytes.length; i++) {
    s += ("0" + bytes[i].toString(16).toUpperCase()).slice(-2) + " ";
  }
  return s;
}

function resolveExport(moduleName, funcName) {
  // Frida 17: статический Module.findExportByName убран, экспорт ищется у модуля.
  var mod = Process.findModuleByName(moduleName);
  if (mod === null) return null;
  return mod.findExportByName(funcName);
}

function hookWrite(moduleName, funcName) {
  var p = resolveExport(moduleName, funcName);
  if (p === null) return;
  Interceptor.attach(p, {
    onEnter: function (args) {
      var handle = args[0];
      var buf = args[1];
      var len = args[2].toInt32();
      var tag = "[" + moduleName + "!" + funcName + "]";
      // Показываем только короткие буферы (HID-отчёты), чтобы не тонуть в шуме SQLite.
      if (len > 0 && len <= 128) {
        console.log(tag + " h=" + handle + " len=" + len + " -> " + dumpBytes(buf, len));
      }
    }
  });
}

// ReadFile у DeviceDriver идёт с OVERLAPPED: onLeave срабатывает на ERROR_IO_PENDING,
// когда буфер ещё пустой. Ответ пишется к моменту GetOverlappedResult / сигнала события.
var pendingReads = {};

function notePendingRead(ovPtr, buf, len, handle, tag) {
  if (ovPtr.isNull()) return;
  var rec = { buf: buf, len: len, handle: handle, tag: tag };
  pendingReads[ovPtr.toString()] = rec;
  try {
    var ev = ovPtr.add(16).readPointer(); // OVERLAPPED.hEvent на x86
    if (!ev.isNull()) pendingReads["ev:" + ev.toString()] = rec;
  } catch (e) {}
}

function takePending(key) {
  var rec = pendingReads[key];
  if (!rec) return null;
  delete pendingReads[key];
  delete pendingReads[rec.ovKey];
  return rec;
}

function logCompletedRead(rec) {
  if (!rec || rec.len <= 0 || rec.len > 128) return;
  console.log(rec.tag + " h=" + rec.handle + " len=" + rec.len +
              " <- " + dumpBytes(rec.buf, rec.len));
}

function hookRead(moduleName, funcName) {
  var p = resolveExport(moduleName, funcName);
  if (p === null) return;
  Interceptor.attach(p, {
    onEnter: function (args) {
      this.buf = args[1];
      this.len = args[2].toInt32();
      this.handle = args[0];
      this.ov = args[4];
      this.tag = "[" + moduleName + "!" + funcName + "]";
    },
    onLeave: function (retval) {
      if (this.len <= 0 || this.len > 128) return;
      if (retval.toInt32() !== 0) {
        logCompletedRead({ buf: this.buf, len: this.len, handle: this.handle, tag: this.tag });
        return;
      }
      notePendingRead(this.ov, this.buf, this.len, this.handle, this.tag);
    }
  });
}

function hookOverlappedCompletion() {
  var gor = resolveExport("kernel32.dll", "GetOverlappedResult");
  if (gor !== null) {
    Interceptor.attach(gor, {
      onEnter: function (args) {
        this.ov = args[1];
      },
      onLeave: function (retval) {
        if (retval.toInt32() === 0 || this.ov.isNull()) return;
        logCompletedRead(takePending(this.ov.toString()));
      }
    });
  }
  var wait = resolveExport("kernel32.dll", "WaitForSingleObject");
  if (wait !== null) {
    Interceptor.attach(wait, {
      onEnter: function (args) {
        this.ev = args[0];
      },
      onLeave: function (retval) {
        if (retval.toInt32() !== 0 || this.ev.isNull()) return;
        logCompletedRead(takePending("ev:" + this.ev.toString()));
      }
    });
  }
}

hookWrite("kernel32.dll", "WriteFile");
hookRead("kernel32.dll", "ReadFile");
hookOverlappedCompletion();
hookWrite("hid.dll", "HidD_SetOutputReport");
hookWrite("hid.dll", "HidD_SetFeature");
hookRead("hid.dll", "HidD_GetFeature");
hookRead("hid.dll", "HidD_GetInputReport");

console.log("[*] HID-хуки установлены. Следите за len=65 (MI_02).");
