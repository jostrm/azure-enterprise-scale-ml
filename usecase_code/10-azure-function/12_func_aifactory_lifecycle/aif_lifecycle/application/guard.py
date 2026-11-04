"""Self-protection: never act on a scope that contains the Function's own project or the management runner."""

from __future__ import annotations

from collections.abc import Iterable

from ..domain.errors import ProtectedTarget
from ..domain.ids import AnyId, parse_any


class SelfProtection:
    """Configurable deny list of IDs (AIF_SELF_PROJECT_ID plus AIF_PROTECTED_IDS)."""

    def __init__(self, protected: Iterable[str]):
        self._protected = [parse_any(text.strip()) for text in protected if text and text.strip()]

    @property
    def protected(self) -> list[str]:
        return [str(item) for item in self._protected]

    def check(self, target: AnyId) -> None:
        for item in self._protected:
            if target.contains(item):
                raise ProtectedTarget(
                    f"{target} includes the protected {item} (this Function's own scope or the management runner).",
                    extra={"protected": str(item)})
