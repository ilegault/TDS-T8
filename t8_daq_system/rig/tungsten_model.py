"""
Lumped-parameter tungsten thermal model for simulation and practice mode.

WHY THIS EXISTS
---------------
Practice mode previously used a 20 s first-order synthetic filter lagging towards
a setpoint, rather than responding to actual commanded voltage, and replaced PID
output with a "demo voltage". Consequently, practice runs bypassed the real
feedforward map, PID loop, and cold-tungsten current limits.

Tungsten has a positive temperature coefficient of resistance (TCR), with
resistance rising ~17x from 300 K to 2500 K. In reality, the thermocouple sits
on the specimen and lags significantly behind the glowing filament.

This module implements a physical two-node thermal model (ticket 41, ADR 0005):
1. A **filament** node carrying electrical resistance R(T_filament), Ohmic heating
   P = V^2 / R(T_filament), radiation loss, and lead conduction loss.
2. A **TC** node representing the specimen thermocouple, coupled to the filament
   by thermal conductance G_COUPLE, with its own thermal capacity and ambient losses.

Calibration targets:
- Cold resistance R(300 K) between 0.004 and 0.006 Ohm (March 2026 logs: ~4-5 mOhm).
- Steady-state current at 6.0 V between 120 and 180 A (tested: ~176 A at T_fil ~ 2530 K).
- Replay current tracking: RMS current error <= 15% of peak current across field runs.
- Replay TC tracking: RMS TC error <= 50 K across active field runs (2026-03-26 through 2026-03-30).
- Filament-TC thermal lag: at peak current on 2026-04-15_ramp_hold_down, T_filament - T_TC >= 500 K.
"""
from __future__ import annotations

from typing import Sequence


class TungstenSim:
    """
    Two-node lumped-parameter tungsten thermal simulator.

    Nodes:
      - Filament: carries Ohmic heating P = V^2 / R(T_fil), radiation, and lead conduction.
      - TC: thermocouple/specimen node coupled to filament by thermal conductance.

    Call step(voltage_v) repeatedly. Each call advances by dt seconds.
    Returns (temperature_k, current_a) where temperature_k is the TC node.
    """

    # Physical constants
    STEFAN_BOLTZMANN = 5.67e-8  # W/(m^2 K^4)

    # Filament node parameters -- calibrated against March/April 2026 Field runs (ticket 41):
    R_COLD = 0.0050          # Ohms at 300 K (March 2026 logs: 0.0093 V -> 2.17 A at 27 C)
    ALPHA = 0.0026           # /K linear TCR fitted against Field runs 2026-03-26..2026-03-30
    C_FIL = 0.5              # J/K filament thermal capacity (rapid response)
    AREA_FIL = 0.0012        # m^2 effective radiating surface area of filament
    EMISSIVITY_FIL = 0.35    # emissivity of tungsten filament at high temperature
    K_COND_FIL = 0.005       # W/K lead conduction loss

    # Coupling and TC node parameters -- calibrated to reproduce thermal lag and TC traces:
    G_COUPLE = 0.12          # W/K thermal conductance coupling between filament and TC
    C_TC = 15.0              # J/K specimen and thermocouple thermal capacity (thermal lag)
    AREA_TC = 0.0003         # m^2 specimen radiating surface area
    EMISSIVITY_TC = 0.25     # emissivity of specimen
    K_COND_TC = 0.02         # W/K specimen mount conduction loss
    T_AMB = 300.0            # K ambient / mounting temperature

    # Backwards-compatibility aliases for single-node references
    MASS = 0.010
    C_P = 140.0
    EMISSIVITY = 0.25
    AREA = 3e-3
    K_COND = 0.005

    def __init__(self, dt: float = 0.5) -> None:
        self.dt = dt
        self._T_fil = self.T_AMB
        self._T_tc = self.T_AMB
        self._time = 0.0

    @property
    def _T(self) -> float:
        """TC node temperature in Kelvin (backwards compatibility)."""
        return self._T_tc

    def reset(self, T0: float = 300.0) -> None:
        """Reset both filament and TC nodes to T0 Kelvin."""
        self._T_fil = float(T0)
        self._T_tc = float(T0)
        self._time = 0.0

    def _resistance(self, T_k: float) -> float:
        """Linear TCR model: R(T) = R_cold * (1 + alpha*(T-300))."""
        return self.R_COLD * (1.0 + self.ALPHA * (T_k - 300.0))

    def step(self, voltage_v: float) -> tuple[float, float]:
        """
        Advance simulation by dt seconds.

        Returns (temperature_k, current_a) where temperature_k is the TC node.
        """
        v_eff = max(0.0, float(voltage_v))
        dt_rem = self.dt

        # Sub-step to ensure numerical stability and accuracy
        sub_limit = 0.05
        while dt_rem > 1e-9:
            sub_dt = min(dt_rem, sub_limit)
            R_fil = max(self._resistance(self._T_fil), 1e-6)

            # Power balance on filament node
            p_in = (v_eff ** 2) / R_fil if v_eff > 0.0 else 0.0
            p_rad_fil = (
                self.EMISSIVITY_FIL
                * self.STEFAN_BOLTZMANN
                * self.AREA_FIL
                * (self._T_fil ** 4 - self.T_AMB ** 4)
            )
            p_cond_fil = self.K_COND_FIL * (self._T_fil - self.T_AMB)
            p_couple = self.G_COUPLE * (self._T_fil - self._T_tc)

            p_net_fil = p_in - p_rad_fil - p_cond_fil - p_couple

            # Power balance on TC node
            p_rad_tc = (
                self.EMISSIVITY_TC
                * self.STEFAN_BOLTZMANN
                * self.AREA_TC
                * (self._T_tc ** 4 - self.T_AMB ** 4)
            )
            p_cond_tc = self.K_COND_TC * (self._T_tc - self.T_AMB)
            p_net_tc = p_couple - p_rad_tc - p_cond_tc

            # Advance temperatures
            dT_fil = (p_net_fil / self.C_FIL) * sub_dt
            dT_tc = (p_net_tc / self.C_TC) * sub_dt

            self._T_fil = max(self.T_AMB, self._T_fil + dT_fil)
            self._T_tc = max(self.T_AMB, self._T_tc + dT_tc)
            dt_rem -= sub_dt

        self._time += self.dt
        R_fil_final = max(self._resistance(self._T_fil), 1e-6)
        current_a = v_eff / R_fil_final if v_eff > 0.0 else 0.0
        return self._T_tc, current_a

    def get_state(self) -> dict[str, float]:
        """Return dict of current simulation state."""
        return {
            "temperature_k": self._T_tc,
            "filament_temperature_k": self._T_fil,
            "time_s": self._time,
            "resistance_ohm": self._resistance(self._T_fil),
        }

    def steady_state_temp(
        self, voltage_v: float, max_iter: int = 100000, tol: float = 0.01
    ) -> float:
        """Iterate to steady-state for a fixed voltage. Returns T_ss of TC node in Kelvin."""
        self.reset()
        prev_T_tc = 0.0
        prev_T_fil = 0.0
        for i in range(max_iter):
            T_tc, _ = self.step(voltage_v)
            if i > 20 and abs(T_tc - prev_T_tc) < tol and abs(self._T_fil - prev_T_fil) < tol:
                return T_tc
            prev_T_tc = T_tc
            prev_T_fil = self._T_fil
        return self._T_tc

    class _ReplayDescriptor:
        """Descriptor enabling TungstenSim.replay(...) and sim.replay(...)."""

        def __get__(self, obj: TungstenSim | None, objtype: type[TungstenSim] | None = None):
            if obj is None:
                assert objtype is not None

                def _replay_class(
                    t_s: Sequence[float],
                    volts: Sequence[float],
                    t0_c: float,
                ) -> tuple[tuple[float, ...], tuple[float, ...]]:
                    sim = objtype()
                    return sim._replay_instance(t_s, volts, t0_c)

                return _replay_class
            else:
                def _replay_instance_call(
                    t_s: Sequence[float],
                    volts: Sequence[float],
                    t0_c: float,
                ) -> tuple[tuple[float, ...], tuple[float, ...]]:
                    return obj._replay_instance(t_s, volts, t0_c)

                return _replay_instance_call

    replay = _ReplayDescriptor()

    def _replay_instance(
        self,
        t_s: Sequence[float],
        volts: Sequence[float],
        t0_c: float,
    ) -> tuple[tuple[float, ...], tuple[float, ...]]:
        n = len(t_s)
        if n == 0:
            return (), ()

        self.reset(t0_c + 273.15)
        # Point 0
        v0 = max(0.0, float(volts[0]))
        r0 = max(self._resistance(self._T_fil), 1e-6)
        sim_tc: list[float] = [self._T_tc - 273.15]
        sim_amps: list[float] = [v0 / r0 if v0 > 0.0 else 0.0]

        for i in range(1, n):
            dt_total = t_s[i] - t_s[i - 1]
            v = max(0.0, float(volts[i]))
            dt_rem = dt_total
            while dt_rem > 1e-9:
                sub_dt = min(dt_rem, 0.5)
                self.dt = sub_dt
                self.step(v)
                dt_rem -= sub_dt

            sim_tc.append(self._T_tc - 273.15)
            r_now = max(self._resistance(self._T_fil), 1e-6)
            sim_amps.append(v / r_now if v > 0.0 else 0.0)

        return tuple(sim_tc), tuple(sim_amps)
