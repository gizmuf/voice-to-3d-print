from __future__ import annotations

from services.printer_profiles import DEFAULT_PROFILE_ID, get_profile, list_profiles


def test_printer_profile_ids_are_unique() -> None:
    ids = [profile.id for profile in list_profiles()]
    assert len(ids) == len(set(ids))


def test_sister_printers_are_available() -> None:
    profiles = {profile.id: profile for profile in list_profiles()}

    assert "prusa_xl" in profiles
    assert "bambu_h2s" in profiles
    assert profiles["bambu_h2s"].bed_size_mm == (340.0, 320.0, 340.0)
    assert profiles["bambu_h2s"].nozzle_mm == 0.4


def test_unknown_printer_profile_falls_back_to_default() -> None:
    assert get_profile("missing-printer").id == DEFAULT_PROFILE_ID

