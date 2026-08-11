"""HTTP caching for the reference data.

Three of the read endpoints -- the equipment catalog, the labour rates and the
presets -- are opened repeatedly during a job and change perhaps a few times a
year. Without cache headers the browser refetches all of them every time a
component mounts, and each one is a round trip to a hosted database.

Two mechanisms, doing different jobs:

  Cache-Control   the browser does not ask at all until it expires
  ETag            when it does ask, an unchanged response comes back as a bare
                  304 with no body

The window is deliberately short. A shop editing its catalog should see the change
within the minute, and on a screen where a tech is quoting real money, stale
prices are a worse failure than a slow request. Anything that writes -- estimates,
settings, customers -- is never cached.
"""

from __future__ import annotations

import hashlib

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

#: Path -> how long a browser may reuse the response without asking.
#:
#: `must-revalidate` is on all of them: once stale, the browser has to check
#: rather than serve an old copy while it refreshes in the background.
CACHEABLE: dict[str, int] = {
    "/api/equipment": 300,
    "/api/equipment/categories": 300,
    "/api/labor-rates": 300,
    "/api/presets": 300,
    # Settings are edited from inside the app and every total depends on them, so
    # they revalidate every time. The ETag still makes the repeat cheap.
    "/api/config": 0,
}


class CacheHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        max_age = CACHEABLE.get(request.url.path)
        if request.method != "GET" or max_age is None or response.status_code != 200:
            return response

        # BaseHTTPMiddleware hands back a streaming response, so the body has to
        # be collected before it can be hashed.
        body = b"".join([chunk async for chunk in response.body_iterator])
        etag = '"%s"' % hashlib.sha256(body).hexdigest()[:32]

        headers = dict(response.headers)
        headers["etag"] = etag
        headers["cache-control"] = f"private, max-age={max_age}, must-revalidate"

        if request.headers.get("if-none-match") == etag:
            # Nothing changed: answer with headers only. Saves the payload, though
            # not the round trip.
            headers.pop("content-length", None)
            return Response(status_code=304, headers=headers)

        headers["content-length"] = str(len(body))
        return Response(
            content=body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )
