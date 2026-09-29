"""
Regression tests for the strict Shelf Audit provider response schema.

These tests do not call any AI provider or network service.
"""

from __future__ import annotations

import math
import unittest

from shelf_audit.providers.schema import (
    MAX_EVIDENCE_LENGTH,
    MAX_RECOMMENDATION_LENGTH,
    MAX_TITLE_LENGTH,
    ProviderResponseSchemaError,
    parse_provider_response,
)


def _valid_opportunity(
    *,
    criterion_id: str = "stackable_opportunity",
) -> dict:
    return {
        "criterion_id": criterion_id,
        "title": "Use vertical stacking",
        "evidence": "The visible package shape supports stacking.",
        "recommendation": "Test a stacked presentation.",
        "relevance": 0.9,
        "confidence": 0.9,
        "impact": 0.8,
        "actionability": 0.9,
    }


class ShelfAuditSchemaTests(
    unittest.TestCase
):
    def test_valid_response_parses(
        self,
    ) -> None:
        raw = {
            "opportunities": [
                _valid_opportunity()
            ]
        }

        opportunities = parse_provider_response(
            raw,
            max_opportunities=8,
        )

        self.assertEqual(
            len(opportunities),
            1,
        )

        self.assertEqual(
            opportunities[0].criterion_id,
            "stackable_opportunity",
        )

    def test_valid_empty_response_succeeds(
        self,
    ) -> None:
        opportunities = parse_provider_response(
            {
                "opportunities": []
            },
            max_opportunities=8,
        )

        self.assertEqual(
            opportunities,
            [],
        )

    def test_missing_top_level_field_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {},
                max_opportunities=8,
            )

    def test_extra_top_level_field_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {
                    "opportunities": [],
                    "extra": "nope",
                },
                max_opportunities=8,
            )

    def test_missing_opportunity_field_is_rejected(
        self,
    ) -> None:
        opportunity = _valid_opportunity()

        del opportunity[
            "recommendation"
        ]

        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {
                    "opportunities": [
                        opportunity
                    ]
                },
                max_opportunities=8,
            )

    def test_extra_opportunity_field_is_rejected(
        self,
    ) -> None:
        opportunity = _valid_opportunity()

        opportunity[
            "priority_score"
        ] = 0.99

        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {
                    "opportunities": [
                        opportunity
                    ]
                },
                max_opportunities=8,
            )

    def test_boolean_score_is_rejected(
        self,
    ) -> None:
        opportunity = _valid_opportunity()

        opportunity[
            "confidence"
        ] = True

        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {
                    "opportunities": [
                        opportunity
                    ]
                },
                max_opportunities=8,
            )

    def test_nan_score_is_rejected(
        self,
    ) -> None:
        opportunity = _valid_opportunity()

        opportunity[
            "confidence"
        ] = math.nan

        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {
                    "opportunities": [
                        opportunity
                    ]
                },
                max_opportunities=8,
            )

    def test_infinite_score_is_rejected(
        self,
    ) -> None:
        opportunity = _valid_opportunity()

        opportunity[
            "confidence"
        ] = math.inf

        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {
                    "opportunities": [
                        opportunity
                    ]
                },
                max_opportunities=8,
            )

    def test_score_below_zero_is_rejected(
        self,
    ) -> None:
        opportunity = _valid_opportunity()

        opportunity[
            "impact"
        ] = -0.01

        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {
                    "opportunities": [
                        opportunity
                    ]
                },
                max_opportunities=8,
            )

    def test_score_above_one_is_rejected(
        self,
    ) -> None:
        opportunity = _valid_opportunity()

        opportunity[
            "impact"
        ] = 1.01

        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {
                    "opportunities": [
                        opportunity
                    ]
                },
                max_opportunities=8,
            )

    def test_blank_text_is_rejected(
        self,
    ) -> None:
        opportunity = _valid_opportunity()

        opportunity[
            "title"
        ] = "   "

        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {
                    "opportunities": [
                        opportunity
                    ]
                },
                max_opportunities=8,
            )

    def test_oversized_title_is_rejected(
        self,
    ) -> None:
        opportunity = _valid_opportunity()

        opportunity[
            "title"
        ] = "x" * (
            MAX_TITLE_LENGTH + 1
        )

        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {
                    "opportunities": [
                        opportunity
                    ]
                },
                max_opportunities=8,
            )

    def test_oversized_evidence_is_rejected(
        self,
    ) -> None:
        opportunity = _valid_opportunity()

        opportunity[
            "evidence"
        ] = "x" * (
            MAX_EVIDENCE_LENGTH + 1
        )

        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {
                    "opportunities": [
                        opportunity
                    ]
                },
                max_opportunities=8,
            )

    def test_oversized_recommendation_is_rejected(
        self,
    ) -> None:
        opportunity = _valid_opportunity()

        opportunity[
            "recommendation"
        ] = "x" * (
            MAX_RECOMMENDATION_LENGTH + 1
        )

        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {
                    "opportunities": [
                        opportunity
                    ]
                },
                max_opportunities=8,
            )

    def test_excess_candidate_count_is_rejected(
        self,
    ) -> None:
        raw = {
            "opportunities": [
                _valid_opportunity(
                    criterion_id=f"criterion_{index}"
                )
                for index in range(3)
            ]
        }

        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                raw,
                max_opportunities=2,
            )

    def test_non_object_response_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                [],
                max_opportunities=8,
            )

    def test_non_list_opportunities_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ProviderResponseSchemaError
        ):
            parse_provider_response(
                {
                    "opportunities": {}
                },
                max_opportunities=8,
            )

    def test_invalid_max_opportunities_is_rejected(
        self,
    ) -> None:
        with self.assertRaises(
            ValueError
        ):
            parse_provider_response(
                {
                    "opportunities": []
                },
                max_opportunities=True,
            )


if __name__ == "__main__":
    unittest.main()