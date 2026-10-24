"""Små HTTP-hjælpere (kun standardbiblioteket, så Actions ikke skal installere meget)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "indbrudskort/1.0 (+https://github.com/Wurtzv/Claude-SO7)"


def hent(url: str, params: dict | None = None, forsøg: int = 3, timeout: int = 30) -> bytes:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    sidste: Exception | None = None
    for i in range(forsøg):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "da"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if 400 <= e.code < 500 and e.code != 429:
                raise
            sidste = e
            if e.code == 429:  # for mange kald: vent som serveren beder om, ellers et halvt minut
                vent = e.headers.get("Retry-After", "")
                time.sleep(int(vent) if vent.isdigit() else 30 * (i + 1))
                continue
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            sidste = e
        time.sleep(2 ** (i + 1))
    raise sidste  # type: ignore[misc]


def hent_tekst(url: str, **kw) -> str:
    return hent(url, **kw).decode("utf-8", errors="replace")


def hent_json(url: str, **kw):
    return json.loads(hent(url, **kw))
