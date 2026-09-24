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
- strict provider-to-domain parsing

It does not contain Streamlit, caching, rate limiting,
prioritization, or persistent telemetry.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass

import openai
from openai import OpenAI

from ..audit_modes import get_depth_config
from ..models import AuditImage, AuditMode, AuditRequest
from ..opportunity import Opportunity
from ..prompts import build_audit_prompt
from .base import (
    AuditProvider,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderRefusalError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderTransientError,
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
    """

    model_name: str
    request_timeout_seconds: float = 45.0
    max_output_tokens: int = 3000
    max_retries: int = 0

    def __post_init__(self) -> None:
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
            isinstance(self.max_output_tokens, bool)
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
            isinstance(self.max_retries, bool)
            or not isinstance(
                self.max_retries,
                int,
            )
            or self.max_retries < 0
        ):
            raise ValueError(
                "max_retries cannot be negative."
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

    This schema mirrors providers/schema.py so malformed
    provider output is rejected twice:

    1. generation-time structured output constraints
    2. provider-neutral runtime parsing
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
    config_version = "2"

    def __init__(
        self,
        *,
        config: OpenAIProviderConfig,
        api_key: str | None = None,
    ) -> None:

        self.config = config
        self.model_name = config.model_name

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
        Build image inputs for the Responses API.

        Product:
        - prepared full scene

        Expanded:
        - prepared full scene
        - prepared target crop
        """

        image_inputs = [
            {
                "role": "full_scene",
                "image": request.image,
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
                    "image": request.target_crop,
                }
            )

        return image_inputs

    def _build_response_input(
        self,
        request: AuditRequest,
    ) -> list[dict]:
        """
        Build one Responses API user message containing
        the audit prompt and all required images.
        """

        content = [
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

            image = image_input[
                "image"
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
                    "image_url": _image_data_url(
                        image
                    ),
                    "detail": "auto",
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

        for output_item in response.output:
            if output_item.type != "message":
                continue

            for content_item in output_item.content:
                if content_item.type == "refusal":
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
    ) -> list[Opportunity]:
        """
        Execute one OpenAI Shelf Audit request.
        """

        max_opportunities = self._candidate_limit(
            request
        )

        schema = _build_response_schema(
            max_opportunities=max_opportunities
        )

        try:
            response = self.client.responses.create(
                model=self.model_name,
                input=self._build_response_input(
                    request
                ),
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

        except openai.AuthenticationError as exc:
            raise ProviderAuthenticationError(
                "OpenAI authentication failed."
            ) from exc

        except openai.PermissionDeniedError as exc:
            raise ProviderAuthenticationError(
                "OpenAI access was denied."
            ) from exc

        except openai.APITimeoutError as exc:
            raise ProviderTimeoutError(
                "The OpenAI request timed out."
            ) from exc

        except openai.RateLimitError as exc:
            raise ProviderTransientError(
                "OpenAI rate limit reached."
            ) from exc

        except openai.APIConnectionError as exc:
            raise ProviderTransientError(
                "OpenAI could not be reached."
            ) from exc

        except openai.InternalServerError as exc:
            raise ProviderTransientError(
                "OpenAI returned a temporary server error."
            ) from exc

        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise ProviderTransientError(
                    "OpenAI returned a temporary server error."
                ) from exc

            raise ProviderResponseError(
                "OpenAI rejected the audit request."
            ) from exc

        except openai.APIError as exc:
            raise ProviderResponseError(
                "The OpenAI request failed."
            ) from exc

        return self._parse_response(
            response,
            max_opportunities=max_opportunities,
        )