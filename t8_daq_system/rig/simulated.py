"""
Simulated rig adapter implementing RigAdapter over TungstenSim and Clock.

WHY THIS EXISTS
---------------
Practice mode previously bypassed the real control and safety pipeline by
generating a synthetic "demo voltage" and using an ad-hoc setpoint filter rather
than simulating tungsten physics.

SimulatedRig provides a drop-in RigAdapter where commanded voltage produces
realistic current and temperature via TungstenSim. Driven by an injectable
Clock, it allows the entire application (PID, feedforward, safety, and logging)
to run identically in practice mode and in automated tests at CPU speeds
without sleeping or real hardware (ADRs 0002, 0005).
"""
from __future__ import annotations

from typing import Sequence

from t8_daq_system.rig.adapter import AdapterError, RawReadings, RigAdapter
from t8_daq_system.rig.clock import Clock
from t8_daq_system.rig.tungsten_model import TungstenSim
from t8_daq_system.settings.safety_limits import DAC0_MAX_V


class SimulatedRig(RigAdapter):
    """
    Simulated rig hardware adapter.

    Connects commanded voltage to TungstenSim and advances physics to clock.now()
    on each read(). Supports fault injection for testing trip and recovery paths.
    """

    def __init__(
        self,
        clock: Clock,
        sim: TungstenSim | None = None,
        tc_names: Sequence[str] | None = None,
        gauge_names: Sequence[str] | None = None,
        room_temp_c: float = 26.85,
    ) -> None:
        self._clock = clock
        self._sim = sim if sim is not None else TungstenSim(dt=0.5)
        self._tc_names = list(tc_names) if tc_names is not None else ["TC_1"]
        self._gauge_names = list(gauge_names) if gauge_names is not None else ["FRG702_Chamber"]
        self._room_temp_c = float(room_temp_c)

        self._connected: bool = True
        self._cable_connected: bool = True
        self._output_enabled: bool = False
        self._voltage_setpoint: float = 0.0
        self._last_time: float = clock.now()

        # Fault injection state
        self._dropped_tcs: set[str] = set()
        self._gauge_pressures: dict[str, float] = {g: 1e-7 for g in self._gauge_names}
        self._stalled_gauges: set[str] = set()
        self._fail_next_write: bool = False
        self._current_limit_pinned: bool = True
        self._forced_amps: float | None = None

    # --- RigAdapter protocol operations ---

    def connect(self) -> bool:
        if not self._cable_connected:
            return False
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._cable_connected = False

    def is_connected(self) -> bool:
        return self._connected

    def read(self) -> RawReadings:
        if not self._connected:
            raise AdapterError("Simulated rig is disconnected")

        now = self._clock.now()
        dt = now - self._last_time
        if dt > 0:
            effective_v = self._voltage_setpoint if self._output_enabled else 0.0
            # Step in sub-intervals of at most 0.5 s for numerical stability
            while dt > 1e-9:
                sub_dt = min(dt, 0.5)
                self._sim.dt = sub_dt
                self._sim.step(effective_v)
                dt -= sub_dt
            self._last_time = now

        sim_t_k = self._sim._T
        sim_t_c = sim_t_k - 273.15
        primary_tc = self._tc_names[0] if self._tc_names else None

        tc_c: dict[str, float | None] = {}
        tc_raw_v: dict[str, float | None] = {}
        for tc in self._tc_names:
            if tc in self._dropped_tcs:
                tc_c[tc] = None
                tc_raw_v[tc] = None
            elif tc == primary_tc:
                tc_c[tc] = sim_t_c
                tc_raw_v[tc] = sim_t_c * 41.276e-6
            else:
                tc_c[tc] = self._room_temp_c
                tc_raw_v[tc] = self._room_temp_c * 41.276e-6

        pressure_torr: dict[str, float | None] = {}
        pressure_valid: dict[str, bool] = {}
        for g in self._gauge_names:
            pressure_torr[g] = self._gauge_pressures.get(g, 1e-7)
            pressure_valid[g] = g not in self._stalled_gauges

        if self._output_enabled:
            ps_volts = self._voltage_setpoint
            r = max(self._sim._resistance(sim_t_k), 1e-6)
            ps_amps = self._voltage_setpoint / r
            shutoff_readback = True
        else:
            ps_volts = 0.0
            ps_amps = 0.0
            shutoff_readback = False

        if self._forced_amps is not None:
            ps_amps = self._forced_amps

        return RawReadings(
            tc_c=tc_c,
            tc_raw_v=tc_raw_v,
            pressure_torr=pressure_torr,
            pressure_valid=pressure_valid,
            ps_volts=ps_volts,
            ps_amps=ps_amps,
            shutoff_readback=shutoff_readback,
        )

    def write_voltage(self, volts: float) -> None:
        self._check_write_link_and_fault()
        self._voltage_setpoint = min(max(0.0, float(volts)), DAC0_MAX_V)

    def set_output(self, enabled: bool) -> None:
        self._check_write_link_and_fault()
        self._output_enabled = bool(enabled)

    def pin_current_limit(self) -> None:
        self._check_write_link_and_fault()
        self._current_limit_pinned = True

    # --- Fault injection methods (tests / dev tools) ---

    def drop_tc(self, name: str) -> None:
        """Simulate open or disconnected thermocouple lead."""
        self._dropped_tcs.add(name)

    def restore_tc(self, name: str) -> None:
        """Restore dropped thermocouple to normal reading."""
        self._dropped_tcs.discard(name)

    def set_pressure(self, name: str, torr: float) -> None:
        """Set pressure in Torr for a specific gauge and mark valid."""
        self._gauge_pressures[name] = float(torr)
        self._stalled_gauges.discard(name)

    def stall_gauge(self, name: str) -> None:
        """Simulate gauge communication failure or invalid data."""
        self._stalled_gauges.add(name)

    def restore_gauge(self, name: str) -> None:
        """Restore stalled gauge to valid state."""
        self._stalled_gauges.discard(name)

    def force_current(self, amps: float) -> None:
        """Make read() report this ps_amps (e.g. a shorted lead) until release_current()."""
        self._forced_amps = float(amps)

    def release_current(self) -> None:
        """Return ps_amps to the physical simulation."""
        self._forced_amps = None

    def fail_next_write(self) -> None:
        """Inject a single write failure (raises AdapterError on next write operation)."""
        self._fail_next_write = True

    def reconnect(self) -> None:
        """Restore link after disconnect()."""
        self._cable_connected = True
        self._connected = True

    # --- Internal helpers ---

    def _check_write_link_and_fault(self) -> None:
        if not self._connected:
            raise AdapterError("Simulated rig is disconnected")
        if self._fail_next_write:
            self._fail_next_write = False
            raise AdapterError("Simulated write failure")
