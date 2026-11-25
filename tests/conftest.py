import shutil
from pathlib import Path

import pytest

from etl.config import ROOT
from etl.pipeline import run


@pytest.fixture
def source(tmp_path):
    return Path(shutil.copytree(ROOT / "data/fixtures/olist", tmp_path / "source"))


@pytest.fixture(scope="session")
def built(tmp_path_factory):
    output = tmp_path_factory.mktemp("snapshot")
    manifest = run(ROOT / "data/fixtures/olist", output)
    return output, manifest, output / manifest["database"]
