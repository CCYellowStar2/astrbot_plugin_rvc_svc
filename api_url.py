import os
from urllib.parse import urlsplit


_INVISIBLE_TRAILING_CHARACTERS = "\u200b\u200c\u200d\u2060\ufeff"
_DIRECT_ACCESS_HOST = "host.docker.internal"


def prepare_api_url(value: str) -> str:
    url = str(value).strip().strip(_INVISIBLE_TRAILING_CHARACTERS).strip()
    if not url:
        raise ValueError("RVC/SVC API URL cannot be empty")
    url = f"{url.rstrip('/')}/"

    host = urlsplit(url).hostname
    if host and host.casefold() == _DIRECT_ACCESS_HOST:
        for variable in ("NO_PROXY", "no_proxy"):
            entries = [entry.strip() for entry in os.environ.get(variable, "").split(",") if entry.strip()]
            if host.casefold() not in {entry.casefold() for entry in entries}:
                entries.append(host)
            os.environ[variable] = ",".join(entries)
    return url
