"""
scripts/fit_two_node.py
Search / fit physical constants for TungstenSim two-node model against Field runs (ticket 41).

WHY THIS EXISTS
---------------
Ticket 41 requires offline fitting of the two-node tungsten model parameters
against the checked-in Field runs (ticket 40). This script evaluates current and
TC tracking RMS errors across field runs for candidate parameter sets.
"""
from __future__ import annotations

import math
import pathlib
import sys
from typing import Any

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from t8_daq_system.data.field_runs import all_field_runs  # noqa: E402

STEFAN_BOLTZMANN = 5.67e-8


def simulate_run(
    run: Any,
    r_cold: float,
    alpha: float,
    c_fil: float,
    area_fil: float,
    eps_fil: float,
    k_cond_fil: float,
    g_couple: float,
    c_tc: float,
    area_tc: float,
    eps_tc: float,
    k_cond_tc: float,
    t_amb: float = 297.15,
) -> tuple[float, float, float]:
    """
    Simulate a field run with two-node model.
    Returns (rms_amps, rms_tc, peak_sample_fil_minus_tc).
    """
    t0_k = run.filament_c[0] + 273.15
    t_fil = t0_k
    t_tc = t0_k

    sim_tc: list[float] = [t_tc - 273.15]
    r0 = max(1e-6, r_cold * (1.0 + alpha * (t_fil - 300.0)))
    v0 = max(0.0, run.ps_volts[0])
    sim_amps: list[float] = [v0 / r0 if v0 > 0 else 0.0]

    peak_amp = max(run.ps_amps)
    peak_idx = run.ps_amps.index(peak_amp)
    peak_sample_fil_diff = 0.0

    t_s = run.t_s
    volts = run.ps_volts
    n = len(t_s)

    for i in range(1, n):
        dt_total = t_s[i] - t_s[i - 1]
        v = max(0.0, volts[i])

        dt_rem = dt_total
        while dt_rem > 1e-9:
            sub_dt = min(dt_rem, 0.05)

            # Resistance of filament
            r_fil = max(1e-6, r_cold * (1.0 + alpha * (t_fil - 300.0)))

            # Power balance filament
            p_in = (v * v) / r_fil if v > 0.0 else 0.0
            p_rad_fil = eps_fil * STEFAN_BOLTZMANN * area_fil * (t_fil**4 - t_amb**4)
            p_cond_fil = k_cond_fil * (t_fil - t_amb)
            p_couple = g_couple * (t_fil - t_tc)

            p_net_fil = p_in - p_rad_fil - p_cond_fil - p_couple

            # Power balance TC node
            p_rad_tc = eps_tc * STEFAN_BOLTZMANN * area_tc * (t_tc**4 - t_amb**4)
            p_cond_tc = k_cond_tc * (t_tc - t_amb)
            p_net_tc = p_couple - p_rad_tc - p_cond_tc

            # Update temperatures with sub_dt
            dt_fil = (p_net_fil / c_fil) * sub_dt
            dt_tc = (p_net_tc / c_tc) * sub_dt

            t_fil = max(t_amb, t_fil + dt_fil)
            t_tc = max(t_amb, t_tc + dt_tc)

            dt_rem -= sub_dt

        if i == peak_idx:
            peak_sample_fil_diff = t_fil - t_tc

        sim_tc.append(t_tc - 273.15)
        r_now = max(1e-6, r_cold * (1.0 + alpha * (t_fil - 300.0)))
        sim_amps.append(v / r_now if v > 0.0 else 0.0)

    # Calculate RMS errors
    rec_amps = run.ps_amps
    rec_tc = run.filament_c
    rms_amps = math.sqrt(sum((s - r) ** 2 for s, r in zip(sim_amps, rec_amps)) / n)
    rms_tc = math.sqrt(sum((s - r) ** 2 for s, r in zip(sim_tc, rec_tc)) / n)

    return rms_amps, rms_tc, peak_sample_fil_diff


def evaluate(params: dict[str, float]) -> dict[str, Any]:
    runs = all_field_runs()
    results: dict[str, Any] = {}
    for r in runs:
        rms_i, rms_tc, peak_diff = simulate_run(r, **params)
        peak_i = max(r.ps_amps)
        i_limit = 0.15 * peak_i
        tc_limit = 50.0

        results[r.name] = {
            "rms_i": rms_i,
            "limit_i": i_limit,
            "pass_i": rms_i <= i_limit,
            "rms_tc": rms_tc,
            "limit_tc": tc_limit,
            "pass_tc": rms_tc <= tc_limit,
            "peak_diff": peak_diff,
        }
    return results


if __name__ == "__main__":
    params = {
        "r_cold": 0.0050,
        "alpha": 0.0026,
        "c_fil": 0.5,
        "area_fil": 0.0012,
        "eps_fil": 0.35,
        "k_cond_fil": 0.005,
        "g_couple": 0.12,
        "c_tc": 15.0,
        "area_tc": 0.0003,
        "eps_tc": 0.25,
        "k_cond_tc": 0.02,
        "t_amb": 297.15,
    }
    res = evaluate(params)
    print("Evaluation summary:")
    for name, r in res.items():
        print(
            f"  {name}: Current RMS={r['rms_i']:.2f}/{r['limit_i']:.2f} ({r['pass_i']}), "
            f"TC RMS={r['rms_tc']:.2f}/{r['limit_tc']:.2f} ({r['pass_tc']}), "
            f"diff={r['peak_diff']:.1f} K"
        )
