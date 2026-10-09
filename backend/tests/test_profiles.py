from __future__ import annotations

import json

import pytest

from app.profiles import PROFILES, ProfileId, installed_trellis_qualities, trellis_qualities_for


@pytest.mark.parametrize("invalid_texture_resolution", [None, "1024", True, {}])
def test_invalid_texture_resolution_is_skipped_before_numeric_comparison(tmp_path, invalid_texture_resolution) -> None:
    profile = PROFILES[ProfileId.GB12]
    registry = tmp_path / "engine-profile.json"
    registry.write_text(
        json.dumps(
            {
                "profile": profile.id.value,
                "trellis": {
                    "qualities": [
                        {
                            "id": "invalid",
                            "resolution": 512,
                            "atlas": 2048,
                            "texture_resolution": invalid_texture_resolution,
                        },
                        {
                            "id": "balanced",
                            "resolution": 512,
                            "atlas": 2048,
                            "texture_resolution": 1024,
                        },
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    qualities = installed_trellis_qualities(profile, registry)

    assert [quality["id"] for quality in qualities] == ["balanced"]


def test_registry_with_only_invalid_texture_resolution_uses_safe_profile_default(tmp_path) -> None:
    profile = PROFILES[ProfileId.GB12]
    registry = tmp_path / "engine-profile.json"
    registry.write_text(
        json.dumps(
            {
                "profile": profile.id.value,
                "trellis": {
                    "qualities": [
                        {"id": "invalid", "resolution": 512, "atlas": 2048, "texture_resolution": "1024"}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    qualities = installed_trellis_qualities(profile, registry)

    assert qualities == trellis_qualities_for(profile)
