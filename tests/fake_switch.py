"""A simulated MT-ViKI HD4X2-X that speaks the documented TCP protocol."""

from __future__ import annotations

import asyncio
import re

_ROUTE = re.compile(r"^(\d)X(\d)(?:&(\d))?\.$")
_ALL = re.compile(r"^(\d)ALL\.$")
_SAVE = re.compile(r"^SAVE(\d{1,2})\.$")
_RECALL = re.compile(r"^RECALL(\d{1,2})\.$")


class FakeSwitch:
    """In-process TCP server that behaves like the real switch."""

    def __init__(self) -> None:
        self.routing = [1, 0, 0, 0]
        self.presets: dict[int, list[int]] = {}
        self.beep = True
        self.received: list[str] = []
        self.silent = False  # when True, swallow commands without replying
        self._server: asyncio.Server | None = None
        self._clients: set[asyncio.StreamWriter] = set()
        self.port = 0

    async def start(self, port: int = 0) -> int:
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        await self.drop_clients()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def drop_clients(self) -> None:
        for writer in list(self._clients):
            writer.close()
        self._clients.clear()
        await asyncio.sleep(0)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def sws(self) -> str:
        return "SWS " + " ".join(str(v) for v in self.routing)

    async def front_panel(self, input_num: int, output_num: int) -> None:
        """Simulate a button press on the device: routing changes + SWS push."""
        self.routing[output_num - 1] = input_num
        await self._broadcast(self.sws())

    async def _broadcast(self, line: str) -> None:
        for writer in list(self._clients):
            writer.write(f"{line}\r\n".encode())
            await writer.drain()

    def respond(self, command: str) -> str:
        cmd = command.strip().upper()
        if m := _ROUTE.match(cmd):
            src, a, b = int(m[1]), int(m[2]), m[3]
            if src > 4 or not 1 <= a <= 4 or (b and not 1 <= int(b) <= 4):
                return "CMD ERROR"
            self.routing[a - 1] = src
            if b:
                self.routing[int(b) - 1] = src
            return self.sws()
        if m := _ALL.match(cmd):
            src = int(m[1])
            if src > 4:
                return "CMD ERROR"
            self.routing = [src] * 4
            return self.sws()
        if cmd == "ALL1.":
            self.routing = [1, 2, 3, 4]
            return self.sws()
        if m := _SAVE.match(cmd):
            n = int(m[1])
            if not 1 <= n <= 16:
                return "CMD ERROR"
            self.presets[n] = list(self.routing)
            return f"Save{n}."
        if m := _RECALL.match(cmd):
            n = int(m[1])
            if not 1 <= n <= 16:
                return "CMD ERROR"
            if n in self.presets:
                self.routing = list(self.presets[n])
            return self.sws()
        if cmd == "BEEPON.":
            self.beep = True
            return "BeepON."
        if cmd == "BEEPOFF.":
            self.beep = False
            return "BeepOFF."
        if cmd == "GETSERVICETYPE.":
            return "ServiceType   HDMI MATRIX"
        if cmd == "GETSERVICENUM.":
            return "ServiceNum  HD4X2-X Ver1.0"
        if cmd == "GETSWS.":
            return self.sws()
        return "CMD ERROR"

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self._clients.add(writer)
        try:
            while line := await reader.readline():
                text = line.decode().strip()
                if not text:
                    continue
                self.received.append(text)
                if self.silent:
                    continue
                reply = self.respond(text)
                # Routing changes are announced to every connected client.
                if reply.startswith("SWS") and not text.upper().startswith("GET"):
                    await self._broadcast(reply)
                else:
                    writer.write(f"{reply}\r\n".encode())
                    await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            self._clients.discard(writer)
            writer.close()
