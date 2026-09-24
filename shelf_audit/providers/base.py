"""
Base provider interface.

All real or mock AI providers should follow this contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import AuditRequest
from ..opportunity import Opportunity


# ---------------------------------------------------------
# Provider errors
# ---------------------------------------------------------


class ProviderError(RuntimeError):
    """
    Base error for provider-specific failures.
    """


class ProviderConfigurationError(ProviderError):
    """
    Raised when provider configuration is missing or invalid.
    """


class ProviderAuthenticationError(ProviderError):
    """
    Raised when provider authentication fails.
    """


class ProviderTimeoutError(ProviderError):
    """
    Raised when a provider request exceeds its allowed time.
    """


class ProviderTransientError(ProviderError):
    """
    Raised for temporary provider failures that may be retryable.
    """


class ProviderRefusalError(ProviderError):
    """
    Raised when the model explicitly refuses the audit request.
    """


class ProviderResponseError(ProviderError):
    """
    Raised when the provider returns malformed, incomplete,
    or otherwise unusable output.
    """


# ---------------------------------------------------------
# Provider interface
# ---------------------------------------------------------


class AuditProvider(ABC):
    """
    Interface all audit providers must implement.
    """

    name: str = "base"
    model_name: str | None = None

    # Nonsecret revision for provider behavior/configuration.
    # Increment when provider behavior changes in a way that
    # should invalidate cached audit results.
    config_version: str = "1"

    @abstractmethod
    def analyze(
        self,
        request: AuditRequest,
    ) -> list[Opportunity]:
        """
        Analyze one audit request and return candidate opportunities.

        Provider implementations are responsible for:
        - prompt construction
        - image attachment preparation
        - API execution
        - strict response parsing
        - provider-specific error mapping

        Application-level validation, prioritization, caching,
        and rate limiting remain outside the provider.
        """

        raise NotImplementedError