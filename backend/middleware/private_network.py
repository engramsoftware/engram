"""
Private network middleware — restricts API access to LAN and VPN clients only.

Rejects any request whose source IP is not in a private/reserved range.
This is the primary security boundary: even if CORS is misconfigured or
bypassed, the middleware blocks requests from the public internet.

Private ranges accepted (RFC 1918 + RFC 4193 + loopback + link-local):
  - 10.0.0.0/8        (Class A private)
  - 172.16.0.0/12     (Class B private)
  - 192.168.0.0/16    (Class C private — typical home/office LAN)
  - 127.0.0.0/8       (loopback / localhost)
  - ::1               (IPv6 loopback)
  - fe80::/10         (IPv6 link-local)
  - fc00::/7          (IPv6 unique local — VPN)
  - 100.64.0.0/10     (CGNAT / Tailscale VPN range)

Additional allowed CIDRs can be configured via ALLOWED_NETWORKS in .env
(comma-separated, e.g. "10.8.0.0/24,100.64.0.0/10").
"""

import logging
import ipaddress
from typing import List, Set

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config import get_settings

logger = logging.getLogger(__name__)

# Pre-built set of private/reserved networks
_PRIVATE_NETWORKS: List[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    # IPv4 private ranges
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("127.0.0.0/8"),
    # CGNAT range used by Tailscale, ZeroTier, and some VPNs
    ipaddress.IPv4Network("100.64.0.0/10"),
    # IPv6 private/local ranges
    ipaddress.IPv6Network("::1/128"),
    ipaddress.IPv6Network("fe80::/10"),
    ipaddress.IPv6Network("fc00::/7"),
]

# Paths that are allowed without network restriction (health check only)
_UNRESTRICTED_PATHS: Set[str] = {
    "/health",
}


def _parse_extra_networks(csv: str) -> List[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse comma-separated CIDR strings into network objects.

    Args:
        csv: Comma-separated CIDR notation strings (e.g. "10.8.0.0/24,100.64.0.0/10").

    Returns:
        List of parsed network objects. Invalid entries are logged and skipped.
    """
    networks = []
    for cidr in csv.split(","):
        cidr = cidr.strip()
        if not cidr:
            continue
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning(f"Invalid CIDR in ALLOWED_NETWORKS: '{cidr}' — skipping")
    return networks


def _is_private_ip(ip_str: str, extra_networks: list) -> bool:
    """Check if an IP address belongs to a private/allowed network.

    Args:
        ip_str: The IP address string to check.
        extra_networks: Additional allowed networks from config.

    Returns:
        True if the IP is in a private/allowed range, False otherwise.
    """
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        logger.warning(f"Could not parse IP address: '{ip_str}' — blocking")
        return False

    # Check built-in private ranges
    for network in _PRIVATE_NETWORKS:
        if addr in network:
            return True

    # Check user-configured extra networks
    for network in extra_networks:
        if addr in network:
            return True

    return False


class PrivateNetworkMiddleware(BaseHTTPMiddleware):
    """Middleware that blocks requests from non-private IP addresses.

    Extracts the client IP from the request (respecting X-Forwarded-For if
    behind a reverse proxy on the same LAN), then checks it against the
    allowed private network ranges.

    Attributes:
        extra_networks: Additional allowed CIDRs from ALLOWED_NETWORKS env var.
    """

    def __init__(self, app, allowed_networks_csv: str = ""):
        super().__init__(app)
        self.extra_networks = _parse_extra_networks(allowed_networks_csv)
        if self.extra_networks:
            logger.info(
                f"PrivateNetworkMiddleware: {len(self.extra_networks)} extra "
                f"network(s) allowed: {[str(n) for n in self.extra_networks]}"
            )
        logger.info("PrivateNetworkMiddleware active — only LAN/VPN clients accepted")

    async def dispatch(self, request: Request, call_next) -> dict:
        """Check client IP and block if not from a private network.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware/handler in the chain.

        Returns:
            The response from the next handler, or a 403 JSON error.
        """
        # Allow health check without network restriction
        if request.url.path in _UNRESTRICTED_PATHS:
            return await call_next(request)

        # Get client IP — check X-Forwarded-For first (reverse proxy on LAN),
        # then fall back to the direct connection IP.
        client_ip = None
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # X-Forwarded-For can be "client, proxy1, proxy2" — take the first
            client_ip = forwarded.split(",")[0].strip()
        if not client_ip and request.client:
            client_ip = request.client.host

        if not client_ip:
            logger.warning("No client IP detected — blocking request")
            return JSONResponse(
                status_code=403,
                content={"detail": "Access denied — could not determine client IP"},
            )

        if not _is_private_ip(client_ip, self.extra_networks):
            logger.warning(
                f"Blocked request from external IP {client_ip} to {request.url.path}"
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "Access denied — this service is only available on the local network"},
            )

        return await call_next(request)
