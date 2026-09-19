"""Tests for the protocol client against the simulated switch."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.mtviki_hdmi_matrix.protocol import (
    MatrixClient,
    MatrixCommandError,
    MatrixConnectionError,
    _LineReader,
    parse_service_num,
    parse_sws,
    probe,
)

from .fake_switch import FakeSwitch


async def _wait_for(predicate, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.fixture
async def client(switch):
    c = MatrixClient(
        "127.0.0.1",
        switch.port,
        command_timeout=0.5,
        keepalive_interval=60,
        reconnect_min=0.05,
        reconnect_max=0.1,
    )
    await c.start()
    assert await c.wait_connected(2)
    await _wait_for(lambda: c.routing is not None and c.info.model is not None)
    yield c
    await c.stop()


def test_parse_sws() -> None:
    assert parse_sws("SWS 1 0 0 0") == [1, 0, 0, 0]
    assert parse_sws("sws 1 2 3 4 ") == [1, 2, 3, 4]
    assert parse_sws("SWS  2  2  0  0") == [2, 2, 0, 0]
    assert parse_sws("Save1.") is None
    assert parse_sws("SWS") is None


def test_parse_service_num() -> None:
    assert parse_service_num("HD4X2-X Ver1.0") == ("HD4X2-X", "1.0")
    assert parse_service_num("HD4X2-X") == ("HD4X2-X", None)


async def test_probe(switch: FakeSwitch) -> None:
    info, routing = await probe("127.0.0.1", switch.port, timeout=1)
    assert info.model == "HD4X2-X"
    assert info.firmware == "1.0"
    assert routing == [1, 0, 0, 0]


async def test_probe_refused() -> None:
    with pytest.raises(MatrixConnectionError):
        await probe("127.0.0.1", 1, timeout=1)


async def test_probe_wrong_device(switch: FakeSwitch) -> None:
    switch.silent = True
    with pytest.raises(MatrixConnectionError):
        await probe("127.0.0.1", switch.port, timeout=0.3)


async def test_initial_state(client: MatrixClient) -> None:
    assert client.connected
    assert client.routing == [1, 0, 0, 0]
    assert client.info.model == "HD4X2-X"


async def test_route(client: MatrixClient, switch: FakeSwitch) -> None:
    await client.route(3, 2)
    assert switch.received[-1] == "3X2."
    assert client.routing == [1, 3, 0, 0]
    await client.route(0, 1)
    assert switch.received[-1] == "0X1."
    assert client.routing == [0, 3, 0, 0]


async def test_route_all(client: MatrixClient, switch: FakeSwitch) -> None:
    await client.route_all(4)
    assert switch.received[-1] == "4ALL."
    assert client.routing == [4, 4, 4, 4]


async def test_presets(client: MatrixClient, switch: FakeSwitch) -> None:
    await client.route(2, 1)
    await client.save_preset(5)
    assert switch.received[-1] == "Save5."
    await client.route(4, 1)
    assert client.routing[0] == 4
    await client.recall_preset(5)
    assert switch.received[-1] == "Recall5."
    assert client.routing[0] == 2


async def test_invalid_arguments(client: MatrixClient) -> None:
    with pytest.raises(ValueError):
        await client.route(5, 1)
    with pytest.raises(ValueError):
        await client.route(1, 3)
    with pytest.raises(ValueError):
        await client.save_preset(17)
    with pytest.raises(ValueError):
        await client.recall_preset(0)


async def test_cmd_error(client: MatrixClient) -> None:
    with pytest.raises(MatrixCommandError):
        await client._command("Bogus.", ("SWS",))


async def test_timeout(client: MatrixClient, switch: FakeSwitch) -> None:
    switch.silent = True
    with pytest.raises(MatrixCommandError):
        await client.route(2, 1)


async def test_front_panel_push(client: MatrixClient, switch: FakeSwitch) -> None:
    calls = []
    client.add_listener(lambda: calls.append(list(client.routing)))
    await switch.front_panel(4, 2)
    await _wait_for(lambda: client.routing == [1, 4, 0, 0])
    assert calls[-1] == [1, 4, 0, 0]


async def test_reconnect(client: MatrixClient, switch: FakeSwitch) -> None:
    states = []
    client.add_listener(lambda: states.append(client.connected))
    await switch.drop_clients()
    await _wait_for(lambda: False in states)
    # The client comes back on its own and re-reads the routing.
    await switch.front_panel(3, 1)  # changed while we were away
    await _wait_for(lambda: client.connected and client.routing == [3, 0, 0, 0])


async def test_not_connected() -> None:
    c = MatrixClient("127.0.0.1", 1, reconnect_min=0.05)
    with pytest.raises(MatrixConnectionError):
        await c.route(1, 1)


async def test_split_and_cr_only_lines() -> None:
    """Replies split across packets or terminated with CR only still parse."""
    reader = asyncio.StreamReader()
    lines = _LineReader(reader)
    reader.feed_data(b"SWS 1 ")
    reader.feed_data(b"2 0 0\r\nSave1.\rServiceNum  HD4X2-X Ver1.0\n\r\n")
    assert await lines.readline() == "SWS 1 2 0 0"
    assert await lines.readline() == "Save1."
    assert await lines.readline() == "ServiceNum  HD4X2-X Ver1.0"
    reader.feed_eof()
    with pytest.raises(MatrixConnectionError):
        await lines.readline()
