"""
OpenAI provider adapter for Shelf Audit.

This module owns OpenAI-specific:
- client configuration
- prompt construction
- image attachment preparation
- structured response schema
- API execution
- refusal handling
- provider error mapping
- provider usage metadata
- strict provider-to-domain parsing

It does not contain Streamlit, caching, rate limiting,
prioritization, or persistent telemetry.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

import openai
from openai import OpenAI

from ..audit_modes import get_depth_config
from ..models import (
    AuditImage,
    AuditMode,
    AuditRequest,
)
from ..opportunity import Opportunity
from ..prompts import build_audit_prompt
from .base import (
    AuditProvider,
    ProviderAnalysisResult,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderRefusalError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderTransientError,
    ProviderUsage,
)
from .schema import (
    MAX_EVIDENCE_LENGTH,
    MAX_RECOMMENDATION_LENGTH,
    MAX_TITLE_LENGTH,
    ProviderResponseSchemaError,
    parse_provider_response,
)


@dataclass(frozen=True)
class OpenAIProviderConfig:
    """
    Nonsecret configuration for the OpenAI audit provider.

    network_enabled defaults to False so the adapter cannot
    make a live API request until explicitly enabled.
    """

    model_name: str

    request_timeout_seconds: float = 45.0
    max_output_tokens: int = 3000
    max_retries: int = 0

    network_enabled: bool = False

    # Optional pricing configuration.
    # We will populate these only after selecting the exact
    # production/test model and verifying current pricing.
    input_cost_per_million_tokens: float | None = None
    output_cost_per_million_tokens: float | None = None

    reasoning_effort: str = "low"
    image_detail: str = "high"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.reasoning_effort, str)
            or self.reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}
        ):
            raise ValueError("reasoning_effort must be low, medium, high, xhigh, or max.")

        if (
            not isinstance(self.image_detail, str)
            or self.image_detail not in {"low", "high", "original", "auto"}
        ):
            raise ValueError("image_detail must be low, high, original, or auto.")

        if (
            not isinstance(self.model_name, str)
            or not self.model_name.strip()
        ):
            raise ValueError(
                "model_name cannot be empty."
            )

        if (
            isinstance(
                self.request_timeout_seconds,
                bool,
            )
            or not isinstance(
                self.request_timeout_seconds,
                (int, float),
            )
            or self.request_timeout_seconds <= 0
        ):
            raise ValueError(
                "request_timeout_seconds must be greater than zero."
            )

        if (
            isinstance(
                self.max_output_tokens,
                bool,
            )
            or not isinstance(
                self.max_output_tokens,
                int,
            )
            or self.max_output_tokens < 1
        ):
            raise ValueError(
                "max_output_tokens must be at least 1."
            )

        if (
            isinstance(
                self.max_retries,
                bool,
            )
            or not isinstance(
                self.max_retries,
                int,
            )
            or self.max_retries < 0
        ):
            raise ValueError(
                "max_retries cannot be negative."
            )

        if not isinstance(
            self.network_enabled,
            bool,
        ):
            raise ValueError(
                "network_enabled must be a boolean."
            )

        self._validate_optional_price(
            self.input_cost_per_million_tokens,
            "input_cost_per_million_tokens",
        )

        self._validate_optional_price(
            self.output_cost_per_million_tokens,
            "output_cost_per_million_tokens",
        )

    @staticmethod
    def _validate_optional_price(
        value: float | None,
        field_name: str,
    ) -> None:
        if value is None:
            return

        if (
            isinstance(value, bool)
            or not isinstance(
                value,
                (int, float),
            )
            or value < 0
        ):
            raise ValueError(
                f"{field_name} must be a non-negative number "
                "or None."
            )


def _image_data_url(
    image: AuditImage,
) -> str:
    """
    Convert a prepared AuditImage into a Base64 data URL.
    """

    encoded = base64.b64encode(
        image.data
    ).decode(
        "ascii"
    )

    return (
        f"data:{image.media_type};base64,"
        f"{encoded}"
    )


def _build_response_schema(
    *,
    max_opportunities: int,
) -> dict:
    """
    Build the strict JSON schema supplied to OpenAI.

    providers/schema.py still validates the returned data
    independently after generation.
    """

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "opportunities": {
                "type": "array",
                "maxItems": max_opportunities,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "criterion_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 200,
                        },
                        "title": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": MAX_TITLE_LENGTH,
                        },
                        "evidence": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": MAX_EVIDENCE_LENGTH,
                        },
                        "recommendation": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": MAX_RECOMMENDATION_LENGTH,
                        },
                        "relevance": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "impact": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                        "actionability": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                        },
                    },
                    "required": [
                        "criterion_id",
                        "title",
                        "evidence",
                        "recommendation",
                        "relevance",
                        "confidence",
                        "impact",
                        "actionability",
                    ],
                },
            },
        },
        "required": [
            "opportunities",
        ],
    }


class OpenAIAuditProvider(AuditProvider):
    """
    OpenAI implementation of the Shelf Audit provider contract.
    """

    name = "openai"

    # Incremented because provider behavior is changing
    # from scaffold-only to Responses API execution.
    config_version = "3"

    def __init__(
        self,
        *,
        config: OpenAIProviderConfig,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:

        self.config = config
        self.model_name = config.model_name

        # Tests can inject a fake client without any API key.
        if client is not None:
            self.client = client
            return

        # Keep the provider inert until network execution
        # has been explicitly enabled.
        if not config.network_enabled:
            self.client = None
            return

        if (
            not isinstance(api_key, str)
            or not api_key.strip()
        ):
            raise ProviderConfigurationError(
                "An OpenAI API key is required when "
                "network execution is enabled."
            )

        try:
            self.client = OpenAI(
                api_key=api_key,
                timeout=config.request_timeout_seconds,
                max_retries=config.max_retries,
            )

        except Exception as exc:
            raise ProviderConfigurationError(
                "The OpenAI client could not be configured."
            ) from exc

    def _build_prompt(
        self,
        request: AuditRequest,
    ) -> str:
        """
        Build the model-facing Shelf Audit prompt.
        """

        return build_audit_prompt(
            criteria=list(
                request.criteria
            ),
            mode=request.mode,
            depth=request.depth,
            target_region=request.target_region,
        )

    def _build_image_inputs(
        self,
        request: AuditRequest,
    ) -> list[dict]:
        """
        Build image descriptors for the Responses API.

        Product:
        - prepared full scene

        Expanded:
        - prepared full scene
        - prepared target crop
        """

        image_inputs = [
            {
                "role": "full_scene",
                "data_url": _image_data_url(
                    request.image
                ),
            }
        ]

        if request.mode is AuditMode.EXPANDED:
            if request.target_crop is None:
                raise ProviderConfigurationError(
                    "Expanded mode requires a prepared target crop."
                )

            image_inputs.append(
                {
                    "role": "target_crop",
                    "data_url": _image_data_url(
                        request.target_crop
                    ),
                }
            )

        return image_inputs

    def _build_response_input(
        self,
        request: AuditRequest,
    ) -> list[dict]:
        """
        Build one Responses API user message containing
        the audit instructions and required images.
        """

        content: list[dict] = [
            {
                "type": "input_text",
                "text": self._build_prompt(
                    request
                ),
            }
        ]

        for image_input in self._build_image_inputs(
            request
        ):
            role = image_input[
                "role"
            ]

            content.append(
                {
                    "type": "input_text",
                    "text": (
                        f"Image role: {role}"
                    ),
                }
            )

            content.append(
                {
                    "type": "input_image",
                    "image_url": image_input[
                        "data_url"
                    ],
                    "detail": self.config.image_detail,
                }
            )

        return [
            {
                "role": "user",
                "content": content,
            }
        ]

    def _candidate_limit(
        self,
        request: AuditRequest,
    ) -> int:
        """
        Return the configured provider candidate ceiling.
        """

        depth_config = get_depth_config(
            request.depth
        )

        return depth_config.max_candidates

    def _estimate_cost(
        self,
        *,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> float | None:
        """
        Estimate provider cost when pricing has been explicitly
        configured for the selected model.

        No model pricing is hard-coded here.
        """

        input_price = (
            self.config.input_cost_per_million_tokens
        )

        output_price = (
            self.config.output_cost_per_million_tokens
        )

        if (
            input_tokens is None
            or output_tokens is None
            or input_price is None
            or output_price is None
        ):
            return None

        return (
            (
                input_tokens
                / 1_000_000
            )
            * input_price
            + (
                output_tokens
                / 1_000_000
            )
            * output_price
        )

    def _build_usage(
        self,
        response,
    ) -> ProviderUsage:
        """
        Extract provider-reported token usage from one response.
        """

        usage = getattr(
            response,
            "usage",
            None,
        )

        input_tokens = getattr(
            usage,
            "input_tokens",
            None,
        )

        output_tokens = getattr(
            usage,
            "output_tokens",
            None,
        )

        total_tokens = getattr(
            usage,
            "total_tokens",
            None,
        )

        request_id = getattr(
            response,
            "_request_id",
            None,
        )

        if request_id is None:
            request_id = getattr(
                response,
                "id",
                None,
            )

        return ProviderUsage(
            provider_called=True,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost=self._estimate_cost(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            provider_request_id=request_id,
            attempt_count=1,
        )

    def _parse_response(
        self,
        response,
        *,
        max_opportunities: int,
    ) -> list[Opportunity]:
        """
        Convert one OpenAI response into validated
        provider-neutral Opportunity objects.
        """

        output = getattr(
            response,
            "output",
            [],
        )

        for output_item in output:
            if getattr(
                output_item,
                "type",
                None,
            ) != "message":
                continue

            content = getattr(
                output_item,
                "content",
                [],
            )

            for content_item in content:
                if getattr(
                    content_item,
                    "type",
                    None,
                ) == "refusal":
                    raise ProviderRefusalError(
                        "The model refused the audit request."
                    )

        if getattr(
            response,
            "status",
            None,
        ) == "incomplete":
            raise ProviderResponseError(
                "The provider returned an incomplete response."
            )

        if getattr(
            response,
            "error",
            None,
        ) is not None:
            raise ProviderResponseError(
                "The provider returned an unsuccessful response."
            )

        raw_text = getattr(
            response,
            "output_text",
            None,
        )

        if (
            not isinstance(raw_text, str)
            or not raw_text.strip()
        ):
            raise ProviderResponseError(
                "The provider returned no structured output."
            )

        try:
            raw = json.loads(
                raw_text
            )

        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                "The provider returned malformed JSON."
            ) from exc

        try:
            return parse_provider_response(
                raw,
                max_opportunities=max_opportunities,
            )

        except ProviderResponseSchemaError as exc:
            raise ProviderResponseError(
                "The provider response did not match "
                "the Shelf Audit schema."
            ) from exc

    def analyze(
        self,
        request: AuditRequest,
    ) -> ProviderAnalysisResult:
        """
        Execute one OpenAI Shelf Audit request.

        Network execution remains blocked unless
        network_enabled is explicitly True.
        """

        if not self.config.network_enabled:
            raise ProviderConfigurationError(
                "OpenAI network execution is disabled."
            )

        if self.client is None:
            raise ProviderConfigurationError(
                "The OpenAI client is not configured."
            )

        max_opportunities = (
            self._candidate_limit(
                request
            )
        )

        schema = _build_response_schema(
            max_opportunities=max_opportunities
        )

        response_input = self._build_response_input(request)

        try:
            response = (
                self.client.responses.create(
                    model=self.model_name,
                    reasoning={
                        "effort": self.config.reasoning_effort,
                    },
                    input=response_input,
                    max_output_tokens=(
                        self.config.max_output_tokens
                    ),
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "shelf_audit_response",
                            "strict": True,
                            "schema": schema,
                        }
                    },
                    store=False,
                )
            )

        except openai.AuthenticationError as exc:
            raise ProviderAuthenticationError(
                "OpenAI authentication failed.",
                provider_called=True,
                attempt_count=1,
            ) from exc

        except openai.PermissionDeniedError as exc:
            raise ProviderAuthenticationError(
                "OpenAI access was denied.",
                provider_called=True,
                attempt_count=1,
            ) from exc

        except openai.APITimeoutError as exc:
            raise ProviderTimeoutError(
                "The OpenAI request timed out.",
                provider_called=True,
                attempt_count=1,
            ) from exc

        except openai.RateLimitError as exc:
            raise ProviderTransientError(
                "OpenAI rate limit reached.",
                provider_called=True,
                attempt_count=1,
            ) from exc

        except openai.APIConnectionError as exc:
            raise ProviderTransientError(
                "OpenAI could not be reached.",
                provider_called=True,
                attempt_count=1,
            ) from exc

        except openai.InternalServerError as exc:
            raise ProviderTransientError(
                "OpenAI returned a temporary server error.",
                provider_called=True,
                attempt_count=1,
            ) from exc

        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ProviderTransientError(
                    "OpenAI returned a temporary server error.",
                    provider_called=True,
                    attempt_count=1,
                ) from exc

            raise ProviderResponseError(
                "OpenAI rejected the audit request.",
                provider_called=True,
                attempt_count=1,
            ) from exc

        except openai.APIError as exc:
            raise ProviderResponseError(
                "The OpenAI request failed.",
                provider_called=True,
                attempt_count=1,
            ) from exc

        opportunities = self._parse_response(
            response,
            max_opportunities=max_opportunities,
        )

        usage = self._build_usage(
            response
        )

        return ProviderAnalysisResult(
            opportunities=opportunities,
            usage=usage,
        )