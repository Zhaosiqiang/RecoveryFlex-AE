from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cluster_statistics import cluster_bootstrap


def test_cluster_bootstrap_is_invariant_to_row_order_and_call_order():
    rows = pd.DataFrame(
        {
            "date": ["2020-01-02", "2020-01-01", "2020-01-02", "2020-01-01"],
            "group": [1, 0, 0, 1],
            "service_kw": [4.0, 1.0, 2.0, 3.0],
        }
    )
    context = ("effect", "baseline_feasible", "634.1", "myopic_recovery", "service_kw")
    expected = cluster_bootstrap(
        rows,
        "service_kw",
        ("date",),
        20261003,
        200,
        context=context,
    )
    # An unrelated summary and a shuffled table must not consume or perturb
    # the stream used by the declared result context.
    cluster_bootstrap(
        rows,
        "service_kw",
        ("date", "group"),
        20261003,
        200,
        context=("method", "all", "611.3", "network_lp", "service_kw"),
    )
    observed = cluster_bootstrap(
        rows.sample(frac=1.0, random_state=7),
        "service_kw",
        ("date",),
        20261003,
        200,
        context=context,
    )
    assert observed == expected


def test_cluster_bootstrap_date_group_count_name_is_explicit():
    rows = pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-01", "2020-01-02"],
            "group": [0, 1, 0],
            "effect": [1.0, 3.0, 5.0],
        }
    )
    result = cluster_bootstrap(
        rows,
        "effect",
        ("date", "group"),
        20261003,
        20,
        context=("effect", "test"),
        count_name="n_dates",
    )
    assert result["n_dates"] == 3
    assert result["n_pairs"] == 3
