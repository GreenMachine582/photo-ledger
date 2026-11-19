"""Settings edited in the browser: stored in the catalogue, winning over the environment."""

import pytest

from photo_ledger import preferences
from photo_ledger.collections.folders import DEFAULT_GENERIC_FOLDERS
from photo_ledger.config import Settings


def test_defaults_come_from_the_environment(db, tmp_path):
    prefs = preferences.effective(db, Settings(photo_ledger_data_dir=tmp_path))
    assert prefs.similar_threshold == 8
    assert prefs.generic_folders == list(DEFAULT_GENERIC_FOLDERS)
    assert not prefs.saved
    env = Settings(photo_ledger_data_dir=tmp_path, photo_ledger_similar_threshold=4)
    assert preferences.effective(db, env).similar_threshold == 4


def test_a_saved_value_wins_and_reset_goes_back(db, tmp_path):
    env = Settings(photo_ledger_data_dir=tmp_path, photo_ledger_similar_threshold=4)
    preferences.save(db, similar_threshold="12", generic_folders="DCIM\n  Scans \n\ndcim\n")
    prefs = preferences.effective(db, env)
    assert prefs.similar_threshold == 12
    assert prefs.generic_folders == ["DCIM", "Scans"]
    assert prefs.saved == {"similar_threshold", "generic_folders"}
    assert preferences.reset(db) is True
    assert preferences.effective(db, env).similar_threshold == 4
    assert preferences.reset(db) is False


def test_no_generic_folders_is_allowed(db, tmp_path):
    preferences.save(db, similar_threshold=8, generic_folders="")
    assert preferences.effective(db, Settings(photo_ledger_data_dir=tmp_path)).generic_folders == []


@pytest.mark.parametrize(
    ("threshold", "folders", "message"),
    [
        ("33", "", "between 0 and 32"),
        ("-1", "", "between 0 and 32"),
        ("eight", "", "whole number"),
        ("8", "Pictures/Holidays", "isn't a folder name"),
        ("8", "Pictures\\Holidays", "isn't a folder name"),
    ],
)
def test_bad_values_store_nothing(db, threshold, folders, message):
    with pytest.raises(preferences.PreferencesError, match=message):
        preferences.save(db, similar_threshold=threshold, generic_folders=folders)
    assert db.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0


def test_matching_and_rule_switches_default_on(db, tmp_path):
    prefs = preferences.effective(db, Settings(photo_ledger_data_dir=tmp_path))
    assert prefs.name_conflicts and prefs.auto_tidier_path and prefs.auto_priority
    assert prefs.dismiss_unlike_names and prefs.min_similar_side == 0
    assert prefs.match_options() == {"name_conflicts": True, "min_similar_side": 0}
    assert prefs.rules() == {
        "tidier_path": True,
        "priority": True,
        "unlike_names": True,
        "threshold": 8,
    }
    env = Settings(photo_ledger_data_dir=tmp_path, photo_ledger_auto_tidier_path=False)
    assert preferences.effective(db, env).auto_tidier_path is False


def test_switches_and_the_smallest_size_are_saved(db, tmp_path):
    preferences.save(
        db,
        similar_threshold=8,
        generic_folders="",
        min_similar_side="200",
        auto_tidier_path="false",
        name_conflicts="true",
    )
    prefs = preferences.effective(db, Settings(photo_ledger_data_dir=tmp_path))
    assert prefs.auto_tidier_path is False and prefs.name_conflicts is True
    assert prefs.min_similar_side == 200
    assert {"auto_tidier_path", "min_similar_side"} <= prefs.saved
    assert "auto_priority" not in prefs.saved  # left out, so it keeps its default


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"min_similar_side": "-1"}, "between 0 and 10,000"),
        ({"min_similar_side": "big"}, "whole number"),
        ({"auto_priority": "maybe"}, "isn't on or off"),
        ({"surprise": "true"}, "Unknown setting"),
    ],
)
def test_bad_switches_store_nothing(db, values, message):
    with pytest.raises(preferences.PreferencesError, match=message):
        preferences.save(db, similar_threshold=8, generic_folders="", **values)
    assert db.execute("SELECT COUNT(*) FROM settings").fetchone()[0] == 0
