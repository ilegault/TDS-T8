"""
Single pure function source for run settings.

WHY THIS EXISTS
---------------
Production settings for a field run are defined by the default configuration
values (ADR 0007). We need to build a `RunSettings` object from these defaults
without loading the `tkinter` UI modules, which prevents proper headless testing
and forces GUI dependencies into pure modules (Ticket 38).
"""
from t8_daq_system.rig.commands import RunSettings
from t8_daq_system.settings.app_settings import _DEFAULTS


def run_settings_from_app_settings(settings) -> RunSettings:
    """
    Capture every run-shaping value from AppSettings into one frozen RunSettings.

    Called once when the operator presses Run. Every value is read from
    AppSettings (ADR 0007); this function holds no literals.
    """
    return RunSettings(
        kp=settings.pid_kp,
        ki=settings.pid_ki,
        kd=settings.pid_kd,
        windup_limit=settings.pid_windup_limit,
        soft_start_threshold_c=settings.soft_start_threshold_c,
        soft_start_ramp_v_per_s=settings.soft_start_ramp_v_per_s,
        soft_start_handoff_current_a=settings.soft_start_handoff_current_a,
        soft_start_cap_enabled=settings.soft_start_cap_enabled,
        soft_start_cap_a=settings.soft_start_cap_a,
        run_cap_enabled=settings.run_cap_enabled,
        run_cap_a=settings.run_cap_a,
    )


def production_run_settings() -> RunSettings:
    """
    Build the canonical production RunSettings from system defaults.

    This avoids instantiating AppSettings (which reads the registry) and avoids
    importing GUI dependencies.
    """
    return RunSettings(
        kp=_DEFAULTS["pid_kp"][1],
        ki=_DEFAULTS["pid_ki"][1],
        kd=_DEFAULTS["pid_kd"][1],
        windup_limit=_DEFAULTS["pid_windup_limit"][1],
        soft_start_threshold_c=_DEFAULTS["soft_start_threshold_c"][1],
        soft_start_ramp_v_per_s=_DEFAULTS["soft_start_ramp_v_per_s"][1],
        soft_start_handoff_current_a=_DEFAULTS["soft_start_handoff_current_a"][1],
        soft_start_cap_enabled=_DEFAULTS["soft_start_cap_enabled"][1],
        soft_start_cap_a=_DEFAULTS["soft_start_cap_a"][1],
        run_cap_enabled=_DEFAULTS["run_cap_enabled"][1],
        run_cap_a=_DEFAULTS["run_cap_a"][1],
    )
