import pytest

from fakes.tail import socket_url


@pytest.mark.parametrize(
    "given, expected",
    [
        ("http://localhost:8000", "ws://localhost:8000/dashboard/ws"),
        ("http://localhost:8000/", "ws://localhost:8000/dashboard/ws"),
        ("https://example.trycloudflare.com", "wss://example.trycloudflare.com/dashboard/ws"),
        ("ws://localhost:8000/dashboard/ws", "ws://localhost:8000/dashboard/ws"),
        ("ws://localhost:8000", "ws://localhost:8000/dashboard/ws"),
    ],
)
def test_tail_takes_the_same_address_as_the_replayer(given, expected):
    assert socket_url(given) == expected
