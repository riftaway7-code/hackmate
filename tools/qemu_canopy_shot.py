import argparse
import socket
import subprocess
import time
from pathlib import Path

from PIL import Image

QEMU = r"C:\Program Files\qemu\qemu-system-x86_64.exe"
OVMF_CODE = r"C:\Program Files\qemu\share\edk2-x86_64-code.fd"
OVMF_VARS_TMPL = r"C:\Program Files\qemu\share\edk2-i386-vars.fd"


def hmp(sock, cmd):
    sock.sendall((cmd + "\n").encode())
    time.sleep(0.4)
    try:
        return sock.recv(65536).decode(errors="replace")
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--esp", default="C:/Users/RAAHIM~1/AppData/Local/Temp/hmc/esp")
    ap.add_argument("--out", default="C:/Users/RAAHIM~1/AppData/Local/Temp/hmc/shots")
    ap.add_argument("--waits", default="20,35,55")
    ap.add_argument("--keys", default="")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    port = 55810

    import shutil
    vars_fd = out / "OVMF_VARS.fd"
    if not vars_fd.exists():
        shutil.copy(OVMF_VARS_TMPL, vars_fd)

    cmd = [
        QEMU,
        "-machine", "q35",
        "-m", "3072",
        "-smp", "2",
        "-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={OVMF_CODE}",
        "-drive", f"if=pflash,format=raw,unit=1,file={vars_fd}",
        "-drive", f"format=raw,file=fat:rw:{args.esp}",
        "-vga", "std",
        "-device", "qemu-xhci",
        "-device", "usb-kbd",
        "-device", "usb-mouse",
        "-rtc", "base=localtime",
        "-display", "none",
        "-monitor", f"tcp:127.0.0.1:{port},server,nowait",
        "-serial", f"file:{out / 'serial.log'}",
    ]
    print("launching qemu...")
    proc = subprocess.Popen(cmd)
    time.sleep(6)

    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    sock.settimeout(3)
    time.sleep(1)
    sock.recv(65536)

    shots = []
    last = 0
    for i, w in enumerate([int(x) for x in args.waits.split(",")]):
        time.sleep(max(0, w - last))
        last = w
        ppm = out / f"shot_{i}_{w}s.ppm"
        png = out / f"shot_{i}_{w}s.png"
        hmp(sock, f'screendump {ppm.as_posix()}')
        time.sleep(1.2)
        if ppm.exists() and ppm.stat().st_size > 0:
            Image.open(ppm).convert("RGB").save(png)
            shots.append(str(png))
            print(f"  {w}s -> {png.name} ({Image.open(png).size})")
        else:
            print(f"  {w}s -> no capture")

    for k in [x for x in args.keys.split(",") if x]:
        hmp(sock, f"sendkey {k}")
        time.sleep(1.5)
    if args.keys:
        time.sleep(2)
        ppm = out / "shot_afterkeys.ppm"
        png = out / "shot_afterkeys.png"
        hmp(sock, f'screendump {ppm.as_posix()}')
        time.sleep(1.2)
        if ppm.exists():
            Image.open(ppm).convert("RGB").save(png)
            shots.append(str(png))
            print(f"  afterkeys -> {png.name}")

    hmp(sock, "quit")
    sock.close()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

    sl = out / "serial.log"
    if sl.exists():
        txt = sl.read_text(errors="replace")
        print("\n--- serial tail ---")
        print("\n".join(txt.splitlines()[-40:]))
    print("\nshots:", shots)


if __name__ == "__main__":
    main()
