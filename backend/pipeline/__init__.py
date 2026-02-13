"""
Pipeline module for memory-augmented chat system.

Provides inlet (context enrichment) and outlet (memory formation) pipelines.
"""

from pipeline.inlet import enrich_request, format_context
from pipeline.outlet import process_response

__all__ = [
    "enrich_request",
    "format_context",
    "process_response"
]
