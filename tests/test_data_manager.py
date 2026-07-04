import glob
import json
import os

import pytest

from data_manager import DataManager


@pytest.fixture
def data_file(tmp_path):
    return str(tmp_path / "salary_data.json")


def test_save_load_round_trip(data_file):
    dm = DataManager(data_file)
    user = dm.get_user_data("42")
    user["rate"] = 500.0
    user["clickup_synced_entries"].add("entry-1")
    dm.save_data()

    dm2 = DataManager(data_file)
    loaded = dm2.get_user_data("42")
    assert loaded["rate"] == 500.0
    assert loaded["clickup_synced_entries"] == {"entry-1"}


def test_save_is_atomic_no_tmp_left_behind(data_file):
    dm = DataManager(data_file)
    dm.get_user_data("42")["rate"] = 100.0
    dm.save_data()

    assert os.path.exists(data_file)
    assert not os.path.exists(data_file + ".tmp")
    with open(data_file, encoding="utf-8") as f:
        assert json.load(f)["42"]["rate"] == 100.0


def test_corrupt_file_backed_up_not_overwritten(data_file):
    with open(data_file, "w", encoding="utf-8") as f:
        f.write('{"broken json')

    dm = DataManager(data_file)
    assert dm.data == {}

    backups = glob.glob(data_file + ".corrupt-*")
    assert len(backups) == 1
    with open(backups[0], encoding="utf-8") as f:
        assert f.read() == '{"broken json'

    # Последующее сохранение не должно трогать бэкап
    dm.get_user_data("42")["rate"] = 100.0
    dm.save_data()
    assert glob.glob(data_file + ".corrupt-*") == backups
