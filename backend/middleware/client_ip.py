"""
The client's IP address, for the LAN-only gate and the rate limiter.

X-Forwarded-For is set by whoever sends the request, so it is only believed
when the request comes from a reverse proxy listed in TRUSTED_PROXIES. Then
the client is the right-most address in the header that isn't itself a
trusted proxy. Without TRUSTED_PROXIES the header is ignored and the
connecting address is used.
"""

import ipaddress
import logging
from typing import List, Optional, Union

from starlette.requests import Request

logger = logging.getLogger(__name__)

Network = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]


def parse_networks(csv: str, setting: str = "TRUSTED_PROXIES") -> List[Network]:
    """Parse comma-separated IPs or CIDRs; invalid entries are logged and skipped."""
    networks: List[Network] = []
    for item in (csv or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            logger.warning(f"Invalid entry in {setting}: '{item}' — skipping")
    return networks


def _in(ip: str, networks: List[Network]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in n for n in networks)


def client_ip(request: Request, trusted_proxies: List[Network]) -> Optional[str]:
    """The address the request really came from (see module docstring)."""
    peer = request.client.host if request.client else None
    if not peer or not trusted_proxies or not _in(peer, trusted_proxies):
        return peer
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    for hop in reversed(hops):
        if not _in(hop, trusted_proxies):
            return hop
    return hops[0] if hops else peer
