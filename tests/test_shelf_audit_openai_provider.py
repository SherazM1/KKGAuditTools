"""
Regression tests for the Shelf Audit OpenAI provider adapter.

These tests use an injected fake client.

They do not:
- require an API key
- contact OpenAI
- make network requests
- spend model tokens
"""

from __future__ import annotations

import io
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import shelf_audit.providers.openai as openai_provider_module

from shelf_audit.audit_modes import AuditDepth
from shelf_audit.image_utils import build_audit_image
from shelf_audit.models import (
    AuditMode,
    AuditRequest,
    TargetRegion,
)
from shelf_audit.providers.base import (
    ProviderAnalysisResult,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderRefusalError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderTransientError,
)
from shelf_audit.providers.openai import (
    OpenAIAuditProvider,
    OpenAIProviderConfig,
)


# ---------------------------------------------------------
# Test helpers
# ---------------------------------------------------------


def _make_image():
    buffer = io.BytesIO()

    image = Image.new(
        "RGB",
        (100, 100),
        "white",
    )

    image.save(
        buffer,
        format="PNG",
    )

    return build_audit_image(
        buffer.getvalue(),
        filename="test.png",
        media_type="image/png",
        source="test",
    )


def _criterion():
    return {
        "id": "test_criterion",
        "category": "test",
        "applies_when": "Visible evidence supports it.",
        "check": "Check the visible execution.",
        "suggestion": "Improve the visible execution.",
    }


def _product_request(
    *,
    depth: AuditDepth = AuditDepth.QUICK,
) -> AuditRequest:
    return AuditRequest(
        image=_make_image(),
        criteria=(
            _criterion(),
        ),
        mode=AuditMode.PRODUCT,
        depth=depth,
    )


def _expanded_request() -> AuditRequest:
    return AuditRequest(
        image=_make_image(),
        criteria=(
            _criterion(),
        ),
        mode=AuditMode.EXPANDED,
        depth=AuditDepth.QUICK,
        target_region=TargetRegion(
            x=0.1,
            y=0.1,
            width=0.5,
            height=0.5,
        ),
        target_crop=_make_image(),
    )


def _valid_output_text() -> str:
    return json.dumps(
        {
            "opportunities": [
                {
                    "criterion_id": "test_criterion",
                    "title": "Improve presentation",
                    "evidence": "Visible test evidence.",
                    "recommendation": "Take a test action.",
                    "relevance": 0.90,
                    "confidence": 0.90,
                    "impact": 0.90,
                    "actionability": 0.90,
                }
            ]
        }
    )


def _fake_response(
    *,
    output_text: str | None = None,
    status: str = "completed",
    error=None,
    output=None,
    input_tokens: int = 1000,
    output_tokens: int = 200,
    total_tokens: int = 1200,
):
    if output_text is None:
        output_text = _valid_output_text()

    if output is None:
        output = []

    return SimpleNamespace(
        output_text=output_text,
        status=status,
        error=error,
        output=output,
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        ),
        _request_id="req_test_123",
        id="resp_test_123",
    )


class FakeResponses:
    def __init__(
        self,
        *,
        response=None,
        error=None,
    ):
        self.response = response
        self.error = error
        self.calls = []

    def create(
        self,
        **kwargs,
    ):
        self.calls.append(
            kwargs
        )

        if self.error is not None:
            raise self.error

        return self.response


class FakeClient:
    def __init__(
        self,
        *,
        response=None,
        error=None,
    ):
        self.responses = FakeResponses(
            response=response,
            error=error,
        )


def _provider_with_fake_client(
    *,
    response=None,
    error=None,
    input_price=None,
    output_price=None,
):
    return OpenAIAuditProvider(
        config=OpenAIProviderConfig(
            model_name="test-model",
            network_enabled=True,
            max_retries=0,
            input_cost_per_million_tokens=input_price,
            output_cost_per_million_tokens=output_price,
        ),
        client=FakeClient(
            response=response,
            error=error,
        ),
    )


# ---------------------------------------------------------
# Tests
# ---------------------------------------------------------


class OpenAIProviderBoundaryTests(
    unittest.TestCase
):

    # -----------------------------------------------------
    # Configuration
    # -----------------------------------------------------

    def test_reasoning_and_image_detail_defaults(self) -> None:
        config = OpenAIProviderConfig(model_name="test-model")
        self.assertEqual(config.reasoning_effort, "low")
        self.assertEqual(config.image_detail, "high")
        self.assertIs(config.network_enabled, False)
        self.assertEqual(config.max_retries, 0)

    def test_allowed_reasoning_efforts(self) -> None:
        for effort in ("low", "medium", "high", "xhigh", "max"):
            with self.subTest(effort=effort):
                config = OpenAIProviderConfig(model_name="test-model", reasoning_effort=effort)
                self.assertEqual(config.reasoning_effort, effort)

    def test_invalid_reasoning_efforts(self) -> None:
        for effort in ("unsupported", "LOW", " low", "low ", "", None, 1, True, []):
            with self.subTest(effort=effort):
                with self.assertRaises(ValueError):
                    OpenAIProviderConfig(model_name="test-model", reasoning_effort=effort)

    def test_allowed_image_details(self) -> None:
        for detail in ("low", "high", "original", "auto"):
            with self.subTest(detail=detail):
                config = OpenAIProviderConfig(model_name="test-model", image_detail=detail)
                self.assertEqual(config.image_detail, detail)

    def test_invalid_image_details(self) -> None:
        for detail in ("unsupported", "HIGH", " high", "high ", "", None, 1, True, []):
            with self.subTest(detail=detail):
                with self.assertRaises(ValueError):
                    OpenAIProviderConfig(model_name="test-model", image_detail=detail)

    def test_default_request_reasoning_and_product_image_detail(self) -> None:
        client = FakeClient(response=_fake_response())
        provider = OpenAIAuditProvider(
            config=OpenAIProviderConfig(model_name="test-model", network_enabled=True),
            client=client,
        )
        provider.analyze(_product_request())
        self.assertEqual(len(client.responses.calls), 1)
        call = client.responses.calls[0]
        self.assertEqual(call["reasoning"], {"effort": "low"})
        images = [item for item in call["input"][0]["content"]
                  if item["type"] == "input_image"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["detail"], "high")

    def test_custom_reasoning_and_image_detail_propagate(self) -> None:
        for request_factory in (_product_request, _expanded_request):
            with self.subTest(mode=request_factory.__name__):
                client = FakeClient(response=_fake_response())
                provider = OpenAIAuditProvider(
                    config=OpenAIProviderConfig(
                        model_name="test-model",
                        network_enabled=True,
                        reasoning_effort="medium",
                        image_detail="original",
                    ),
                    client=client,
                )
                provider.analyze(request_factory())
                self.assertEqual(len(client.responses.calls), 1)
                call = client.responses.calls[0]
                self.assertEqual(call["reasoning"], {"effort": "medium"})
                images = [item for item in call["input"][0]["content"]
                          if item["type"] == "input_image"]
                self.assertEqual(len(images), 2 if request_factory is _expanded_request else 1)
                self.assertEqual([item["detail"] for item in images],
                                 ["original"] * len(images))

    def test_config_accepts_valid_values(
        self,
    ) -> None:
        config = OpenAIProviderConfig(
            model_name="test-model",
            request_timeout_seconds=30,
            max_output_tokens=1000,
            max_retries=0,
        )

        self.assertEqual(
            config.model_name,
            "test-model",
        )

        self.assertEqual(
            config.max_retries,
            0,
        )

        self.assertFalse(
            config.network_enabled
        )

    def test_empty_model_name_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            OpenAIProviderConfig(
                model_name="",
            )

    def test_invalid_timeout_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            OpenAIProviderConfig(
                model_name="test-model",
                request_timeout_seconds=0,
            )

    def test_boolean_timeout_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            OpenAIProviderConfig(
                model_name="test-model",
                request_timeout_seconds=True,
            )

    def test_invalid_output_token_limit_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            OpenAIProviderConfig(
                model_name="test-model",
                max_output_tokens=0,
            )

    def test_boolean_output_token_limit_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            OpenAIProviderConfig(
                model_name="test-model",
                max_output_tokens=True,
            )

    def test_negative_retry_count_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            OpenAIProviderConfig(
                model_name="test-model",
                max_retries=-1,
            )

    def test_boolean_retry_count_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            OpenAIProviderConfig(
                model_name="test-model",
                max_retries=True,
            )

    # -----------------------------------------------------
    # Image handoff
    # -----------------------------------------------------

    def test_product_mode_uses_one_image(
        self,
    ) -> None:
        provider = OpenAIAuditProvider(
            config=OpenAIProviderConfig(
                model_name="test-model",
            )
        )

        images = provider._build_image_inputs(
            _product_request()
        )

        self.assertEqual(
            len(images),
            1,
        )

        self.assertEqual(
            images[0]["role"],
            "full_scene",
        )

    def test_expanded_mode_uses_full_scene_and_target_crop(
        self,
    ) -> None:
        provider = OpenAIAuditProvider(
            config=OpenAIProviderConfig(
                model_name="test-model",
            )
        )

        images = provider._build_image_inputs(
            _expanded_request()
        )

        self.assertEqual(
            len(images),
            2,
        )

        self.assertEqual(
            images[0]["role"],
            "full_scene",
        )

        self.assertEqual(
            images[1]["role"],
            "target_crop",
        )

    def test_expanded_without_crop_is_rejected(
        self,
    ) -> None:
        provider = OpenAIAuditProvider(
            config=OpenAIProviderConfig(
                model_name="test-model",
            )
        )

        request = AuditRequest(
            image=_make_image(),
            criteria=(
                _criterion(),
            ),
            mode=AuditMode.EXPANDED,
            depth=AuditDepth.QUICK,
            target_region=TargetRegion(
                x=0.1,
                y=0.1,
                width=0.5,
                height=0.5,
            ),
            target_crop=None,
        )

        with self.assertRaises(
            ProviderConfigurationError
        ):
            provider._build_image_inputs(
                request
            )

    # -----------------------------------------------------
    # Candidate limits
    # -----------------------------------------------------

    def test_quick_candidate_limit_matches_mode_config(
        self,
    ) -> None:
        provider = OpenAIAuditProvider(
            config=OpenAIProviderConfig(
                model_name="test-model",
            )
        )

        self.assertEqual(
            provider._candidate_limit(
                _product_request(
                    depth=AuditDepth.QUICK,
                )
            ),
            8,
        )

    def test_deep_candidate_limit_matches_mode_config(
        self,
    ) -> None:
        provider = OpenAIAuditProvider(
            config=OpenAIProviderConfig(
                model_name="test-model",
            )
        )

        self.assertEqual(
            provider._candidate_limit(
                _product_request(
                    depth=AuditDepth.DEEP,
                )
            ),
            14,
        )

    # -----------------------------------------------------
    # Network safety
    # -----------------------------------------------------

    def test_network_execution_defaults_disabled(
        self,
    ) -> None:
        provider = OpenAIAuditProvider(
            config=OpenAIProviderConfig(
                model_name="test-model",
            )
        )

        with self.assertRaises(
            ProviderConfigurationError
        ):
            provider.analyze(
                _product_request()
            )

    # -----------------------------------------------------
    # Successful fake provider execution
    # -----------------------------------------------------

    def test_fake_success_returns_analysis_result(
        self,
    ) -> None:
        response = _fake_response()

        provider = _provider_with_fake_client(
            response=response
        )

        result = provider.analyze(
            _product_request()
        )

        self.assertIsInstance(
            result,
            ProviderAnalysisResult,
        )

        self.assertEqual(
            len(result.opportunities),
            1,
        )

        self.assertEqual(
            result.opportunities[0].criterion_id,
            "test_criterion",
        )

    def test_fake_success_captures_usage(
        self,
    ) -> None:
        provider = _provider_with_fake_client(
            response=_fake_response(
                input_tokens=1000,
                output_tokens=200,
                total_tokens=1200,
            )
        )

        result = provider.analyze(
            _product_request()
        )

        self.assertTrue(
            result.usage.provider_called
        )

        self.assertEqual(
            result.usage.input_tokens,
            1000,
        )

        self.assertEqual(
            result.usage.output_tokens,
            200,
        )

        self.assertEqual(
            result.usage.total_tokens,
            1200,
        )

        self.assertEqual(
            result.usage.provider_request_id,
            "req_test_123",
        )

        self.assertEqual(
            result.usage.attempt_count,
            1,
        )

    def test_cost_estimate_uses_configured_prices(
        self,
    ) -> None:
        provider = _provider_with_fake_client(
            response=_fake_response(
                input_tokens=1_000_000,
                output_tokens=1_000_000,
                total_tokens=2_000_000,
            ),
            input_price=2.0,
            output_price=8.0,
        )

        result = provider.analyze(
            _product_request()
        )

        self.assertAlmostEqual(
            result.usage.estimated_cost,
            10.0,
        )

    def test_request_uses_model_and_output_limit(
        self,
    ) -> None:
        response = _fake_response()

        fake_client = FakeClient(
            response=response
        )

        provider = OpenAIAuditProvider(
            config=OpenAIProviderConfig(
                model_name="test-model",
                network_enabled=True,
                max_output_tokens=777,
                max_retries=0,
            ),
            client=fake_client,
        )

        provider.analyze(
            _product_request()
        )

        self.assertEqual(
            len(fake_client.responses.calls),
            1,
        )

        call = fake_client.responses.calls[0]

        self.assertEqual(
            call["model"],
            "test-model",
        )

        self.assertEqual(
            call["max_output_tokens"],
            777,
        )

        self.assertFalse(
            call["store"]
        )

    def test_request_uses_strict_json_schema(
        self,
    ) -> None:
        fake_client = FakeClient(
            response=_fake_response()
        )

        provider = OpenAIAuditProvider(
            config=OpenAIProviderConfig(
                model_name="test-model",
                network_enabled=True,
            ),
            client=fake_client,
        )

        provider.analyze(
            _product_request()
        )

        call = fake_client.responses.calls[0]

        response_format = (
            call["text"]["format"]
        )

        self.assertEqual(
            response_format["type"],
            "json_schema",
        )

        self.assertTrue(
            response_format["strict"]
        )

        self.assertEqual(
            response_format["schema"][
                "properties"
            ][
                "opportunities"
            ][
                "maxItems"
            ],
            8,
        )

    def test_expanded_request_sends_two_images(
        self,
    ) -> None:
        fake_client = FakeClient(
            response=_fake_response()
        )

        provider = OpenAIAuditProvider(
            config=OpenAIProviderConfig(
                model_name="test-model",
                network_enabled=True,
            ),
            client=fake_client,
        )

        provider.analyze(
            _expanded_request()
        )

        call = fake_client.responses.calls[0]

        content = (
            call["input"][0]["content"]
        )

        image_items = [
            item
            for item in content
            if item["type"] == "input_image"
        ]

        self.assertEqual(
            len(image_items),
            2,
        )

    # -----------------------------------------------------
    # Response failures
    # -----------------------------------------------------

    def test_malformed_json_is_rejected(
        self,
    ) -> None:
        provider = _provider_with_fake_client(
            response=_fake_response(
                output_text="{not valid json"
            )
        )

        with self.assertRaises(
            ProviderResponseError
        ):
            provider.analyze(
                _product_request()
            )

    def test_schema_mismatch_is_rejected(
        self,
    ) -> None:
        provider = _provider_with_fake_client(
            response=_fake_response(
                output_text=json.dumps(
                    {
                        "wrong_field": [],
                    }
                )
            )
        )

        with self.assertRaises(
            ProviderResponseError
        ):
            provider.analyze(
                _product_request()
            )

    def test_incomplete_response_is_rejected(
        self,
    ) -> None:
        provider = _provider_with_fake_client(
            response=_fake_response(
                status="incomplete"
            )
        )

        with self.assertRaises(
            ProviderResponseError
        ):
            provider.analyze(
                _product_request()
            )

    def test_refusal_is_rejected(
        self,
    ) -> None:
        refusal_item = SimpleNamespace(
            type="refusal",
        )

        message = SimpleNamespace(
            type="message",
            content=[
                refusal_item,
            ],
        )

        provider = _provider_with_fake_client(
            response=_fake_response(
                output=[
                    message,
                ]
            )
        )

        with self.assertRaises(
            ProviderRefusalError
        ):
            provider.analyze(
                _product_request()
            )

    # -----------------------------------------------------
    # Provider error mapping
    # -----------------------------------------------------

    def test_authentication_error_is_mapped(
        self,
    ) -> None:
        class FakeAuthenticationError(
            Exception
        ):
            pass

        provider = _provider_with_fake_client(
            error=FakeAuthenticationError()
        )

        with patch.object(
            openai_provider_module.openai,
            "AuthenticationError",
            FakeAuthenticationError,
        ):
            with self.assertRaises(
                ProviderAuthenticationError
            ) as caught:
                provider.analyze(
                    _product_request()
                )

        self.assertIs(caught.exception.provider_called, True)
        self.assertEqual(caught.exception.attempt_count, 1)

    def test_timeout_error_is_mapped(
        self,
    ) -> None:
        class FakeTimeoutError(
            Exception
        ):
            pass

        provider = _provider_with_fake_client(
            error=FakeTimeoutError()
        )

        with patch.object(
            openai_provider_module.openai,
            "APITimeoutError",
            FakeTimeoutError,
        ):
            with self.assertRaises(
                ProviderTimeoutError
            ) as caught:
                provider.analyze(
                    _product_request()
                )

        self.assertIs(caught.exception.provider_called, True)
        self.assertEqual(caught.exception.attempt_count, 1)

    def test_rate_limit_error_is_mapped(
        self,
    ) -> None:
        class FakeRateLimitError(
            Exception
        ):
            pass

        provider = _provider_with_fake_client(
            error=FakeRateLimitError()
        )

        with patch.object(
            openai_provider_module.openai,
            "RateLimitError",
            FakeRateLimitError,
        ):
            with self.assertRaises(
                ProviderTransientError
            ):
                provider.analyze(
                    _product_request()
                )

    def test_connection_error_is_mapped(
        self,
    ) -> None:
        class FakeConnectionError(
            Exception
        ):
            pass

        provider = _provider_with_fake_client(
            error=FakeConnectionError()
        )

        with patch.object(
            openai_provider_module.openai,
            "APIConnectionError",
            FakeConnectionError,
        ):
            with self.assertRaises(
                ProviderTransientError
            ):
                provider.analyze(
                    _product_request()
                )


if __name__ == "__main__":
    unittest.main()