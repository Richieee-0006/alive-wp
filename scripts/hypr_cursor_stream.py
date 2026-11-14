#!/usr/bin/env python3
import socket
import os
import sys
import time

def main():
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", "")
    his = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
    if not runtime_dir or not his:
        sys.exit(1)

    sock_path = os.path.join(runtime_dir, "hypr", his, ".socket.sock")
    if not os.path.exists(sock_path):
        sys.exit(1)

    last_pos = None
    idle_reads = 0
    # Poll Hyprland socket at ~60 Hz while active, backing off when cursor is stationary.
    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                s.connect(sock_path)
                s.sendall(b"cursorpos")
                data = s.recv(64).decode("utf-8", errors="ignore").strip()
                if data and data != last_pos:
                    last_pos = data
                    idle_reads = 0
                    sys.stdout.write(data + "\n")
                    sys.stdout.flush()
                else:
                    idle_reads += 1
        except (BrokenPipeError, KeyboardInterrupt):
            sys.exit(0)
        except Exception:
            time.sleep(0.05)
            continue
        time.sleep(0.064 if idle_reads >= 30 else 0.016)

if __name__ == "__main__":
    main()
