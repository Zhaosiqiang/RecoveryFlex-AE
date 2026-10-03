from pathlib import Path
from recoveryflex import FeederModel

def test_ieee13_open_dss_audit():
    root=Path(__file__).resolve().parents[1]
    m=FeederModel(root/'data/raw/IEEE13Nodeckt.dss',battery_sites=('634.1',),line_limit=1.05)
    a=m.solve(load_scale=.5,pv_fraction=.5,p_kw={'634.1':50})
    assert a.error=='' and a.vmin>.9 and a.vmax<1.1 and a.max_line_loading<2
