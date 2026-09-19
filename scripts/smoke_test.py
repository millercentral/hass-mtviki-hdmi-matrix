#!/usr/bin/env python3
"""Check a real MT-ViKI HD4X2-X against what the integration expects.

Standard library only; runs on Windows, macOS and Linux with Python 3.8+.

    python smoke_test.py 192.168.0.245             # read-only checks
    python smoke_test.py 192.168.0.245 --write     # also switches outputs, then restores them
    python smoke_test.py 192.168.0.245 --listen 20 # watch for front-panel/remote changes

Close or disable the Home Assistant integration first if the switch only
accepts one TCP connection at a time (this script checks for that too).
Paste the whole output back to Claude.
"""

from __future__ import annotations

import argparse
import re
import socket
import sys
import time

SWS = re.compile(r"^SWS((?:\s+\d+)+)\s*$", re.I)


class Conn:
    def __init__(self, host: str, port: int, timeout: float = 3.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.buf = b""

    def close(self) -> None:
        self.sock.close()

    def lines(self, wait: float) -> list[str]:
        """Collect every line that arrives within `wait` seconds."""
        end = time.monotonic() + wait
        out: list[str] = []
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(1024)
            except socket.timeout:  # noqa: UP041 - keeps Python 3.8/3.9 working
                break
            if not chunk:
                out.append("<connection closed by switch>")
                break
            self.buf += chunk
            *done, self.buf = re.split(rb"[\r\n]+", self.buf)
            out += [d.decode("ascii", "replace").strip() for d in done if d.strip()]
        return out

    def ask(self, command: str, wait: float = 1.0) -> list[str]:
        start = time.monotonic()
        self.sock.sendall(f"{command}\r\n".encode("ascii"))
        replies = self.lines(wait)
        ms = (time.monotonic() - start) * 1000
        print(f"  -> {command:<16} <- {replies!r}  ({ms:.0f} ms window)")
        return replies


def routing(replies: list[str]) -> list[int] | None:
    for line in replies:
        m = SWS.match(line)
        if m:
            return [int(v) for v in m.group(1).split()]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--write", action="store_true", help="switch outputs and restore")
    ap.add_argument("--listen", type=int, default=0, metavar="SECONDS")
    args = ap.parse_args()

    results: dict[str, str] = {}
    print(f"Connecting to {args.host}:{args.port} ...")
    try:
        c = Conn(args.host, args.port)
    except OSError as err:
        print(f"FAIL: cannot connect: {err}")
        return 1
    print("  connected")

    print("\n1. Identity and routing")
    raw = c.lines(0.5)
    if raw:
        print(f"  (switch sent on connect: {raw!r})")
    c.ask("GetServiceType.")
    num = c.ask("GetServiceNum.")
    results["model"] = next((ln for ln in num if ln.lower().startswith("servicenum")), "MISSING")
    r = routing(c.ask("GetSWS."))
    results["GetSWS"] = f"OK {r}" if r else "MISSING"
    original = r

    print("\n2. Case-insensitivity and error reply")
    r2 = routing(c.ask("getsws."))
    results["lowercase"] = "OK" if r2 else "no SWS reply"
    err = c.ask("Bogus.")
    results["CMD ERROR"] = "OK" if any("CMD ERROR" in ln.upper() for ln in err) else f"got {err!r}"

    print("\n3. Second simultaneous connection")
    try:
        c2 = Conn(args.host, args.port, timeout=3)
        rr = routing(c2.ask("GetSWS."))
        results["2nd client"] = "accepted and answered" if rr else "accepted but silent"
        c2.close()
    except OSError as e:
        results["2nd client"] = f"refused ({e})"
    r3 = routing(c.ask("GetSWS."))
    results["1st client after 2nd"] = "still works" if r3 else "BROKEN"

    if args.write and original:
        print("\n4. Switching (restored afterwards)")
        test_input = 2 if original[1] != 2 else 3
        rep = c.ask(f"{test_input}X2.")
        got = routing(rep)
        results["route 1 output"] = (
            "OK" if got and got[1] == test_input else f"unexpected {rep!r}"
        )
        rep = c.ask(f"{test_input}ALL.")
        got = routing(rep)
        results["route all"] = (
            "OK" if got and got[0] == test_input and got[1] == test_input
            else f"unexpected {rep!r}"
        )
        for out in range(1, len(original) + 1):
            c.ask(f"{original[out - 1]}X{out}.")
        final = routing(c.ask("GetSWS."))
        results["restored"] = "OK" if final == original else f"now {final}, was {original}"

    if args.listen:
        print(f"\n5. Listening {args.listen}s: press input buttons on the switch or remote now")
        seen = c.lines(args.listen)
        for line in seen:
            print(f"  <- {line!r}")
        results["push on front panel"] = (
            f"{sum(1 for ln in seen if SWS.match(ln))} SWS line(s)" if seen else "nothing received"
        )

    print("\n2-minute idle test skipped (run with --listen 130 to check idle disconnects)"
          if args.listen < 120 else "")
    c.close()

    print("\nSummary")
    for k, v in results.items():
        print(f"  {k:<22} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
