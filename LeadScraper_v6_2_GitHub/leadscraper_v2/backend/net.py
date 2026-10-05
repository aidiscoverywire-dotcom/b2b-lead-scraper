"""Shared outbound HTTP client factory.

All vendor calls (Google Places, Apollo, OpenAI) go through here with
``trust_env=False`` so deployment-environment proxy variables can never
break or reroute billing-sensitive API traffic. In particular, httpx
misparses common ``no_proxy`` IPv6 entries such as ``[::1]`` and raises
``InvalidURL`` before any request is made — that would take down every
vendor call on hosts whose base image ships those defaults.

v1 does not support proxy egress (documented Railway requirement:
direct internet access). If proxy support is ever needed it must be an
explicit, user-configured setting — never ambient environment.
"""
import httpx

DEFAULT_TIMEOUT = 30.0


def async_client(**kwargs) -> httpx.AsyncClient:
    kwargs.setdefault("trust_env", False)
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    return httpx.AsyncClient(**kwargs)
