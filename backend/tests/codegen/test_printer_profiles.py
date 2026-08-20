from __future__ import annotations

import math

from services.printer_profiles import DEFAULT_PROFILE_ID, get_profile, list_profiles


def test_printer_profile_ids_are_unique() -> None:
    ids = [profile.id for profile in list_profiles()]
    assert len(ids) == len(set(ids))


def test_every_printer_profile_has_sane_ranges() -> None:
    for profile in list_profiles():
        assert profile.id.strip(), "printer profile id must not be blank"
        assert profile.label.strip(), f"{profile.id}: label must not be blank"

        assert all(
            math.isfinite(dimension) and dimension > 0
            for dimension in profile.bed_size_mm
        ), f"{profile.id}: build volume dimensions must be finite and positive"

        assert math.isfinite(profile.nozzle_mm) and profile.nozzle_mm > 0, (
            f"{profile.id}: nozzle diameter must be finite and positive"
        )
        assert math.isfinite(profile.layer_height_mm) and profile.layer_height_mm > 0, (
            f"{profile.id}: layer height must be finite and positive"
        )
        assert profile.layer_height_mm <= profile.nozzle_mm * 0.8, (
            f"{profile.id}: layer height should not exceed 80% of nozzle diameter"
        )

        assert 0 <= profile.max_unsupported_overhang_deg <= 90, (
            f"{profile.id}: unsupported-overhang angle must be within 0–90 degrees"
        )
        assert 0 <= profile.clean_overhang_deg <= 90, (
            f"{profile.id}: clean-overhang angle must be within 0–90 degrees"
        )
        assert profile.max_unsupported_overhang_deg <= profile.clean_overhang_deg, (
            f"{profile.id}: clean-overhang threshold must not be below the warning threshold"
        )

        assert math.isfinite(profile.min_wall_thickness_mm), (
            f"{profile.id}: minimum wall thickness must be finite"
        )
        assert profile.min_wall_thickness_mm > 0, (
            f"{profile.id}: minimum wall thickness must be positive"
        )
        assert math.isfinite(profile.max_bridge_length_mm), (
            f"{profile.id}: bridge limit must be finite"
        )
        assert profile.max_bridge_length_mm > 0, (
            f"{profile.id}: bridge limit must be positive"
        )


def test_sister_printers_are_available() -> None:
    profiles = {profile.id: profile for profile in list_profiles()}

    assert "prusa_xl" in profiles
    assert "bambu_h2s" in profiles
    assert profiles["bambu_h2s"].bed_size_mm == (340.0, 320.0, 340.0)
    assert profiles["bambu_h2s"].nozzle_mm == 0.4


def test_unknown_printer_profile_falls_back_to_default() -> None:
    assert get_profile("missing-printer").id == DEFAULT_PROFILE_ID
