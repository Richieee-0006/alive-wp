#!/usr/bin/env python3
import json
import os
import socket
import sys
import time


def _query_socket(sock_path: str, cmd: bytes) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(0.1)
        s.connect(sock_path)
        s.sendall(cmd)
        return s.recv(4096).decode("utf-8", errors="ignore").strip()


def is_active_workspace_empty(sock_path: str) -> bool:
    """Return True when the active Hyprland workspace has no open windows."""
    try:
        raw = _query_socket(sock_path, b"j/activeworkspace")
        if not raw:
            return True
        info = json.loads(raw)
        return int(info.get("windows", 0)) == 0
    except Exception:
        return True


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
    ws_empty = True
    ws_check_counter = 8
    reported_occupied = False

    # Poll Hyprland socket at ~60 Hz on empty workspaces; pause while windows are open.
    while True:
        try:
            if not ws_empty or ws_check_counter >= 8:
                ws_empty = is_active_workspace_empty(sock_path)
                ws_check_counter = 0

            if not ws_empty:
                if not reported_occupied:
                    sys.stdout.write("OCCUPIED\n")
                    sys.stdout.flush()
                    reported_occupied = True
                    last_pos = None
                    idle_reads = 0
                time.sleep(0.15)
                continue

            reported_occupied = False
            ws_check_counter += 1
            data = _query_socket(sock_path, b"cursorpos")
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
