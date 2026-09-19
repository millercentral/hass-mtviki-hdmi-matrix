"""Async TCP client for the MT-ViKI HD4X2-X HDMI matrix switcher.

This module has no Home Assistant imports so it can be tested and reused on
its own (see scripts/smoke_test.py).

Protocol summary (see the project's protocol document):
    [x]X[y].    route input x to output y (x=0 means no signal)
    [x]ALL.     route input x to every output
    Save[n].    store the current routing in preset n (1-16)
    Recall[n].  load preset n
    GetSWS.     report routing -> "SWS a b c d" (input per output 1-4)
    GetServiceNum.  -> "ServiceNum  HD4X2-X Ver1.0"
Commands end with "." and CR/LF. The switch also pushes an unsolicited
"SWS ..." line when routing changes from the front panel or IR remote.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
from dataclasses import dataclass
import logging
import re

_LOGGER = logging.getLogger(__name__)

NUM_INPUTS = 4
NUM_OUTPUTS = 2
NUM_PRESETS = 16

DEFAULT_PORT = 8080
COMMAND_TIMEOUT = 3.0
CONNECT_TIMEOUT = 5.0
KEEPALIVE_INTERVAL = 30.0
RECONNECT_MIN = 1.0
RECONNECT_MAX = 30.0

_SWS_RE = re.compile(r"^SWS((?:\s+\d+)+)\s*$", re.IGNORECASE)
_NUM_RE = re.compile(r"^ServiceNum\s+(.*)$", re.IGNORECASE)
_TYPE_RE = re.compile(r"^ServiceType\s+(.*)$", re.IGNORECASE)
_LINE_SPLIT_RE = re.compile(rb"[\r\n]+")


class MatrixError(Exception):
    """Base error for the matrix client."""


class MatrixConnectionError(MatrixError):
    """The switch could not be reached or the connection dropped."""


class MatrixCommandError(MatrixError):
    """The switch rejected a command or did not answer in time."""


@dataclass
class DeviceInfo:
    """Identification strings reported by the switch."""

    model: str | None = None
    firmware: str | None = None
    service_type: str | None = None


def parse_sws(line: str) -> list[int] | None:
    """Parse an 'SWS a b c d' line into a list of input numbers per output."""
    match = _SWS_RE.match(line.strip())
    if not match:
        return None
    return [int(v) for v in match.group(1).split()]


def parse_service_num(text: str) -> tuple[str | None, str | None]:
    """Split 'HD4X2-X Ver1.0' into (model, firmware)."""
    parts = text.split()
    if not parts:
        return None, None
    model = parts[0]
    firmware = " ".join(parts[1:]) or None
    if firmware and firmware.lower().startswith("ver"):
        firmware = firmware[3:].strip() or firmware
    return model, firmware


def _check_input(value: int) -> None:
    if not 0 <= value <= NUM_INPUTS:
        raise ValueError(f"input must be 0-{NUM_INPUTS}, got {value}")


def _check_output(value: int) -> None:
    if not 1 <= value <= NUM_OUTPUTS:
        raise ValueError(f"output must be 1-{NUM_OUTPUTS}, got {value}")


def _check_preset(value: int) -> None:
    if not 1 <= value <= NUM_PRESETS:
        raise ValueError(f"preset must be 1-{NUM_PRESETS}, got {value}")


class _LineReader:
    """Split a byte stream into lines on CR and/or LF."""

    def __init__(self, reader: asyncio.StreamReader) -> None:
        self._reader = reader
        self._buffer = b""
        self._lines: list[str] = []

    async def readline(self) -> str:
        while not self._lines:
            chunk = await self._reader.read(1024)
            if not chunk:
                raise MatrixConnectionError("connection closed by switch")
            self._buffer += chunk
            *complete, self._buffer = _LINE_SPLIT_RE.split(self._buffer)
            for raw in complete:
                text = raw.decode("ascii", errors="replace").strip()
                if text:
                    self._lines.append(text)
        return self._lines.pop(0)


async def probe(
    host: str, port: int = DEFAULT_PORT, timeout: float = CONNECT_TIMEOUT
) -> tuple[DeviceInfo, list[int]]:
    """Open a short-lived connection, read identity and routing, then close.

    Used by the config flow to validate the address before creating an entry.
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout
        )
    except (OSError, TimeoutError) as err:
        raise MatrixConnectionError(f"cannot connect to {host}:{port}: {err}") from err

    lines = _LineReader(reader)
    info = DeviceInfo()
    routing: list[int] | None = None
    try:
        async with asyncio.timeout(timeout):
            writer.write(b"GetServiceNum.\r\n")
            await writer.drain()
            while info.model is None:
                line = await lines.readline()
                if m := _NUM_RE.match(line):
                    info.model, info.firmware = parse_service_num(m.group(1))
                elif (sws := parse_sws(line)) is not None:
                    routing = sws
            writer.write(b"GetSWS.\r\n")
            await writer.drain()
            while routing is None:
                routing = parse_sws(await lines.readline())
    except TimeoutError as err:
        raise MatrixConnectionError(
            f"{host}:{port} accepted the connection but did not answer like an "
            "MT-ViKI matrix"
        ) from err
    except OSError as err:
        raise MatrixConnectionError(str(err)) from err
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
    return info, routing


class MatrixClient:
    """Persistent connection to the switch with automatic reconnect.

    Call ``start()`` once; the client connects in the background, keeps the
    socket open, tracks routing from every SWS line (including ones pushed
    when someone presses a front-panel button) and reconnects with backoff if
    the connection drops. Listeners are called on every state or connection
    change.
    """

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        *,
        command_timeout: float = COMMAND_TIMEOUT,
        keepalive_interval: float = KEEPALIVE_INTERVAL,
        reconnect_min: float = RECONNECT_MIN,
        reconnect_max: float = RECONNECT_MAX,
    ) -> None:
        self.host = host
        self.port = port
        self._command_timeout = command_timeout
        self._keepalive_interval = keepalive_interval
        self._reconnect_min = reconnect_min
        self._reconnect_max = reconnect_max

        self.routing: list[int] | None = None
        self.info = DeviceInfo()
        self.connected = False

        self._listeners: list[Callable[[], None]] = []
        self._writer: asyncio.StreamWriter | None = None
        self._runner: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._pending: tuple[tuple[str, ...], asyncio.Future[str]] | None = None
        self._connected_event = asyncio.Event()
        self._stopping = False

    # ------------------------------------------------------------------ public

    def add_listener(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Register a callback for state changes; returns an unsubscribe fn."""
        self._listeners.append(callback)

        def remove() -> None:
            with contextlib.suppress(ValueError):
                self._listeners.remove(callback)

        return remove

    async def start(self) -> None:
        """Start the background connection loop."""
        if self._runner is None:
            self._stopping = False
            self._runner = asyncio.create_task(
                self._run(), name=f"mtviki_matrix_{self.host}"
            )

    async def stop(self) -> None:
        """Close the connection and stop reconnecting."""
        self._stopping = True
        if self._runner is not None:
            self._runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._runner
            self._runner = None
        await self._close()

    async def wait_connected(self, timeout: float) -> bool:
        """Wait until the first successful connection (or timeout)."""
        try:
            async with asyncio.timeout(timeout):
                await self._connected_event.wait()
        except TimeoutError:
            return False
        return True

    async def route(self, input_num: int, output_num: int) -> None:
        """Route an input (0 = none) to one output."""
        _check_input(input_num)
        _check_output(output_num)
        await self._command(f"{input_num}X{output_num}.", ("SWS",))

    async def route_all(self, input_num: int) -> None:
        """Route an input (0 = none) to every output."""
        _check_input(input_num)
        await self._command(f"{input_num}ALL.", ("SWS",))

    async def save_preset(self, preset: int) -> None:
        """Store the current routing in preset 1-16."""
        _check_preset(preset)
        await self._command(f"Save{preset}.", ("SAVE",))

    async def recall_preset(self, preset: int) -> None:
        """Load preset 1-16."""
        _check_preset(preset)
        await self._command(f"Recall{preset}.", ("SWS",))

    async def refresh(self) -> None:
        """Ask the switch for its current routing."""
        await self._command("GetSWS.", ("SWS",))

    # ---------------------------------------------------------------- internals

    def _notify(self) -> None:
        for callback in list(self._listeners):
            try:
                callback()
            except Exception:  # noqa: BLE001 - never let a listener kill the loop
                _LOGGER.exception("Error in matrix listener")

    async def _command(self, command: str, expect: tuple[str, ...]) -> str:
        """Send a command and wait for a reply starting with one of `expect`."""
        async with self._lock:
            writer = self._writer
            if writer is None or not self.connected:
                raise MatrixConnectionError(
                    f"not connected to {self.host}:{self.port}"
                )
            future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            self._pending = (tuple(e.upper() for e in expect), future)
            _LOGGER.debug("-> %s", command)
            try:
                writer.write(f"{command}\r\n".encode("ascii"))
                await writer.drain()
                async with asyncio.timeout(self._command_timeout):
                    return await future
            except TimeoutError as err:
                raise MatrixCommandError(
                    f"no reply to {command!r} within {self._command_timeout}s"
                ) from err
            except OSError as err:
                raise MatrixConnectionError(str(err)) from err
            finally:
                self._pending = None

    def _handle_line(self, line: str) -> None:
        _LOGGER.debug("<- %s", line)
        upper = line.upper()

        if (sws := parse_sws(line)) is not None:
            if sws != self.routing:
                self.routing = sws
                self._notify()
        elif m := _NUM_RE.match(line):
            self.info.model, self.info.firmware = parse_service_num(m.group(1))
        elif m := _TYPE_RE.match(line):
            self.info.service_type = m.group(1).strip()

        if self._pending is not None:
            expect, future = self._pending
            if future.done():
                return
            if upper.startswith("CMD ERROR"):
                future.set_exception(MatrixCommandError("switch replied CMD ERROR"))
            elif upper.startswith(expect):
                future.set_result(line)

    async def _open(self) -> _LineReader:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), CONNECT_TIMEOUT
        )
        self._writer = writer
        self.connected = True
        return _LineReader(reader)

    async def _close(self) -> None:
        writer, self._writer = self._writer, None
        was_connected = self.connected
        self.connected = False
        if self._pending is not None and not self._pending[1].done():
            self._pending[1].set_exception(
                MatrixConnectionError("connection lost while waiting for reply")
            )
        if writer is not None:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        if was_connected and not self._stopping:
            self._notify()

    async def _keepalive(self) -> None:
        """Poll routing periodically; also detects half-open connections."""
        while True:
            await asyncio.sleep(self._keepalive_interval)
            try:
                await self.refresh()
            except MatrixError as err:
                _LOGGER.debug("Keepalive failed: %s", err)
                if self._writer is not None:
                    self._writer.close()
                return

    async def _run(self) -> None:
        delay = self._reconnect_min
        while not self._stopping:
            keepalive: asyncio.Task | None = None
            try:
                lines = await self._open()
                _LOGGER.info("Connected to MT-ViKI matrix at %s:%s", self.host, self.port)
                delay = self._reconnect_min
                self._connected_event.set()

                async def initial_query() -> None:
                    try:
                        await self._command("GetServiceNum.", ("SERVICENUM",))
                    except MatrixError as err:
                        _LOGGER.debug("GetServiceNum failed: %s", err)
                    try:
                        await self.refresh()
                    except MatrixError as err:
                        _LOGGER.debug("Initial GetSWS failed: %s", err)
                    self._notify()

                init = asyncio.create_task(initial_query())
                keepalive = asyncio.create_task(self._keepalive())
                try:
                    while True:
                        self._handle_line(await lines.readline())
                finally:
                    init.cancel()
            except asyncio.CancelledError:
                raise
            except (OSError, TimeoutError, MatrixConnectionError) as err:
                if self.connected:
                    _LOGGER.warning(
                        "Lost connection to MT-ViKI matrix at %s:%s: %s",
                        self.host, self.port, err,
                    )
                else:
                    _LOGGER.debug(
                        "Cannot connect to %s:%s: %s", self.host, self.port, err
                    )
            finally:
                if keepalive is not None:
                    keepalive.cancel()
                await self._close()

            if self._stopping:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._reconnect_max)
