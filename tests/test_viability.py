from recoveryflex import BatterySpec
from recoveryflex.viability import KernelState, compose_kernel, sequence_contraction

def test_rearmed_state_composes_for_short_event():
    r=compose_kernel(KernelState(.70),100,.25,1.0,3,BatterySpec())
    assert r.viable and len(r.states)==4

def test_long_event_fails_at_low_soc():
    r=compose_kernel(KernelState(.20),150,1.0,1.0,2,BatterySpec())
    assert not r.viable

def test_contraction():
    assert sequence_contraction([100,80,60]).tolist()==[1.0,.8,.75]
