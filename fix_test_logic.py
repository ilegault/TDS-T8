import sys
from unittest.mock import MagicMock
sys.modules['winreg'] = MagicMock()
sys.modules['labjack'] = MagicMock()

from t8_daq_system.rig.clock import ManualClock
from t8_daq_system.rig.simulated import SimulatedRig

clock = ManualClock()
rig = SimulatedRig(clock=clock, tc_names=["TC_1"])
rig.set_output(True)
rig.write_voltage(0.29)
readings = rig.read()

print(f"Current: {readings.ps_amps}")
