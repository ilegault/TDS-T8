"""
Unit and property tests for the pure HeaterOutput module (Ticket 07 / ADR 0003).

WHY THIS EXISTS
---------------
ADR 0003 establishes that HeaterOutput is the single arbiter of heater commands,
prioritising Safety > Operator > Program. Every trip is an instant cutoff (0 V,
output disabled) and latches.

These tests verify Rules 1–6 from the specification and ADR 0003, verify that
ResetTrip refuses while tripping conditions persist and clears only when cleared,
and enforce property invariants (volts in [0, 6], output never enabled while
latched, nudge never enables output) over at least 1,000 random sequences.
"""
from __future__ import annotations

import random
from typing import Mapping

import pytest

from t8_daq_system.control.heater_output import (
    HeaterOutput,
    ProgramHeaterRequest,
)
from t8_daq_system.control.safety_monitor import Trip
from t8_daq_system.rig.commands import (
    RunSettings,
    Nudge,
    ResetTrip,
    SetOutput,
    SetVoltage,
    StartProgram,
    StopProgram,
)
from t8_daq_system.rig.snapshot import (
    HeaterStatus,
    ProgramStatus,
    Snapshot,
    SourceStatus,
)
from t8_daq_system.settings.safety_limits import (
    COLD_CURRENT_LIMIT_A,
    DAC0_MAX_V,
    TEMP_OVERRIDE_RESET_C,
)

pytestmark = pytest.mark.unit


def _make_snapshot(
    tc_c: Mapping[str, float | None] | None = None,
    pressure_torr: Mapping[str, float | None] | None = None,
    source_age_s: Mapping[str, float] | None = None,
    program: ProgramStatus | None = None,
    heater: HeaterStatus | None = None,
    permissive_ok: bool = True,
    permissive_reason: str | None = None,
    ps_volts: float = 0.0,
    ps_amps: float = 0.0,
    commanded_volts: float = 0.0,
    output_enabled: bool = False,
    labjack: SourceStatus | None = None,
    xgs: SourceStatus | None = None,
    adapter: str = "simulated",
) -> Snapshot:
    if tc_c is None:
        tc_c = {"TC_1": 25.0}
    if pressure_torr is None:
        pressure_torr = {"FRG702_Chamber": 1e-6}
    if source_age_s is None:
        source_age_s = {k: 0.0 for k in tc_c}
        source_age_s.update({k: 0.0 for k in pressure_torr})
    if program is None:
        program = ProgramStatus()
    if heater is None:
        heater = HeaterStatus(state="off")
    if labjack is None:
        labjack = SourceStatus(state="connected", message="OK")
    if xgs is None:
        xgs = SourceStatus(state="connected", message="OK")

    return Snapshot(
        t=100.0,
        wall_time=1700000000.0,
        tc_c=tc_c,
        tc_raw_v={k: 0.001 for k in tc_c},
        pressure_torr=pressure_torr,
        source_age_s=source_age_s,
        ps_volts=ps_volts,
        ps_amps=ps_amps,
        commanded_volts=commanded_volts,
        output_enabled=output_enabled,
        labjack=labjack,
        xgs=xgs,
        heater=heater,
        program=program,
        permissive_ok=permissive_ok,
        permissive_reason=permissive_reason,
        adapter=adapter,
    )


# =============================================================================
# Rule 1 Tests: Any trip -> instant cutoff, latched, requests ignored while latched
# =============================================================================


class TestRule1TripCutoffAndLatch:
    def test_trip_cuts_heater_same_tick_and_latches(self):
        """Rule 1: Any trip -> (False, 0.0) this tick, latch set, trip recorded."""
        ho = HeaterOutput()
        trip = Trip(
            kind="temp_override",
            reason="TC_1 temperature 2210.0 °C >= 2200.0 °C",
            sensor="TC_1",
            value=2210.0,
        )
        snap = _make_snapshot(output_enabled=True, commanded_volts=3.0)

        cmd = ho.resolve([trip], snap)

        # Unpacks as (False, 0.0)
        out_enabled, volts = cmd
        assert not out_enabled
        assert volts == 0.0
        assert ho.is_latched
        assert ho.active_trip_kind == "temp_override"
        assert "2210.0" in ho.active_trip_reason
        assert cmd.trip_kind == "temp_override"

    def test_requests_ignored_while_latched(self):
        """Rule 1: While latched, Operator and Program requests are ignored."""
        ho = HeaterOutput()
        trip = Trip(kind="pressure_high", reason="Chamber pressure 2e-4 > 1e-4 Torr")
        snap = _make_snapshot(permissive_ok=True)
        ho.resolve([trip], snap)
        assert ho.is_latched

        # Operator SetOutput(True) ignored
        cmd1 = ho.resolve([SetOutput(True)], snap)
        assert not cmd1.output_enabled
        assert cmd1.volts == 0.0

        # Operator SetVoltage ignored
        cmd2 = ho.resolve([SetVoltage(4.0)], snap)
        assert not cmd2.output_enabled
        assert cmd2.volts == 0.0

        # Operator Nudge ignored
        cmd3 = ho.resolve([Nudge("up")], snap)
        assert not cmd3.output_enabled
        assert cmd3.volts == 0.0

        # Program request ignored
        cmd4 = ho.resolve([ProgramHeaterRequest(volts=2.5)], snap)
        assert not cmd4.output_enabled
        assert cmd4.volts == 0.0

    def test_normal_operation_passes_when_not_latched(self):
        """Rule 1: Requests pass normally when there is no trip."""
        ho = HeaterOutput()
        snap = _make_snapshot(permissive_ok=True)

        cmd = ho.resolve([SetOutput(True), SetVoltage(2.0)], snap)
        assert cmd.output_enabled
        assert cmd.volts == 2.0
        assert not ho.is_latched


# =============================================================================
# Rule 2 Tests: ResetTrip acceptance & refusal reasons
# =============================================================================


class TestRule2ResetTrip:
    def test_reset_refused_when_temp_override_persists(self):
        """Rule 2: temp_override reset refused if any TC >= TEMP_OVERRIDE_RESET_C."""
        ho = HeaterOutput()
        trip = Trip(kind="temp_override", reason="TC_1 2210.0 >= 2200.0 C", sensor="TC_1", value=2210.0)
        snap1 = _make_snapshot(tc_c={"TC_1": 2210.0})
        ho.resolve([trip], snap1)
        assert ho.is_latched

        # TC_1 has cooled to 2160 °C, which is < 2200 °C but >= TEMP_OVERRIDE_RESET_C (2150 °C)
        snap2 = _make_snapshot(tc_c={"TC_1": 2160.0})
        cmd = ho.resolve([ResetTrip()], snap2)

        assert ho.is_latched
        assert not cmd.output_enabled
        assert cmd.volts == 0.0
        assert cmd.refusal_reason is not None
        assert "TC_1" in cmd.refusal_reason
        assert "2160.0" in cmd.refusal_reason
        assert str(TEMP_OVERRIDE_RESET_C) in cmd.refusal_reason or "2150" in cmd.refusal_reason

    def test_reset_accepted_when_temp_override_clears(self):
        """Rule 2: temp_override reset accepted when every TC < TEMP_OVERRIDE_RESET_C."""
        ho = HeaterOutput()
        trip = Trip(kind="temp_override", reason="TC_1 2210.0 >= 2200.0 C", sensor="TC_1", value=2210.0)
        ho.resolve([trip], _make_snapshot(tc_c={"TC_1": 2210.0}))
        assert ho.is_latched

        # TC_1 cooled to 2100 °C (< 2150 °C)
        snap_cool = _make_snapshot(tc_c={"TC_1": 2100.0})
        cmd = ho.resolve([ResetTrip()], snap_cool)

        assert not ho.is_latched
        assert ho.active_trip_kind is None
        assert cmd.refusal_reason is None
        assert not cmd.output_enabled  # Reset alone does not enable output
        assert cmd.volts == 0.0

    def test_reset_refused_when_pressure_stale_persists(self):
        """Rule 2: pressure_stale reset refused if gauge still stale."""
        ho = HeaterOutput()
        trip = Trip(kind="pressure_stale", reason="FRG702_Chamber stale (6.0 s > 5.0 s)", sensor="FRG702_Chamber")
        ho.resolve([trip], _make_snapshot())
        assert ho.is_latched

        snap_stale = _make_snapshot(source_age_s={"FRG702_Chamber": 7.0})
        cmd = ho.resolve([ResetTrip()], snap_stale)

        assert ho.is_latched
        assert cmd.refusal_reason is not None
        assert "FRG702_Chamber" in cmd.refusal_reason
        assert "stale" in cmd.refusal_reason.lower()

    def test_reset_accepted_when_pressure_stale_clears(self):
        """Rule 2: pressure_stale reset accepted when fresh valid reading exists."""
        ho = HeaterOutput()
        trip = Trip(kind="pressure_stale", reason="FRG702_Chamber stale", sensor="FRG702_Chamber")
        ho.resolve([trip], _make_snapshot())
        assert ho.is_latched

        snap_fresh = _make_snapshot(
            pressure_torr={"FRG702_Chamber": 1e-6},
            source_age_s={"FRG702_Chamber": 0.2},
            permissive_ok=True,
        )
        cmd = ho.resolve([ResetTrip()], snap_fresh)

        assert not ho.is_latched
        assert cmd.refusal_reason is None

    def test_reset_refused_when_labjack_lost_persists(self):
        """Rule 2: labjack_lost reset refused while adapter not connected."""
        ho = HeaterOutput()
        trip = Trip(kind="labjack_lost", reason="LabJack link lost")
        ho.resolve([trip], _make_snapshot(labjack=SourceStatus(state="lost")))
        assert ho.is_latched

        snap_reconnecting = _make_snapshot(labjack=SourceStatus(state="reconnecting"))
        cmd = ho.resolve([ResetTrip()], snap_reconnecting)

        assert ho.is_latched
        assert cmd.refusal_reason is not None
        assert "LabJack" in cmd.refusal_reason

    def test_reset_accepted_when_labjack_reconnected(self):
        """Rule 2: labjack_lost reset accepted when adapter connected."""
        ho = HeaterOutput()
        trip = Trip(kind="labjack_lost", reason="LabJack link lost")
        ho.resolve([trip], _make_snapshot(labjack=SourceStatus(state="lost")))
        assert ho.is_latched

        snap_connected = _make_snapshot(labjack=SourceStatus(state="connected"))
        cmd = ho.resolve([ResetTrip()], snap_connected)

        assert not ho.is_latched
        assert cmd.refusal_reason is None

    def test_reset_refused_when_active_trip_in_same_tick(self):
        """Rule 2: ResetTrip refused if an active trip is present this tick."""
        ho = HeaterOutput()
        trip = Trip(kind="pressure_high", reason="Pressure 3e-4 > 1e-4 Torr")
        snap = _make_snapshot(permissive_ok=False)

        cmd = ho.resolve([ResetTrip(), trip], snap)

        assert ho.is_latched
        assert cmd.refusal_reason is not None


# =============================================================================
# Rule 3 Tests: Output enabling, permissive requirement, nudge never enables
# =============================================================================


class TestRule3OutputEnablingAndNudge:
    def test_set_output_true_passes_when_permissive_ok_and_not_latched(self):
        """Rule 3: SetOutput(True) enables output when permissive_ok and not latched."""
        ho = HeaterOutput()
        snap = _make_snapshot(permissive_ok=True)

        cmd = ho.resolve([SetOutput(True)], snap)
        assert cmd.output_enabled

    def test_start_program_enables_output_when_permissive_ok(self):
        """Rule 3: StartProgram enables output when permissive_ok and not latched."""
        ho = HeaterOutput()
        snap = _make_snapshot(permissive_ok=True)

        cmd = ho.resolve([StartProgram(settings=RunSettings(kp=0.02, ki=0.0013, kd=0.005, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0))], snap)
        assert cmd.output_enabled

    def test_output_refused_when_permissive_not_ok(self):
        """Rule 3: SetOutput(True) and StartProgram refused when permissive_ok is False."""
        ho = HeaterOutput()
        snap = _make_snapshot(permissive_ok=False, permissive_reason="Chamber pressure high")

        cmd1 = ho.resolve([SetOutput(True)], snap)
        assert not cmd1.output_enabled
        assert cmd1.refusal_reason is not None

        cmd2 = ho.resolve([StartProgram(settings=RunSettings(kp=0.02, ki=0.0013, kd=0.005, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0))], snap)
        assert not cmd2.output_enabled

    def test_nudge_never_enables_output_when_off(self):
        """Rule 3 (FIX-3): A nudge never flips output from off to on."""
        ho = HeaterOutput()
        snap = _make_snapshot(permissive_ok=True, output_enabled=False)

        cmd_up = ho.resolve([Nudge("up")], snap)
        assert not cmd_up.output_enabled
        assert cmd_up.volts == 0.0

        cmd_down = ho.resolve([Nudge("down")], snap)
        assert not cmd_down.output_enabled
        assert cmd_down.volts == 0.0

    def test_nudge_adjusts_voltage_when_output_already_enabled(self):
        """Rule 3: Nudge adjusts voltage when output is already enabled."""
        ho = HeaterOutput()
        snap = _make_snapshot(permissive_ok=True, output_enabled=True, commanded_volts=1.5)
        # Enable output and establish voltage
        ho.resolve([SetOutput(True), SetVoltage(1.5)], snap)

        snap_running = _make_snapshot(permissive_ok=True, output_enabled=True, commanded_volts=1.5)
        cmd = ho.resolve([Nudge("up")], snap_running)
        assert cmd.output_enabled
        assert cmd.volts > 1.5


# =============================================================================
# Rule 4 Tests: Operator request while Program runs stops Program first
# =============================================================================


class TestRule4OperatorOutranksProgram:
    def test_operator_set_voltage_stops_program(self):
        """Rule 4: Operator SetVoltage while Program runs stops Program first."""
        ho = HeaterOutput()
        snap = _make_snapshot(
            permissive_ok=True,
            output_enabled=True,
            program=ProgramStatus(running=True, block_index=1),
        )

        cmd = ho.resolve([SetVoltage(2.5)], snap)

        assert cmd.stop_program is True
        assert cmd.volts == 2.5

    def test_operator_nudge_stops_program(self):
        """Rule 4: Operator Nudge while Program runs stops Program first."""
        ho = HeaterOutput()
        snap = _make_snapshot(
            permissive_ok=True,
            output_enabled=True,
            commanded_volts=2.0,
            program=ProgramStatus(running=True, block_index=1),
        )
        # Seed previous command
        ho.resolve([SetOutput(True), SetVoltage(2.0)], snap)

        cmd = ho.resolve([Nudge("up")], snap)

        assert cmd.stop_program is True
        assert cmd.volts > 2.0

    def test_operator_request_outranks_program_request_without_blending(self):
        """Rule 4: When both Operator and Program request arrive, Operator wins without blending."""
        ho = HeaterOutput()
        snap = _make_snapshot(
            permissive_ok=True,
            output_enabled=True,
            program=ProgramStatus(running=True),
        )

        cmd = ho.resolve([ProgramHeaterRequest(volts=1.0), SetVoltage(3.0)], snap)

        assert cmd.stop_program is True
        assert cmd.volts == 3.0  # Exactly operator voltage, no blending

    def test_program_request_alone_does_not_stop_program(self):
        """Rule 4: Program request alone applies without stopping Program."""
        ho = HeaterOutput()
        snap = _make_snapshot(
            permissive_ok=True,
            output_enabled=True,
            program=ProgramStatus(running=True),
        )
        ho.resolve([SetOutput(True)], snap)

        cmd = ho.resolve([ProgramHeaterRequest(volts=2.0)], snap)

        assert cmd.stop_program is False
        assert cmd.volts == 2.0


# =============================================================================
# Rule 5 Tests: Cold-tungsten current guard
# =============================================================================


class TestRule5ColdTungstenGuard:
    def test_cold_tungsten_guard_refuses_voltage_rise_when_current_high(self):
        """Rule 5: if ps_amps > COLD_CURRENT_LIMIT_A, volts may not rise above previous command."""
        ho = HeaterOutput()
        snap1 = _make_snapshot(permissive_ok=True, ps_amps=100.0)
        ho.resolve([SetOutput(True), SetVoltage(1.5)], snap1)

        # Current exceeds 180 A (e.g. 185 A)
        snap_hot = _make_snapshot(permissive_ok=True, ps_amps=COLD_CURRENT_LIMIT_A + 5.0)
        # Attempt to rise from 1.5 V to 2.5 V
        cmd = ho.resolve([SetVoltage(2.5)], snap_hot)

        # Clamped to previous command (1.5 V)
        assert cmd.volts == 1.5

    def test_cold_tungsten_guard_allows_voltage_reduction_when_current_high(self):
        """Rule 5: if ps_amps > COLD_CURRENT_LIMIT_A, decreasing voltage is permitted."""
        ho = HeaterOutput()
        snap1 = _make_snapshot(permissive_ok=True, ps_amps=100.0)
        ho.resolve([SetOutput(True), SetVoltage(2.0)], snap1)

        # Current exceeds 180 A
        snap_hot = _make_snapshot(permissive_ok=True, ps_amps=COLD_CURRENT_LIMIT_A + 5.0)
        # Lower voltage from 2.0 V to 1.2 V
        cmd = ho.resolve([SetVoltage(1.2)], snap_hot)

        assert cmd.volts == 1.2

    def test_cold_tungsten_guard_allows_rise_when_current_normal(self):
        """Rule 5: if ps_amps <= COLD_CURRENT_LIMIT_A, voltage rise is permitted."""
        ho = HeaterOutput()
        snap1 = _make_snapshot(permissive_ok=True, ps_amps=100.0)
        ho.resolve([SetOutput(True), SetVoltage(1.5)], snap1)

        snap2 = _make_snapshot(permissive_ok=True, ps_amps=175.0)
        cmd = ho.resolve([SetVoltage(2.5)], snap2)

        assert cmd.volts == 2.5


# =============================================================================
# Rule 6 Tests: Voltage clamping to [0.0, DAC0_MAX_V] & CV-only
# =============================================================================


class TestRule6VoltageClampingAndCVOnly:
    def test_voltage_clamped_to_dac0_max(self):
        """Rule 6: Volts clamped to [0.0, DAC0_MAX_V]."""
        ho = HeaterOutput()
        snap = _make_snapshot(permissive_ok=True)
        ho.resolve([SetOutput(True)], snap)

        # Above DAC0_MAX_V (6.0 V)
        cmd_high = ho.resolve([SetVoltage(8.5)], snap)
        assert cmd_high.volts == DAC0_MAX_V

        # Below 0.0 V
        cmd_low = ho.resolve([SetVoltage(-2.0)], snap)
        assert cmd_low.volts == 0.0

        # Normal voltage
        cmd_mid = ho.resolve([SetVoltage(4.2)], snap)
        assert cmd_mid.volts == 4.2

    def test_result_type_has_no_dac1_or_current_fields(self):
        """Rule 6 (CV-only): HeaterCommand result type has no field that could command DAC1."""
        ho = HeaterOutput()
        snap = _make_snapshot(permissive_ok=True)
        cmd = ho.resolve([SetOutput(True), SetVoltage(2.0)], snap)

        field_names = [f for f in dir(cmd) if not f.startswith("_")]
        # Assert no dac1, current_limit, amps, or cc_limit field exists on the command
        for forbidden in ("dac1", "current", "amps", "cc_limit", "current_limit"):
            assert not any(forbidden in name.lower() for name in field_names)

    def test_command_supports_tuple_unpacking(self):
        """HeaterCommand unpacks cleanly as (output_enabled, volts)."""
        ho = HeaterOutput()
        snap = _make_snapshot(permissive_ok=True)
        cmd = ho.resolve([SetOutput(True), SetVoltage(3.3)], snap)

        enabled, volts = cmd
        assert enabled is True
        assert volts == 3.3


# =============================================================================
# Property Tests: Over >= 1000 random sequences
# =============================================================================


class TestHeaterOutputProperties:
    def test_random_request_sequences_property_invariants(self):
        """
        Property test: over random request/trip/snapshot sequences (>= 1,000 sequences):
        - volts in [0.0, 6.0] always
        - output never enabled while latched
        - a nudge never flips output from off to on
        """
        rng = random.Random(1337)
        num_sequences = 1200
        steps_per_seq = 10

        for seq_i in range(num_sequences):
            ho = HeaterOutput()
            output_enabled_prev = False
            commanded_volts_prev = 0.0

            for _ in range(steps_per_seq):
                # Generate random snapshot
                permissive = rng.choice([True, True, False])
                ps_amps = rng.uniform(0.0, 200.0)
                tc_temp = rng.uniform(20.0, 2300.0)
                press = rng.choice([1e-6, 5e-5, 2e-4, 1e-3])
                labjack_state = rng.choice(["connected", "connected", "lost", "reconnecting"])
                prog_running = rng.choice([True, False])

                snap = _make_snapshot(
                    tc_c={"TC_1": tc_temp},
                    pressure_torr={"FRG702_Chamber": press},
                    source_age_s={"FRG702_Chamber": rng.uniform(0.0, 10.0), "TC_1": rng.uniform(0.0, 10.0)},
                    permissive_ok=permissive,
                    ps_amps=ps_amps,
                    commanded_volts=commanded_volts_prev,
                    output_enabled=output_enabled_prev,
                    labjack=SourceStatus(state=labjack_state),
                    program=ProgramStatus(running=prog_running),
                )

                # Generate random requests
                req_choices = [
                    None,
                    SetOutput(True),
                    SetOutput(False),
                    SetVoltage(rng.uniform(-2.0, 10.0)),
                    Nudge(rng.choice(["up", "down"])),
                    ProgramHeaterRequest(rng.uniform(-1.0, 8.0)),
                    StartProgram(settings=RunSettings(kp=0.02, ki=0.0013, kd=0.005, windup_limit=30.0, soft_start_threshold_c=200.0, soft_start_ramp_v_per_s=0.02, soft_start_handoff_current_a=35.0, soft_start_cap_enabled=True, soft_start_cap_a=40.0, run_cap_enabled=True, run_cap_a=120.0)),
                    StopProgram(),
                    ResetTrip(),
                    Trip(kind="temp_override", reason="test override", sensor="TC_1", value=tc_temp),
                    Trip(kind="pressure_high", reason="test pressure", sensor="FRG702_Chamber", value=press),
                ]
                req = rng.choice(req_choices)
                requests = [req] if req is not None else []

                was_latched = ho.is_latched
                is_nudge = isinstance(req, Nudge)

                cmd = ho.resolve(requests, snap)

                # Invariant 1: volts in [0.0, 6.0] always
                assert 0.0 <= cmd.volts <= DAC0_MAX_V, f"Volts {cmd.volts} out of bounds"

                # Invariant 2: output never enabled while latched
                if ho.is_latched:
                    assert not cmd.output_enabled, "Output was enabled while latched"
                    assert cmd.volts == 0.0, "Volts non-zero while latched"
                if was_latched and not isinstance(req, ResetTrip):
                    assert ho.is_latched, "Latch cleared without ResetTrip"

                # Invariant 3: a nudge never flips output from off to on
                if is_nudge and not output_enabled_prev:
                    assert not cmd.output_enabled, "Nudge enabled output from off state"

                output_enabled_prev = cmd.output_enabled
                commanded_volts_prev = cmd.volts


def test_extract_limit_from_malformed_reason_raises():
    """Malformed trip reason with '>=' must raise ValueError instead of silently returning None."""
    with pytest.raises(ValueError):
        HeaterOutput._extract_limit_from_reason("TC_1 exceeded limit >= not_a_number °C")
    with pytest.raises(ValueError):
        HeaterOutput._extract_limit_from_reason("TC_1 exceeded limit >=")

