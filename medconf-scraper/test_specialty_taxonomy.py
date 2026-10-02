"""
test_specialty_taxonomy.py

pytest tests for specialty_taxonomy.py — the Python-side reader for
medconf-website/src/lib/taxonomy/specialties.json (generated from
specialties.ts via `npm run taxonomy:export`). Covers the exact gap this
module exists to close: fire_specialty_alerts.py matching a stored
user_profiles.specialty value (a post-W6 canonical slug, or a pre-W6 legacy
raw label) against the raw conferences.specialty column.

Run: ./.venv/bin/python -m pytest test_specialty_taxonomy.py -v
"""

import pytest

import specialty_taxonomy as st


def test_json_file_is_present_and_loadable():
    # Exercises the real generated file (committed alongside specialties.ts)
    # rather than a mock, so this test also catches "someone edited
    # specialties.ts and forgot to re-run the export".
    data = st._load()
    assert "parents" in data and "rawToCanonical" in data
    assert len(data["parents"]) > 0
    assert len(data["rawToCanonical"]) > 0


def test_slug_resolves_to_itself():
    assert st.canonical_parent("oncology") == "oncology"
    assert st.canonical_parent("general-practice") == "general-practice"


def test_legacy_raw_label_maps_to_its_parent():
    assert st.canonical_parent("Oncology") == "oncology"
    assert st.canonical_parent("General Practice") == "general-practice"
    # Case-insensitive, mirroring canonicalSpecialty()'s fallback in
    # specialties.ts.
    assert st.canonical_parent("ONCOLOGY") == "oncology"


def test_unknown_value_resolves_to_none():
    assert st.canonical_parent("not-a-real-specialty") is None
    assert st.canonical_parent(None) is None
    assert st.canonical_parent("") is None


@pytest.mark.parametrize(
    "value",
    ["oncology", "Oncology", "Clinical Oncology", "Surgical Oncology"],
)
def test_oncology_family_all_expand_to_the_same_raw_set(value):
    # Whichever member of the oncology family a user is stored as (slug,
    # or any legacy raw sibling), they should all expand to the SAME full
    # set — that's the whole point of expanding via the parent rather than
    # matching the literal stored string.
    expanded = set(st.raw_values_for_profile_specialty(value))
    assert expanded == set(st.raw_values_for("oncology"))
    assert "Oncology" in expanded
    assert "Clinical Oncology" in expanded


def test_multiword_slug_does_not_ilike_match_its_raw_values():
    # The bug this module fixes: a multi-word slug like "general-practice"
    # has a hyphen where the raw values have a space, so a plain
    # .ilike("specialty", "general-practice") would match ZERO rows even
    # though raw_values_for_profile_specialty correctly resolves it.
    raw_values = st.raw_values_for_profile_specialty("general-practice")
    assert "General Practice" in raw_values
    assert all("general-practice" not in v.lower() for v in raw_values)


def test_other_and_empty_expand_to_no_matches():
    assert st.raw_values_for_profile_specialty("other") == []
    assert st.raw_values_for_profile_specialty(None) == []
    assert st.raw_values_for_profile_specialty("") == []


def test_unmapped_value_expands_to_empty_list_not_itself():
    # Callers (fire_specialty_alerts.py) are expected to detect an empty
    # list and fall back to the old ilike behaviour themselves — this
    # function must not paper over an unmapped value by returning [value].
    assert st.raw_values_for_profile_specialty("a-brand-new-specialty-not-yet-mapped") == []


def test_raw_values_for_parent_round_trips_through_raw_to_canonical():
    data = st._load()
    for raw, parent in data["rawToCanonical"].items():
        assert raw in st.raw_values_for(parent)
