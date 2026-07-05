"""seed.py — collision-resistant deterministic seed from a ticker string,
same utility used across the sibling projects (stock-forecast-bench,
ticker-clustering, multi-agent-analyst). sum(ord(c)) collides on anagrams
(e.g. 'GS' and 'KO'); crc32 over the actual bytes doesn't."""

import zlib


def stable_seed(s: str) -> int:
    return zlib.crc32(s.encode()) % (2**32)
