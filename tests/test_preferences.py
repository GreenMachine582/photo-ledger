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
