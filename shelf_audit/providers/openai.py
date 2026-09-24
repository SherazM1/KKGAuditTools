"""
OpenAI provider adapter for Shelf Audit.

This module owns OpenAI-specific audit preparation and will later
own API execution, structured-output handling, and provider error mapping.

It does not contain Streamlit, caching, rate limiting, or prioritization.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from ..audit_modes import get_depth_config
from ..models import AuditImage, AuditMode, AuditRequest
from ..opportunity import Opportunity
from ..prompts import build_audit_prompt
from .base import (
    AuditProvider,
    ProviderConfigurationError,
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
        if not self.model_name.strip():
            raise ValueError(
                "model_name cannot be empty."
            )

        if self.request_timeout_seconds <= 0:
            raise ValueError(
                "request_timeout_seconds must be greater than zero."
            )

        if self.max_output_tokens < 1:
            raise ValueError(
                "max_output_tokens must be at least 1."
            )

        if self.max_retries < 0:
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


class OpenAIAuditProvider(AuditProvider):
    """
    OpenAI implementation of the Shelf Audit provider contract.

    Network execution is intentionally added in a later step.
    """

    name = "openai"
    config_version = "1"

    def __init__(
        self,
        *,
        config: OpenAIProviderConfig,
    ) -> None:

        self.config = config
        self.model_name = config.model_name

    def _build_prompt(
        self,
        request: AuditRequest,
    ) -> str:
        """
        Build the model-facing Shelf Audit prompt.
        """

        return build_audit_prompt(
            criteria=list(request.criteria),
            mode=request.mode,
            depth=request.depth,
            target_region=request.target_region,
        )

    def _build_image_inputs(
        self,
        request: AuditRequest,
    ) -> list[dict]:
        """
        Build provider-neutral descriptions of the images that
        should eventually be attached to the OpenAI request.

        Product mode:
        - prepared full image

        Expanded mode:
        - prepared full scene
        - detailed target crop
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

    def analyze(
        self,
        request: AuditRequest,
    ) -> list[Opportunity]:
        """
        Execute one OpenAI Shelf Audit request.

        Actual API execution will be added after the adapter
        boundary and target-crop handoff are finalized.
        """

        raise ProviderConfigurationError(
            "OpenAI network execution has not been wired yet."
        )