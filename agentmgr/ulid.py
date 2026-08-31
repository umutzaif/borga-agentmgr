"""Minimal ULID generator (Crockford base32, stdlib only).

A ULID is 26 characters: 10 chars of millisecond timestamp + 16 chars of
randomness. Lexicographic string order matches chronological order, which is
exactly what the event log needs for cheap sorting.
"""

from __future__ import annotations

import os
import time

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_INDEX = {ch: i for i, ch in enumerate(_CROCKFORD)}

_TIME_LEN = 10   # 50 bits, enough for ms timestamps well past year 10000
_RAND_LEN = 16   # 80 bits of randomness


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        value, rem = divmod(value, 32)
        out.append(_CROCKFORD[rem])
    return "".join(reversed(out))


def new_ulid(ts_ms: int | None = None) -> str:
    if ts_ms is None:
        ts_ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    return _encode(ts_ms, _TIME_LEN) + _encode(rand, _RAND_LEN)


def ulid_timestamp_ms(ulid: str) -> int:
    value = 0
    for ch in ulid[:_TIME_LEN].upper():
        value = value * 32 + _INDEX[ch]
    return value
