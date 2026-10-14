"""
tests/unit/test_post_run_suggestion_dialog.py

Ticket cold-start-and-traceability-32: the post-run popup shows the one engine's
metrics and reasons, and Apply only opens Settings prefilled (ADR 0007).
"""
import importlib.util
import inspect
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from t8_daq_system.control.suggestion_engine import run_metrics, suggest
from t8_daq_system.gui import main_window as mw
from t8_daq_system.gui.main_window import MainWindow
from t8_daq_system.settings.app_settings import AppSettings


def _record():
    gains = (1.0, 0.05, 0.05)
    # Overshoot of 8 K, error large and one-sided: Kp -15 %.
    log = [(float(i), 400.0, 408.0, 2.0) for i in range(30)]
    metrics = run_metrics(log, rate_k_per_min=0.0)
    s = suggest(metrics, gains)
    assert len(s.reasons) >= 1
    return {
        "overshoot_k": metrics["overshoot_k"],
        "oscillation_count": metrics["oscillation_count"],
        "settling_time_sec": metrics["settling_time_sec"],
        "kp_used": gains[0], "ki_used": gains[1], "kd_used": gains[2],
        "suggested_kp": s.kp, "suggested_ki": s.ki, "suggested_kd": s.kd,
        "suggestions": list(s.reasons),
    }, s


@pytest.fixture
def window(monkeypatch):
    record, suggestion = _record()
    settings = AppSettings()
    save = MagicMock()
    monkeypatch.setattr(settings, "save", save)
    fake = SimpleNamespace(
        rig=SimpleNamespace(program_run=SimpleNamespace(last_run_record=record)),
        _app_settings=settings,
        root=MagicMock(),
        _apply_settings_to_gui=MagicMock(),
    )
    asked = MagicMock(return_value=True)
    monkeypatch.setattr(mw.messagebox, "askyesno", asked)
    dialog_cls = MagicMock()
    monkeypatch.setattr(mw, "SettingsDialog", dialog_cls)
    return SimpleNamespace(fake=fake, record=record, suggestion=suggestion,
                           save=save, asked=asked, dialog_cls=dialog_cls,
                           settings=settings)


def test_apply_opens_settings_prefilled_and_never_saves(window):
    MainWindow._show_pid_run_summary(window.fake)
    window.dialog_cls.assert_called_once()
    args, kwargs = window.dialog_cls.call_args
    assert args[0] is window.fake.root
    assert args[1] is window.settings
    s = window.suggestion
    assert kwargs["prefill_gains"] == (round(s.kp, 5), round(s.ki, 5), round(s.kd, 5))
    window.save.assert_not_called()


def test_declining_apply_opens_nothing(window):
    window.asked.return_value = False
    MainWindow._show_pid_run_summary(window.fake)
    window.dialog_cls.assert_not_called()
    window.save.assert_not_called()


def test_message_contains_every_reason_and_metrics(window):
    MainWindow._show_pid_run_summary(window.fake)
    msg = window.asked.call_args.args[1]
    for reason in window.suggestion.reasons:
        assert reason in msg
    assert f"{window.record['overshoot_k']:.2f}" in msg


def test_summary_source_has_no_private_gain_maths():
    src = inspect.getsource(MainWindow._show_pid_run_summary)
    for needle in ("* 0.7", "* 0.6", "* 1.3"):
        assert needle not in src


class _Var:
    def __init__(self):
        self.v = None

    def set(self, v):
        self.v = v

    def get(self):
        return self.v


def test_settings_dialog_prefill_sets_gain_variables(monkeypatch):
    monkeypatch.setattr(sys.modules["tkinter"], "Toplevel", type("Toplevel", (), {}))
    spec = importlib.util.find_spec("t8_daq_system.gui.settings_dialog")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    d = object.__new__(module.SettingsDialog)
    d._pid_kp_var, d._pid_ki_var, d._pid_kd_var = _Var(), _Var(), _Var()
    d._apply_gain_prefill((1.15, 0.0425, 0.05))
    assert (d._pid_kp_var.get(), d._pid_ki_var.get(), d._pid_kd_var.get()) == (
        "1.15", "0.0425", "0.05")
