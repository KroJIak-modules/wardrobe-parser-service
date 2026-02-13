from collections.abc import Iterable

from app.core.config import settings
from app.parsers.sites.example_parser import ExampleParser
from app.parsers.sites.nofaithstudios_parser import NoFaithStudiosParser


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers = {
            "example": ExampleParser(),
            "nofaithstudios": NoFaithStudiosParser(),
        }

    def enabled_sites(self) -> list[str]:
        raw = [item.strip() for item in settings.enabled_sites.split(",") if item.strip()]
        return [item.lower() for item in raw]

    def iter_parsers(self) -> Iterable[tuple[str, object]]:
        for key in self.enabled_sites():
            parser = self._parsers.get(key)
            if parser:
                yield key, parser

    def get(self, key: str) -> object | None:
        return self._parsers.get(key.lower())
