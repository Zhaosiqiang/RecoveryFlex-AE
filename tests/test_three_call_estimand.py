from pathlib import Path
import sys

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_three_call_grid_v1 import _cluster_bootstrap


def test_three_call_summary_helper_exposes_both_estimands():
    # Two rows on date A and one on date B deliberately make the pooled and
    # equal-date means differ, so a regression cannot hide the distinction.
    frame = pd.DataFrame({"date": ["A", "A", "B"], "value": [1.0, 3.0, 5.0]})
    out = _cluster_bootstrap(frame, "value", ("test",))
    assert out["estimate"] == pytest.approx(3.5)  # (2 + 5) / 2
    assert out["unit_weighted_estimate"] == pytest.approx(3.0)
    assert out["n_dates"] == 2
    assert out["n_units"] == 3
