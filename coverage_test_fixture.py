from pathlib import Path

from coverage_capture import write_capture
from coverage_scenarios import make_scenarios


def create_fixture(root):
    scenarios = make_scenarios()
    return write_capture(Path(root), scenarios=[scenarios[0], scenarios[-1]], grid_n=4)
