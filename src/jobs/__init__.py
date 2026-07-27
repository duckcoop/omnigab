"""Job sources and multi-board search."""

from .sources import (
    API,
    SCRAPE,
    HANDOFF,
    JobSource,
    AmazonJobs,
    GreenhouseBoard,
    LeverBoard,
    RemoteOK,
    BrowserHandoff,
    LINKEDIN,
    HANDSHAKE,
    INDEED_HANDOFF,
    default_registry,
    search_many,
    posting,
)

__all__ = [
    "API", "SCRAPE", "HANDOFF",
    "JobSource", "AmazonJobs", "GreenhouseBoard", "LeverBoard", "RemoteOK",
    "BrowserHandoff", "LINKEDIN", "HANDSHAKE", "INDEED_HANDOFF",
    "default_registry", "search_many", "posting",
]
