from __future__ import annotations

from .base import PlatformAdapter
from .email import EmailAdapter
from .facebook import FacebookAdapter
from .google import GoogleAdapter
from .instagram import InstagramAdapter
from .linkedin import LinkedInAdapter
from .threads import ThreadsAdapter
from .whatsapp import WhatsAppAdapter
from .x_platform import XAdapter
from .youtube import YouTubeAdapter

# Specialized adapters first; Google remains the catch-all discovery source.
ADAPTERS: tuple[PlatformAdapter, ...] = (
    LinkedInAdapter(),
    XAdapter(),
    YouTubeAdapter(),
    InstagramAdapter(),
    FacebookAdapter(),
    ThreadsAdapter(),
    WhatsAppAdapter(),
    EmailAdapter(),
    GoogleAdapter(),
)


def get_adapters() -> tuple[PlatformAdapter, ...]:
    return ADAPTERS
