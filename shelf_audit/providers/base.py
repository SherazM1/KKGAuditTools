"""
Base provider interface.

All real or mock AI providers should follow this contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import AuditRequest
from ..opportunity import Opportunity


# ---------------------------------------------------------
# Provider errors
# ---------------------------------------------------------


class ProviderError(RuntimeError):
    """
    Base error for provider-specific failures.
    """
    def __init__(self, message: str, *, provider_called: bool = False, attempt_count: int = 0) -> None:
        super().__init__(message)
        self.provider_called = provider_called
        self.attempt_count = attempt_count



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
# Provider result metadata
# ---------------------------------------------------------


@dataclass(frozen=True)
class ProviderUsage:
    """
    Usage metadata reported or calculated for one provider execution.

    Mock and other nonbillable providers should leave
    provider_called=False and token fields unset.
    """

    provider_called: bool = False

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    estimated_cost: float | None = None

    provider_request_id: str | None = None

    attempt_count: int = 0


@dataclass(frozen=True)
class ProviderAnalysisResult:
    """
    Complete provider result returned to audit orchestration.
    """

    opportunities: list[Opportunity]
    usage: ProviderUsage


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
    config_version: str = "3"

    @abstractmethod
    def analyze(
        self,
        request: AuditRequest,
    ) -> ProviderAnalysisResult:
        """
        Analyze one audit request.

        Provider implementations are responsible for:
        - prompt construction
        - image attachment preparation
        - API execution
        - strict response parsing
        - provider-specific error mapping
        - provider usage metadata

        Application-level validation, prioritization, caching,
        rate limiting, and telemetry storage remain outside
        the provider.
        """

        raise NotImplementedError