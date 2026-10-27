"""One module per crawled site."""

from types import ModuleType

from animanga.crawler.sites import ann, mangaupdates

SITES: dict[str, ModuleType] = {m.NAME: m for m in (ann, mangaupdates)}
