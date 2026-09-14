"""
Base provider interface.

All real or mock AI providers should follow this contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import AuditRequest
from ..opportunity import Opportunity


class AuditProvider(ABC):
    """
    Interface all audit providers must implement.
    """

    name: str = "base"

    @abstractmethod
    def analyze(
        self,
        request: AuditRequest,
    ) -> list[Opportunity]:
        """
        Analyze one audit request and return candidate opportunities.
        """

        raise NotImplementedError