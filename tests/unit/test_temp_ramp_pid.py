import pytest
from t8_daq_system.control.temp_ramp_pid import PIDController

def test_pidcontroller_requires_gains():
    """PIDController must be instantiated with explicit gains (no silent defaults)."""
    with pytest.raises(TypeError):
        PIDController()

    # Instantiating with required arguments works
    pid = PIDController(kp=0.014, ki=0.00078, kd=0.00845)
    assert getattr(pid, "_kp") == 0.014
