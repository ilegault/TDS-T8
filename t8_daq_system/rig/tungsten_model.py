"""
Lumped-parameter tungsten thermal model for simulation and practice mode.

WHY THIS EXISTS
---------------
Practice mode previously used a 20 s first-order synthetic filter lagging towards
a setpoint, rather than responding to actual commanded voltage, and replaced PID
output with a "demo voltage". Consequently, practice runs bypassed the real
feedforward map, PID loop, and cold-tungsten current limits.

Tungsten has a positive temperature coefficient of resistance (TCR), with
resistance rising ~17x from 300 K to 2500 K. This physical model couples Ohmic
heating P = V^2 / R(T) with Stefan-Boltzmann radiation and conduction loss,
accurately reproducing steady-state temperatures and electrical characteristics
without real hardware (ADR 0005).
"""
from __future__ import annotations


class TungstenSim:
    """
    Simple lumped-parameter tungsten thermal simulator.

    Call step(voltage_v) repeatedly. Each call advances by dt seconds.
    """

    # Physical constants
    STEFAN_BOLTZMANN = 5.67e-8  # W/(m^2 K^4)

    # Specimen parameters -- tuned to give:
    #   * Numerically stable steps at dt=0.5 s (no explosive first-step)
    #   * Monotonically increasing T_ss with voltage (matches feedforward table trend)
    #   * At 3.0V steady-state T_ss in the 1400–1900 K ballpark
    #
    # Calibrated from March 2026 run logs:
    #   * R_COLD target is 0.004–0.006 Ω (measured ~0.005 Ω cold)
    #   * At 6.0V steady-state, draws ~120–180 A (around 122 A)
    #   * MASS bumped to 0.150 kg to limit dT at cold start given the much lower R_COLD
    R_COLD = 0.005          # Ohms at 300K — cold resistance from March 2026 logs
    ALPHA = 0.0045          # /K  linear TCR (positive, tungsten heats ~17x cold→hot)
    MASS = 0.150            # kg  thermal mass to limit explosive heating at 6V cold start
    C_P = 140.0             # J/(kg K)  specific heat capacity (relatively flat for W)
    EMISSIVITY = 0.25       # emissivity (polished W)
    AREA = 2e-3             # m^2  effective radiating surface area
    K_COND = 0.005          # W/K  lead conduction loss (small)
    T_AMB = 300.0           # K   ambient / mounting temperature

    def __init__(self, dt: float = 0.5) -> None:
        self.dt = dt
        self._T = self.T_AMB
        self._time = 0.0

    def reset(self, T0: float = 300.0) -> None:
        self._T = float(T0)
        self._time = 0.0

    def _resistance(self, T_k: float) -> float:
        """Linear TCR model: R(T) = R_cold * (1 + alpha*(T-300))."""
        return self.R_COLD * (1.0 + self.ALPHA * (T_k - 300.0))

    def step(self, voltage_v: float) -> tuple[float, float]:
        """
        Advance simulation by dt seconds.

        Returns (temperature_k, current_a).
        """
        T = self._T
        R = self._resistance(T)
        R = max(R, 1e-6)  # prevent division by zero

        # Power balance
        P_in = (voltage_v ** 2) / R                           # Ohmic heating
        P_rad = self.EMISSIVITY * self.STEFAN_BOLTZMANN * self.AREA * (T ** 4 - self.T_AMB ** 4)
        P_cond = self.K_COND * (T - self.T_AMB)               # Lead conduction

        P_net = P_in - P_rad - P_cond
        dT = P_net * self.dt / (self.MASS * self.C_P)

        self._T = max(self.T_AMB, T + dT)
        self._time += self.dt
        current_a = voltage_v / R
        return self._T, current_a

    def get_state(self) -> dict[str, float]:
        return {
            'temperature_k': self._T,
            'time_s': self._time,
            'resistance_ohm': self._resistance(self._T),
        }

    def steady_state_temp(self, voltage_v: float, max_iter: int = 100000, tol: float = 0.01) -> float:
        """Iterate to steady-state for a fixed voltage. Returns T_ss in Kelvin."""
        self.reset()
        prev_T = 0.0
        for _ in range(max_iter):
            T, _ = self.step(voltage_v)
            if abs(T - prev_T) < tol:
                return T
            prev_T = T
        return self._T
