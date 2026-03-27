# TDS-T8 Data Acquisition and Control System — Technical Review

**Project:** Thermal Desorption Spectroscopy (TDS) Instrument Control Software
**Repository:** `TDS-T8`
**Platform:** Windows 10/11, Python 3.9+
**Author:** IGLeg
**Review Date:** 2026-03-26

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Scientific and Engineering Context](#2-scientific-and-engineering-context)
3. [Hardware Architecture](#3-hardware-architecture)
4. [Software Architecture Overview](#4-software-architecture-overview)
5. [Hardware Abstraction Layer](#5-hardware-abstraction-layer)
6. [Data Acquisition Core](#6-data-acquisition-core)
7. [Control System](#7-control-system)
8. [Safety System](#8-safety-system)
9. [Data Management](#9-data-management)
10. [Graphical User Interface](#10-graphical-user-interface)
11. [Settings and Persistence](#11-settings-and-persistence)
12. [Practice Mode](#12-practice-mode)
13. [Deployment and Distribution](#13-deployment-and-distribution)
14. [Test Suite](#14-test-suite)
15. [Known Issues and Future Work](#15-known-issues-and-future-work)

---

## 1. Executive Summary

The TDS-T8 system is a custom Python application developed to support Thermal Desorption Spectroscopy (TDS) experiments in a vacuum laboratory environment. It serves as the sole control interface between the experimenter and all physical instruments involved in a TDS run: a high-current DC power supply for resistive specimen heating, multiple thermocouples for temperature measurement, full-range vacuum gauges for chamber pressure monitoring, and an optional Quadrupole Mass Spectrometer (QMS) for gas species analysis.

The application is built around a **LabJack T8 USB Data Acquisition (DAQ) device**, which acts as the central analog and digital I/O hub. All sensor readings and control signals pass through the T8. The software provides:

- **Real-time data acquisition** at configurable rates (1 Hz to 10 Hz) across all sensor channels simultaneously.
- **Multiple control modes**: open-loop constant-voltage ramps, closed-loop PID temperature ramps, and isothermal stable-hold segments.
- **A block-based program sequencer** allowing users to chain control segments into repeatable, saveable experimental protocols.
- **A multi-panel live GUI** with real-time matplotlib plots, numeric readouts, and a wiring diagram viewer.
- **A three-tier safety system** with configurable per-sensor temperature limits, warning thresholds, and an emergency controlled ramp-down triggered at 2200 °C.
- **Structured CSV data logging** with embedded JSON metadata, supporting both in-run monitoring and post-run data replay.
- **QMS synchronization** via automated mouse-click triggering and execution gating.
- **A standalone Windows executable** built with PyInstaller, requiring no Python installation on laboratory computers.

The software is written entirely in Python and uses Tkinter for the GUI, matplotlib for plotting, the LabJack LJM library for hardware communication, and pyserial for RS-232 vacuum gauge control. All settings are persisted to the Windows Registry, eliminating external configuration file management.

---

## 2. Scientific and Engineering Context

### 2.1 Thermal Desorption Spectroscopy

Thermal Desorption Spectroscopy is a surface science technique in which a specimen is heated in ultra-high vacuum (UHV) and the thermally stimulated desorption of surface-adsorbed or bulk-dissolved species is monitored as a function of temperature and time. A QMS records the partial pressure of desorbing species, producing a desorption spectrum. The positions and shapes of desorption peaks provide quantitative information about binding energies, surface coverage, and desorption kinetics.

A TDS experiment requires:
1. A controlled, reproducible heating ramp (typically linear in temperature, e.g., 1–10 K/min).
2. Simultaneous high-resolution temperature and pressure measurement.
3. Accurate synchronization between the heating controller and the mass spectrometer.
4. UHV conditions (typically 10⁻⁹ to 10⁻⁷ mbar) during the measurement.

### 2.2 Resistive Heating and the Tungsten TCR Problem

The specimen in this system is heated resistively: a large direct current (up to 180 A) is passed through the tungsten sample or heater filament, and Joule heating raises the temperature. Tungsten is the material of choice for high-temperature experiments due to its exceptionally high melting point (~3422 °C) and mechanical strength at elevated temperatures.

However, tungsten presents a critical control engineering challenge: it exhibits a **strongly positive Temperature Coefficient of Resistance (TCR)**. The electrical resistance of tungsten at room temperature is approximately **17 times lower** than its resistance at operating temperature (e.g., 2000 °C). This means:

- At room temperature, tungsten is effectively a short circuit for the power supply.
- Applying a large current at room temperature would result in catastrophic overcurrent before the specimen heats up enough for its resistance to rise.
- Conventional constant-current (CC) control is therefore unsafe for cold startup.

The solution implemented in this system is **Constant Voltage (CV) mode only**:

- The voltage setpoint (`DAC0`) is ramped slowly and linearly.
- The current ceiling (`DAC1`) is pinned at its maximum value (5 V analog → 180 A output).
- As the specimen heats, its resistance rises naturally (positive TCR), causing the current to self-limit without any active current control.
- This creates a "docile," self-regulating heating process: the physics of tungsten's TCR acts as a natural safety mechanism.

This constraint — CV-only operation — is the single most important design decision in the entire system and is explicitly enforced in software. The PID controller and all ramp blocks apply corrections to the **voltage setpoint**, never the current setpoint. The current limit DAC is set once at startup and not modified during a run.

### 2.3 Temperature Range and Measurement Challenges

The system is designed to operate from room temperature (~300 K) up to approximately 2315 °C (the instrument's safety hard limit is set at 2200 °C). At these temperatures:

- Type-K thermocouples (Chromel-Alumel) are limited to ~1370 °C.
- Type-C thermocouples (W5%Re/W26%Re) are suitable to ~2315 °C and are the primary sensors for high-temperature work.
- Cold-junction compensation is performed automatically by the LabJack T8's onboard reference.

The software supports all standard thermocouple types (K, J, T, E, R, S, B, N, C) and allows per-channel type configuration, enabling mixed-type setups where different sensors monitor different temperature ranges simultaneously.

---

## 3. Hardware Architecture

### 3.1 Instrument List

| Device | Role | Interface | Key Specifications |
|--------|------|-----------|-------------------|
| **LabJack T8** | Central DAQ and I/O hub | USB (LJM library) | 8× differential analog inputs (24-bit), 2× DAC outputs, digital I/O |
| **Keysight N5700** | DC power supply for resistive heating | Analog DB25 J1 connector | 6 V / 180 A max; programmable via 0–5 V analog signals |
| **Agilent XGS-600** | Vacuum gauge controller | RS-232 (COM4, 9600 baud) | Controls up to 6 gauge heads; RS-485 multi-drop protocol |
| **Leybold FRG-702** | Full-range vacuum gauge | Via XGS-600 | Pirani + cold cathode; range ~10⁻⁹ to 1000 mbar |
| **Thermocouples** | Temperature measurement | T8 differential AIN (EF registers) | Types K, J, T, E, R, S, B, N, C; up to 8 channels |
| **QMS** (external) | Gas species analysis | Separate instrument (triggered via autoclicker) | Synchronized via QMS Trigger block feature |

### 3.2 LabJack T8

The LabJack T8 is a USB-connected, 8-channel differential analog input device with 24-bit resolution. It communicates with the host PC via the LJM (LabJack Modbus) library. Key capabilities used in this system:

- **AIN0–AIN7**: Differential analog inputs configured with the T8's Extended Feature (EF) system for direct thermocouple reading with built-in cold-junction compensation. The EF system handles thermocouple linearization in firmware, returning temperature directly in the selected unit.
- **DAC0**: Analog output (0–5 V) used as the voltage setpoint for the Keysight power supply (0–5 V = 0–6 V output).
- **DAC1**: Analog output (0–5 V) used as the current ceiling for the Keysight power supply (0–5 V = 0–180 A).
- **AIN4**: Analog input monitoring actual output voltage from the Keysight (0–5 V = 0–6 V).
- **AIN5**: Analog input monitoring actual output current from the Keysight (0–5 V = 0–180 A).
- **FIO0/FIO1**: Digital I/O for shutdown signaling and turbo pump control.

### 3.3 Keysight N5700 Power Supply

The Keysight N5700 is a 6 V / 180 A (approximately 1 kW) DC power supply. It is controlled entirely via analog signals on its DB25 J1 rear-panel connector, eliminating the need for VISA/GPIB communication during a run. The analog interface is configured via rear-panel DIP switches (SW1).

**Required DIP Switch Configuration (SW1):**

| Switch | Position | Effect |
|--------|----------|--------|
| 1 | UP | Enables analog voltage programming |
| 2 | UP | Enables analog current programming |
| 3 | DOWN | Sets 0–5 V programming range |
| 4 | DOWN | Sets 0–5 V monitor range |
| 5 | UP | Shutdown polarity: FIO1 = logic 0 → output OFF |

**J1 Wiring (DB25 connector):**

| J1 Pin | Signal | T8 Connection | Direction |
|--------|--------|---------------|-----------|
| 3 | Voltage setpoint (0–5 V = 0–6 V out) | DAC0 | T8 → Keysight |
| 4 | Current ceiling (0–5 V = 0–180 A) | DAC1 | T8 → Keysight |
| 15 | Shut-Off enable (active per SW1-5 polarity) | FIO1 | T8 → Keysight |
| 11 | Voltage monitor (0–5 V = 0–6 V) | AIN4+ | Keysight → T8 |
| 24 | Current monitor (0–5 V = 0–180 A) | AIN5+ | Keysight → T8 |
| 12 | Analog GND reference | AIN4−, AIN5− | — |
| 22, 23 | Analog chassis GND | T8 GND | — |

> **Critical wiring note:** Pin 12 (Analog GND Reference) must be connected to the negative inputs of the differential pairs AIN4− and AIN5−, **not** to the T8 chassis GND. Wiring Pin 12 to T8 GND creates a ground loop that produces incorrect current readings.

### 3.4 Agilent XGS-600 and Leybold FRG-702

The XGS-600 is a multi-channel vacuum gauge controller that communicates with the host PC via RS-232 (9600 baud, 8N1, no flow control). It is connected to the host PC via an OIKWAN FTDI USB-to-serial adapter on COM4. The connection requires a straight-wired male DB9 cable (not a null-modem cable).

The FRG-702 is a full-range gauge that combines a Pirani gauge (for higher pressures, ~10⁻³ to 1000 mbar) with a cold cathode ionization gauge (for UHV, ~10⁻⁹ to 10⁻² mbar). The XGS-600 reports gauge status alongside pressure values — the software handles the following gauge states: valid combined reading, Pirani-only mode (cold cathode offline), underrange, overrange, sensor error, and no supply.

The software polls the XGS-600 at most once per 200 ms to avoid overloading the serial bus.

---

## 4. Software Architecture Overview

### 4.1 Layered Architecture

The application is organized into five distinct layers, each with a well-defined responsibility:

```
┌─────────────────────────────────────────────────────────────────┐
│                        gui/                                     │
│  main_window.py  ·  live_plot.py  ·  sensor_panel.py           │
│  power_programmer_panel.py  ·  settings_dialog.py  ·  etc.     │
└────────────────────────┬────────────────────────────────────────┘
                         │ callbacks / root.after()
┌────────────────────────▼────────────────────────────────────────┐
│                       core/                                     │
│               data_acquisition.py                               │
│         (background polling thread, callback dispatch)          │
└──────┬─────────────────┬───────────────────────────────────────┘
       │                 │
┌──────▼──────┐   ┌──────▼──────────────────────────────────────┐
│  hardware/  │   │               control/                       │
│  labjack    │   │  program_executor.py  ·  temp_ramp_pid.py   │
│  thermo     │   │  safety_monitor.py   ·  program_block.py    │
│  keysight   │   └─────────────────────────────────────────────┘
│  xgs600     │
│  frg702     │   ┌─────────────────────────────────────────────┐
└─────────────┘   │               data/                         │
                  │  data_buffer.py  ·  data_logger.py          │
                  └─────────────────────────────────────────────┘
```

- **`hardware/`**: Low-level device drivers. Each module corresponds to one physical instrument. They are stateless where possible and communicate only with their specific device.
- **`core/`**: The data acquisition engine. Runs a background polling thread that calls all hardware readers on each tick and dispatches results via callbacks.
- **`control/`**: The control logic layer. Contains the block-based program executor, the PID controller, and the safety monitor. Runs in its own background thread.
- **`data/`**: In-memory ring buffer and CSV file logger. Decoupled from hardware and control.
- **`gui/`**: Tkinter-based user interface. Consumes data from the buffer and dispatches user commands to the control and acquisition layers. Receives all updates via thread-safe callbacks marshalled through Tkinter's `root.after()` mechanism.

### 4.2 Threading Model

The application uses four concurrent threads:

| Thread | Owner | Responsibility |
|--------|-------|----------------|
| **Main (GUI) thread** | Tkinter | All GUI rendering, user input, callback dispatch via `root.after()` |
| **DAQ thread** | `DataAcquisition` | Polls all sensors at the configured sample rate; fires `on_new_data` callback |
| **Executor thread** | `ProgramExecutor` | Runs the block-based heating program; writes DAC setpoints; calls status callbacks |
| **Ramp-down thread** | `SafetyMonitor` | Executes the 5-minute emergency voltage ramp-down when the 2200 °C limit is breached |

All shared state (data buffer, PID state, safety monitor status) is protected by `threading.Lock()`. Callbacks from background threads to the GUI are always dispatched via `root.after(0, callback)` to ensure they execute on the main thread and are safe for Tkinter widget updates.

### 4.3 Data Flow During a Live Run

1. `DataAcquisition` polls all sensors every tick (default: 1000 ms).
2. Raw readings dictionary (`{'TC_1': 1200.5, 'FRG702_Chamber': 2.3e-7, 'PS_Voltage': 3.4, ...}`) is passed to the `on_new_data` callback.
3. `main_window.on_new_data()` (on GUI thread) routes readings to:
   - `DataBuffer.add_reading()` — appends to rolling in-memory buffer.
   - `DataLogger.log_reading()` — writes one CSV row and flushes to disk.
   - `SafetyMonitor.check_limits()` — checks all temperature readings against configured limits.
   - All live plot instances — calls `update()` to redraw matplotlib canvas.
   - `SensorPanel.update()` — updates numeric readout tiles.
4. Concurrently, `ProgramExecutor` (in its own thread) reads current temperature via its registered callback, computes the next voltage setpoint, and calls `power_supply.set_voltage()` every ~0.5 seconds.
5. If a safety limit is exceeded, `SafetyMonitor` fires `on_limit_exceeded()`, which propagates through `main_window` to disable all GUI controls and call `emergency_off()` on the power supply panel.

---

## 5. Hardware Abstraction Layer

### 5.1 `labjack_connection.py` — LabJack T8 Interface

**Class: `LabJackConnection`**

This module provides a thin wrapper around the LJM (LabJack Modbus) C library accessed via the `labjack.ljm` Python binding. It encapsulates the connection lifecycle (open, configure, close) and exposes generic register read/write methods.

**Key methods:**
- `open(device_type="T8", connection_type="ANY", identifier="ANY")` — Calls `ljm.openS()` to establish a USB connection to the first available T8 device. Returns a device handle.
- `read_name(handle, name)` — Calls `ljm.eReadName()` to read a single named register (e.g., `"AIN0"`, `"DEVICE_NAME_DEFAULT"`).
- `write_name(handle, name, value)` — Calls `ljm.eWriteName()` for single register writes (e.g., `"DAC0"`, `"FIO1_STATE"`).
- `read_names(handle, names)` — Calls `ljm.eReadNames()` for batch reading multiple registers in a single USB transaction. Used for thermocouple batch reads to minimize latency.
- `write_names(handle, names, values)` — Batch write.
- `close(handle)` — Calls `ljm.close()` to release the device handle.

**Error handling:** LJM errors raise `ljm.LJMError`, which is caught at the calling layer and converted to `None` return values or logged warnings. The connection class itself does not swallow errors — it propagates them to allow callers to decide on recovery strategy.

### 5.2 `thermocouple_reader.py` — Temperature Measurement

**Class: `ThermocoupleReader`**

The T8's Extended Feature (EF) system allows thermocouple temperature to be read directly from an AIN channel as a floating-point temperature value, with cold-junction compensation performed in T8 firmware. Configuration requires writing EF type registers before reading.

**Initialization sequence** (per channel, via `eWriteName`):
1. `AIN{N}_EF_INDEX` = thermocouple type code (e.g., 22 for Type-C, 20 for Type-K, etc.)
2. `AIN{N}_EF_CONFIG_A` = temperature unit (1 = °C, 0 = K)
3. `AIN{N}_NEGATIVE_CH` = channel number of the negative differential input (or 199 for single-ended ground reference)

**Reading:** A batch call to `eReadNames` reads all configured EF result registers (`AIN{N}_EF_READ_A` for each channel N) in a single USB transaction, returning temperature values directly.

**Error handling:** The T8 returns `-9999.0` for invalid readings (open circuit, out-of-range, sensor fault). The reader converts any value equal to `-9999.0` to `None`, which propagates through the data pipeline as a missing reading rather than a spurious temperature value.

### 5.3 `keysight_analog_controller.py` — Power Supply Control

**Class: `KeysightAnalogController`**

Since the Keysight N5700 is controlled via analog signals rather than VISA/GPIB, this module does not perform any serial communication. Instead, it drives DAC0 and DAC1 on the LabJack T8 and reads AIN4/AIN5 for monitoring.

**Signal scaling:**
- Voltage setpoint: `DAC0_voltage = target_V × (5.0 / 6.0)` (maps 0–6 V range to 0–5 V DAC range)
- Current ceiling: `DAC1_voltage = target_A × (5.0 / 180.0)` (maps 0–180 A range to 0–5 V DAC range)
- Voltage monitor: `actual_V = AIN4_voltage × (6.0 / 5.0)`
- Current monitor: `actual_A = AIN5_voltage × (180.0 / 5.0)`

**Interlock check:** Before writing a new voltage setpoint, the module reads the state of FIO1 (the shutdown signal line). If FIO1 indicates an active interlock (power supply in shut-off state), the write is suppressed and the condition is logged. This prevents the control loop from fighting the hardware interlock.

**Key methods:**
- `set_voltage(v)` — Writes scaled value to DAC0 after interlock check.
- `set_current(a)` — Writes scaled value to DAC1.
- `get_voltage()` — Reads AIN4 and returns actual output voltage.
- `get_current()` — Reads AIN5 and returns actual output current.
- `output_on()` / `output_off()` — Drives FIO1 to enable/disable power supply output per SW1-5 polarity.
- `emergency_shutdown()` — Immediately drives FIO1 and sets both DACs to zero.

### 5.4 `xgs600_controller.py` — Vacuum Gauge Controller

**Class: `XGS600Controller`**

This module implements the XGS-600 RS-232 command protocol over a PySerial connection. The XGS-600 uses a simple ASCII request-response protocol with a configurable slave address byte.

**Configuration:** COM4, 9600 baud, 8N1, no flow control, 1.0 s timeout. Address byte defaults to `"00"` for RS-232 single-device mode.

**Protocol:** Commands are framed as `@{address}{command_code}\r` and responses are parsed by stripping the echo and extracting pressure values. The module enforces a minimum 200 ms inter-command delay to prevent bus overruns.

**Key methods:**
- `connect()` / `disconnect()` — Open/close serial port.
- `read_pressure(sensor_code)` — Queries a specific gauge head (e.g., `"T1"`, `"T2"`) and returns pressure in the configured unit.
- `read_all()` — Queries all configured gauge heads in sequence.
- `is_connected()` — Returns True if serial port is open.

### 5.5 `frg702_reader.py` — Full-Range Pressure Gauge

**Class: `FRG702Reader`**

This module supports two operating modes, selectable in settings:

1. **XGS600 mode** (default): Reads pressure values and status from the XGS-600 controller via the `XGS600Controller`. Returns gauge status (valid, Pirani-only, underrange, overrange, error, no supply) alongside the numeric pressure value.
2. **Analog mode**: Reads a 0–10 V analog output from the FRG-702 (if equipped) via a T8 AIN channel. Converts voltage to pressure using the logarithmic calibration curve specified in the FRG-702 datasheet.

**Status reporting:** `read_all_with_status()` returns a dictionary per gauge with keys `pressure`, `status`, and `mode` (Combined or Pirani-only). The GUI uses this to display color-coded status indicators (green = valid combined, yellow = Pirani-only, red = error states).

---

## 6. Data Acquisition Core

### 6.1 `data_acquisition.py` — Polling Engine

**Class: `DataAcquisition`**

The data acquisition engine runs a background thread that polls all enabled sensor channels on every tick and dispatches results to registered callbacks. It is the single aggregation point for all hardware readings.

**Tick behavior:**
1. Reads all enabled thermocouple channels (batch LJM read).
2. Reads FRG-702 pressure values (XGS-600 or analog, depending on config).
3. Reads power supply actual voltage and current (AIN4, AIN5).
4. Reads the current voltage setpoint from the controller (for logging as `PS_Voltage_Setpoint`).
5. Reads the current current limit from the controller (for logging as `PS_CC_Limit`).
6. Assembles all readings into a single dictionary with string sensor names as keys.
7. Fires the `on_new_data(readings)` callback.

**Threading:** The polling loop runs in a daemon thread. Sleep between ticks is calculated to maintain the configured sample rate, accounting for the time spent in hardware reads. If a hardware read takes longer than one tick period, the next tick begins immediately (no backlog accumulation).

**Practice mode:** When launched with `--practice`, the polling thread generates synthetic sensor data: sinusoidal temperature profiles across all TC channels, a simulated pressure decay curve, and mock power supply readings. This allows full GUI validation and CSV format verification without any physical hardware connection.

**Sample rate configuration:** The internal acquisition rate is independently configurable from the display refresh rate. Acquisition rate governs how often hardware is polled and data is logged. Display rate governs how often the GUI plots are redrawn. Both are configurable from 100 ms to 2000 ms.

### 6.2 Sensor Naming Convention

All sensor readings are identified by string names that are consistent across the acquisition, buffer, logger, and GUI layers:

| Prefix | Meaning | Example |
|--------|---------|---------|
| `TC_` | Thermocouple temperature | `TC_1`, `TC_AIN0_C` |
| `FRG702_` | FRG-702 vacuum pressure gauge | `FRG702_Chamber`, `FRG702_T1` |
| `PS_Voltage` | Actual power supply output voltage | `PS_Voltage` |
| `PS_Current` | Actual power supply output current | `PS_Current` |
| `PS_Voltage_Setpoint` | Commanded voltage (DAC0 value) | `PS_Voltage_Setpoint` |
| `PS_CC_Limit` | Commanded current ceiling (DAC1 value) | `PS_CC_Limit` |

Custom names (configured in the settings dialog) are used for TC and FRG-702 channels. These names appear in CSV column headers, live plot legends, sensor panel tiles, and the PID controller's thermocouple selection. The naming convention is enforced consistently throughout.

---

## 7. Control System

### 7.1 Block-Based Program Architecture

Rather than a scripting interface, the system uses a **block-based sequencer**: a heating program is defined as an ordered list of discrete control blocks, each specifying a complete control objective. This design offers several advantages:

- **Repeatability**: Programs are serializable to JSON and can be saved and reloaded.
- **Visualization**: A forward-simulation preview can be computed from any block list before execution, giving the user a time-series prediction of voltage and temperature.
- **Modularity**: Blocks can be reordered, duplicated, and edited independently.
- **QMS gating**: A block can be configured to pause execution at its completion and wait for user confirmation before proceeding, enabling synchronized multi-instrument workflows.

**Block types (`program_block.py`):**

**`VoltageRampBlock`**
```
start_voltage: float   # Initial DAC0 voltage (V)
end_voltage:   float   # Final DAC0 voltage (V)
duration_sec:  float   # Ramp duration (seconds)
pid_active:    bool    # If True, PID runs in monitoring mode (no output)
```
Linearly interpolates the DAC0 voltage setpoint from `start_voltage` to `end_voltage` over `duration_sec`. The current ceiling (DAC1) remains unchanged. This is the primary block type for open-loop heating.

**`StableHoldBlock`**
```
target_temp_k:    float   # Target temperature (Kelvin)
tolerance_k:      float   # Stability band (±K)
hold_duration_sec: float  # Duration to maintain stability before completing
qms_trigger:      bool    # Pause execution at block end for QMS confirmation
```
Uses PID feedback to drive and hold the specimen at `target_temp_k`. The block does not complete until the measured temperature has stayed within `±tolerance_k` of the setpoint for `hold_duration_sec` consecutive seconds.

**`TempRampBlock`**
```
rate_k_per_min: float   # Heating rate (K/min; negative = cooling)
end_temp_k:     float   # Target end temperature (Kelvin)
tc_name:        str     # Thermocouple name to use as PID feedback
```
Ramps the temperature setpoint linearly at `rate_k_per_min` from the current temperature to `end_temp_k`, using PID feedback to track the moving setpoint. This is the primary block for TDS experiments, where a constant temperature ramp rate is essential for reproducible desorption spectra.

### 7.2 `program_executor.py` — Block Execution Engine

**Class: `ProgramExecutor`**

The executor runs in a dedicated background thread and steps through the block list sequentially. Each block is executed by a dedicated `_execute_block()` method that runs in a tight loop (~0.5 s tick rate) until the block's completion condition is met.

**Lifecycle:**
- `load_program(blocks)` — Stores block list and resets state.
- `start()` — Enables power supply output, resets PID integrator, launches executor thread.
- `stop()` — Sets `_running = False`, joins thread with 2 s timeout, sets DAC0 and DAC1 to zero for safety.
- `is_running()` — Returns True if thread is alive and `_running` flag is set.

**VoltageRamp execution:**
```python
v = start_v + (end_v - start_v) * (elapsed / duration_sec)
power_supply.set_voltage(clamp(v, 0.0, 6.0))
```
Linear interpolation, ticked every ~0.5 s.

**StableHold execution:**
- PID computes `correction = pid.compute(target_temp_k, current_temp_k, now)`.
- Output voltage: `v_out = clamp(ff_voltage + correction, 0.0, 6.0)`.
- Feedforward voltage (`ff_voltage`) is the last known stable voltage from the previous block's end, providing a warm-start estimate that reduces PID transients.
- Completion condition: `|current_temp_k - target_temp_k| <= tolerance_k` held for `hold_duration_sec` seconds continuously. The stability timer resets if the temperature drifts outside the band.

**TempRamp execution:**
- Setpoint advances each tick: `setpoint_k = start_temp_k + rate_k_per_sec × elapsed`.
- Setpoint is capped at `end_temp_k` when the end temperature is reached.
- **Cold-start current protection:** If measured current exceeds 120 A and the new voltage setpoint is higher than the previous one, the voltage is held constant for that tick. This prevents overcurrent during the early phase of heating when tungsten resistance is still low.
- Each tick logs `(elapsed, setpoint_k, actual_k, voltage_v)` to an in-memory run log.

**QMS trigger gating:**
After a block with `qms_trigger=True` completes, the executor:
1. Fires `on_waiting_for_confirmation(message)` callback to the GUI.
2. Waits on a `threading.Event` with 0.5 s poll intervals.
3. Resumes when `confirm_and_continue()` is called (either by user button click or the QMS autoclicker).

**Status callback (fired every tick):**
```python
{
    'block_index':   int,
    'block_type':    str,
    'elapsed_sec':   float,
    'current_temp_k': float,
    'voltage_v':     float,
    'ff_voltage':    float,
    'pid_p':         float,
    'pid_i':         float,
    'd_term':        float
}
```

### 7.3 PID Controller (`temp_ramp_pid.py`)

**Class: `PIDController`**

A discrete-time proportional-integral-derivative controller with anti-windup and derivative filtering.

**Default gains:**
```
Kp = 1.0    (proportional)
Ki = 0.05   (integral)
Kd = 0.05   (derivative)
output_min = 0.0    (voltage correction cannot be negative)
output_max = 1.5    (max correction = 1.5 V, 150% of nominal headroom)
integral_windup_limit = 30.0  (K·s)
```

**Algorithm (`compute(setpoint_k, measured_k, current_time)`):**

1. Compute timestep: `dt = current_time - prev_time`.
2. Compute error: `e = setpoint_k - measured_k`.
3. **Integral with anti-windup:**
   ```python
   integral += e * dt
   integral = clamp(integral, -windup_limit, +windup_limit)
   ```
   Clamping the integral accumulator prevents integrator windup: the condition where prolonged output saturation causes the integral term to grow unboundedly, leading to large overshoot when the system eventually responds.

4. **Derivative-on-measurement:**
   ```python
   derivative = -(measured_k - prev_measured_k) / dt
   ```
   The derivative is computed on the negative rate of change of the measurement rather than the rate of change of the error. This avoids the "derivative kick" — the large instantaneous derivative spike that occurs when the setpoint changes abruptly.

5. **PID output:**
   ```python
   output = Kp * e + Ki * integral + Kd * derivative
   output = clamp(output, output_min, output_max)
   ```

6. **Slew-rate limiting (applied in executor):** The ProgramExecutor limits the change in voltage setpoint to ±0.050 V per tick, preventing the PID from commanding abrupt voltage steps that could damage the specimen or power supply.

**`reset()`**: Clears integral accumulator and previous-state variables. Called at the start of each new program.

**`update_gains(kp, ki, kd)`**: Allows real-time gain adjustment without constructing a new controller instance. Useful for mid-run tuning.

**Soft-start constants (defined at module level):**
```python
SOFT_START_THRESHOLD_C  = 150.0   # °C — switch from soft-start to PID above this
SOFT_START_VOLTAGE_STEP = 0.010   # V/tick — open-loop ramp rate during phase 1
SOFT_START_CURRENT_LIMIT = 120.0  # A — current ceiling during phase 1
SOFT_START_RATE_CEILING  = 3.0    # K/min — max heating rate in phase 1
PID_MAX_VOLTAGE_STEP_V   = 0.050  # V/tick — PID output slew limit
```

Below `SOFT_START_THRESHOLD_C`, the executor uses a pure open-loop voltage ramp (`SOFT_START_VOLTAGE_STEP` per tick). If current exceeds `SOFT_START_CURRENT_LIMIT`, the ramp pauses. If the heating rate exceeds `SOFT_START_RATE_CEILING`, the ramp pauses. Once the specimen temperature crosses the threshold, PID control takes over. This two-phase approach protects against the instability inherent in controlling a highly nonlinear load (tungsten) in its cold, low-resistance state.

### 7.4 PID Run Logger and Auto-Tuning Suggestions

**Class: `PIDRunLogger`**

After every `TempRampBlock` completes, the executor computes performance metrics and passes them to `PIDRunLogger.save_run()`. Metrics are computed from the in-memory tick log:

- **Settling time:** The elapsed time at which the error first enters and remains within ±2 K for at least 10 consecutive ticks.
- **Overshoot:** Maximum value of `(actual_temp - setpoint_temp)` during the run.
- **Oscillation count:** Number of zero-crossings of the error signal `(actual_temp - setpoint_temp)`.
- **Achieved rate:** `(final_temp - start_temp) / elapsed_time` in K/min.
- **Rate tracking error:** `|target_rate - achieved_rate| / target_rate × 100%`.

The logger appends each run record (with timestamp, gains used, and computed metrics) to `logs/pid_runs.json`, keeping the last 100 runs. It also auto-generates tuning suggestions:

| Condition | Suggestion |
|-----------|-----------|
| Rate error > 25% | Increase Ki to improve steady-state following |
| Rate error 10–25% | Minor Ki increase may help |
| Overshoot > 10 K | Reduce Kp or increase Kd |
| Overshoot 5–10 K | Slight Kp reduction or Kd increase |
| Oscillation count > 8 | Reduce Ki or increase Kd |
| Oscillation count 4–8 | Kd increase may smooth response |
| Settling time = None | Significant re-tuning required |
| Settling time > 120 s | Increase Ki to reduce steady-state error |
| All within bounds | Performance looks good |

This provides the operator with actionable, data-driven feedback for iterative PID tuning without requiring expertise in control theory.

---

## 8. Safety System

### 8.1 Architecture and Design Philosophy

**Class: `SafetyMonitor`** (`safety_monitor.py`)

The safety system is designed around the principle that **temperature control failures in a high-power resistive heating system can cause irreversible specimen damage, equipment failure, or physical hazard**. The safety monitor therefore operates independently of the control layer and has direct access to the power supply for emergency shutdown.

The monitor implements a three-tier escalation model:

1. **Warning** (configurable threshold, default 90% of limit): GUI status bar turns yellow; operator is notified but execution continues.
2. **Limit Exceeded** (at the configured limit): Power supply output is disabled; program execution is halted; GUI shows red alert; restart is blocked until the operator manually resets.
3. **Hard Override at 2200 °C**: A hardware-level temperature ceiling that triggers a controlled 5-minute voltage ramp-down and applies a restart lockout that prevents re-enabling the power supply until the temperature has dropped below 2150 °C.

### 8.2 Configurable Limits and Debouncing

Per-sensor temperature limits are set via `set_temperature_limit(sensor_name, max_temp)`. Each limit applies to one named thermocouple channel. A separate `_violation_counts` dictionary tracks how many consecutive polling ticks each sensor has exceeded its limit. The `set_debounce_count(n)` method configures how many consecutive violations are required before an emergency shutdown is triggered (default: 1, i.e., immediate). This debounce mechanism prevents false shutdowns from single spurious readings.

A "watchdog sensor" can be designated via `set_watchdog_sensor(sensor_name)`. This sensor bypasses the debounce count and triggers immediately on any violation, regardless of the global debounce setting.

### 8.3 The 2200 °C Hard Override

The hard override is implemented as an absolute ceiling that operates independently of any user-configured limits. When any thermocouple reading reaches or exceeds 2200 °C, the safety monitor:

1. Records a `SafetyEvent` with `event_type = "temperature_override_rampdown"`.
2. Sets `_restart_locked = True`.
3. Reads the current power supply output voltage as the ramp-down starting point.
4. Launches a dedicated `_rampdown_thread` running `_rampdown_loop()`.
5. Fires the `on_rampdown_start(message)` callback to notify the GUI.

**Controlled ramp-down algorithm (`_rampdown_loop`):**
```python
start_voltage = power_supply.get_voltage()
start_time = time.time()
while running:
    elapsed = time.time() - start_time
    if elapsed >= RAMPDOWN_DURATION_SEC:   # 300 s
        break
    fraction_remaining = max(0.0, 1.0 - (elapsed / RAMPDOWN_DURATION_SEC))
    power_supply.set_voltage(start_voltage * fraction_remaining)
    time.sleep(1.0)
power_supply.set_voltage(0.0)
power_supply.set_current(0.0)
power_supply.output_off()
```

The 5-minute (300 s) ramp-down duration was chosen to avoid thermal shock to the specimen and heater assembly while still achieving a controlled shutdown. An instantaneous power cutoff at extreme temperatures could cause thermal stress fractures in the specimen or damage to the thermocouple-specimen junction.

### 8.4 Restart Lockout

After any emergency shutdown (whether from the hard override or a user-configured limit), `_restart_locked = True` prevents re-enabling the power supply. The GUI's "Reset Safety" button calls `can_restart()`, which returns `True` only when the maximum measured thermocouple reading has dropped below `TEMP_RESTART_THRESHOLD` (2150 °C). This ensures the operator cannot inadvertently restart heating before the system has cooled to a safe state.

### 8.5 Safety Events

Every safety-relevant event is captured as a `SafetyEvent` dataclass:
```python
@dataclass
class SafetyEvent:
    timestamp: datetime
    event_type: str
    sensor_name: str
    value: float
    limit: float
    message: str
```

The last 100 events are maintained in `_event_history`. The GUI can display this history to the operator for post-incident review.

---

## 9. Data Management

### 9.1 `data_buffer.py` — In-Memory Ring Buffer

**Class: `DataBuffer`**

The data buffer provides thread-safe, bounded storage of recent sensor readings for live plot rendering. It is implemented using Python's `collections.deque` with a fixed `maxlen`, which automatically evicts the oldest entry when the buffer is full, providing O(1) append with no manual pruning.

**Design:**
- One master `timestamps` deque (the time axis).
- One `data` deque per sensor name (the value axes).
- All deques are kept at identical length at all times: when a new sensor appears mid-run, its deque is back-filled with `None` for all previous timestamps. When a sensor disappears (read failure), `None` is appended for that tick.

**Configuration:**
- `max_seconds = 60` (default): buffer stores the last 60 seconds of data.
- `sample_rate_ms = 100` (default): expected inter-sample interval, used to pre-compute `maxlen`.
- Setting `max_seconds = None` creates an unlimited buffer (used for loaded CSV replay).

**Public API:**
- `add_reading(sensor_readings: dict)` — Thread-safe append of one tick.
- `get_sensor_data(sensor_name)` — Returns `(timestamps_list, values_list)`.
- `get_all_current()` — Returns dict of most recent values per sensor.
- `get_all_data()` — Returns full buffer content per sensor.
- `get_sensor_names()` — Returns list of all sensor names.
- `clear()` — Empties all buffers.

### 9.2 `data_logger.py` — CSV File Logging

**Class: `DataLogger`**

The data logger writes sensor readings to CSV files with an embedded JSON metadata header, providing a self-describing file format that retains experimental context alongside the raw data.

**File format:**
```
#META:{"start_time": "2026-03-26T14:30:00.123456", "sensors": ["TC_1", "FRG702_Chamber", "PS_Voltage"], "tc_count": 1, "tc_type": "C", ...}
Timestamp,TC_1,FRG702_Chamber,PS_Voltage,PS_Current,PS_Voltage_Setpoint,PS_CC_Limit
2026-03-26T14:30:00.456789,23.5,1.23e-07,0.0,0.0,0.0,180.0
2026-03-26T14:30:01.456789,24.1,1.21e-07,0.1,15.3,0.1,180.0
...
#END_TIME:2026-03-26T15:45:30.654321
```

**Value formatting:**
- FRG-702 pressures: scientific notation (`1.23e-07`) for readability across the wide dynamic range.
- Power supply voltages: 4 decimal places.
- Power supply currents: 3 decimal places.
- Thermocouple temperatures: as returned by the hardware (typically 1–2 decimal places).
- Missing values: empty string (blank CSV cell).

**Event rows:** Special events can be logged inline with `log_event(event_name, detail)`, producing rows like:
```
2026-03-26T14:35:00.000000,EVENT:RAMP_START,VoltageRamp block 0
2026-03-26T14:40:00.000000,EVENT:QMS_TRIGGER,StableHold complete at 1200K
```

This allows post-run analysis tools to correlate data with experimental milestones without requiring a separate event log file.

**File naming:** `data_log_{safe_name}_{YYYYMMDD_HHMMSS}.csv`. The `safe_name` component is the user-entered run name with special characters removed. If no name is entered, the filename is timestamp-only.

**`load_csv_with_metadata(filepath)`** (class method): Parses a log file and returns `(metadata_dict, data_dict)` suitable for direct replay in the GUI's historical data viewer. Timestamps are parsed to `datetime` objects; numeric values are converted to `float`. Malformed rows are skipped silently.

---

## 10. Graphical User Interface

### 10.1 Overview and Technology

The GUI is built with Python's standard **Tkinter** library, using the **matplotlib TkAgg backend** for embedded live plotting. This choice prioritizes portability and zero additional runtime dependencies — Tkinter is included with CPython, and the application ships as a standalone Windows executable.

The main window (`main_window.py`, ~2000 lines) acts as the central orchestrator: it constructs all hardware objects, wires all callbacks, manages run state, and routes all user interactions to the appropriate subsystem.

### 10.2 Main Window Layout

```
┌─────────────────────────────────────────────────────────────────┐
│ File    Settings    Help                          [Menu Bar]    │
├─────────────────────────────────────────────────────────────────┤
│ ● System Ready — No active program                [Status Bar] │
├─────────────────────────────────────────────────────────────────┤
│ ┌──────────┬──────────┬──────────┬────────────┬──────────────┐ │
│ │ Sensors  │ Temp Plot│ Press Plot│ PS Plot   │  Programmer  │ │
│ │          │          │          │            │  Pinout      │ │
│ └──────────┴──────────┴──────────┴────────────┴──────────────┘ │
│                                                                 │
│             [Tab Content Area]                                  │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  [Start DAQ] [Stop] [Load CSV] [Settings]   Rate: [1000ms ▼]  │
└─────────────────────────────────────────────────────────────────┘
```

**Status bar:** Color-coded — green (OK/idle), yellow (warning threshold reached), red (emergency shutdown triggered). Text provides human-readable status for the current system state.

### 10.3 Sensor Panel (`sensor_panel.py`)

The sensor panel displays current readings as a grid of fixed-size tiles. Each tile contains the sensor name, a large-font numeric value, a units label, and a status indicator.

**Thermocouple tiles (206 × 90 px):** Show temperature in the configured unit (°C, K, or °F). Status indicator shows "CONNECTED" (green), "WAITING" (gray), or an error code.

**FRG-702 tiles (240 × 120 px):** Show pressure in scientific notation. A 12×12 px colored circle indicates gauge status:
- **Green**: Valid, combined mode (Pirani + cold cathode both active).
- **Yellow**: Valid, Pirani-only mode (cold cathode offline; typically pressure too high to ignite).
- **Red**: Error states (underrange, overrange, sensor error, no supply voltage).
- **Gray**: Disconnected or no data.

**Click-to-toggle visibility:** Each sensor tile responds to mouse clicks (`<Button-1>`). Clicking toggles the sensor's visibility in the live plots. Hidden sensors are shown with a dimmed gray style. This allows the operator to declutter the plot view without modifying the sensor configuration.

**Power supply tiles:** Show actual voltage and current with connection status. Display "Output is turned off" when the output is disabled.

### 10.4 Live Plots (`live_plot.py`)

Three independent `LivePlot` instances handle the three sensor categories:

- **Temperature plot** (`plot_type='tc'`): Linear Y-axis, all thermocouple channels, configurable absolute scale (default 0–2500 °C).
- **Pressure plot** (`plot_type='pressure'`): Logarithmic Y-axis, all FRG-702 channels, configurable absolute scale (default 10⁻⁹–10⁻³ mbar).
- **Power supply plot** (`plot_type='ps'`): Dual Y-axis — voltage (left, 0–6 V) and current (right, 0–180 A) — with additional lines for voltage setpoint and current ceiling.

**Dual-mode scrollbar:** Each plot has a horizontal scrollbar for browsing history:
- **Live mode** (scrollbar at 1.0): The plot auto-advances, always showing the most recent 2-minute window.
- **Frozen mode** (scrollbar < 0.98): The plot shows a fixed 2-minute window at the chosen historical position. A status label changes from "● LIVE" (green) to the timestamp range being viewed.
- Dragging the scrollbar back to 1.0 automatically resumes live mode.

**Programmer overlay:** When a block program is loaded, the power supply plot renders a dotted preview line showing the expected voltage trajectory over time, computed by `ProgramExecutor.compute_preview()`.

**Historical data replay:** `update_from_loaded_data(loaded_data)` replaces the live buffer with data loaded from a CSV file, enabling post-run analysis within the same GUI.

### 10.5 Power Programmer Panel (`power_programmer_panel.py`)

The programmer panel provides a block-based editor for defining heating programs:

- **Block list table** (Treeview): Displays all blocks with their key parameters. Supports add, delete, move-up, move-down via toolbar buttons.
- **Block edit dialog** (modal): Double-clicking a block opens a type-specific form with input validation.
- **Safe Test Mode checkbox**: When enabled, clamps voltage to ≤ 1 V and current to ≤ 10 A for bench-testing program logic without specimen.
- **Preview plot**: A `ProgrammerPreviewPlot` instance renders the computed time-series temperature and voltage trajectory. A real-time animated dot tracks the current execution position during a live run.
- **Profile save/load**: Programs are serialized to JSON files for reuse across experimental sessions.

**Block edit dialog fields by block type:**

| Block Type | Fields |
|-----------|--------|
| VoltageRamp | Start Voltage (V), End Voltage (V), Duration (s), PID Active (checkbox) |
| StableHold | Target Temperature (°C or K), Tolerance (K), Hold Duration (s), QMS Trigger (checkbox) |
| TempRamp | TC Name (dropdown), Target Temperature, Rate (K/min) or Time Target, Entry Mode |

Temperature fields support display in either °C or K, with internal storage always in Kelvin.

### 10.6 Settings Dialog (`settings_dialog.py`)

A six-tab modal dialog provides access to all configurable parameters:

1. **Sensors**: Thermocouple count (0–8), type per channel, temperature unit, FRG-702 count and names, pressure unit, custom sensor names.
2. **Hardware**: XGS-600 COM port selection, power supply interface selection.
3. **Scales**: Absolute vs auto-scaling toggle, axis ranges for temperature, pressure, voltage, current. Sample rate configuration.
4. **Paths**: Log folder path, program profiles folder path.
5. **Power Programmer / PID**: Default ramp parameters, PID gains (Kp, Ki, Kd), windup limit, max output, soft-start threshold and current limit.
6. **QMS Trigger**: Enable/disable auto-click, click coordinate entry, "Capture Location (3s)" interactive capture, "Test Click" verification.

All settings are immediately persisted to the Windows Registry via `AppSettings.save()` on dialog confirmation.

### 10.7 Pre-flight Checklist (`preflight_dialog.py`)

Before the first DAQ run, a modal dialog presents a dynamically-generated checklist of physical wiring verifications based on the current configuration. Each item is a checkbox with a specific wiring instruction (e.g., "Pin 12 (GND Reference) wired to AIN4−/AIN5− ONLY — NOT to T8 GND"). The "Start DAQ" button is only enabled when all checkboxes are ticked.

The operator can click "Skip (I know what I'm doing)" — this logs a warning and proceeds. A `skip_preflight_check` registry flag allows the dialog to be suppressed entirely for experienced operators.

### 10.8 Live Pinout Display (`pinout_display.py`)

A two-tab panel showing:

1. **Pin Table**: A scrollable table listing every active signal with its pin number, signal name, type, thermocouple type, units, current status (live/stale indicator), raw voltage, and live value.
2. **Wiring Diagram**: A canvas-based schematic showing the LabJack T8, Keysight N5700, XGS-600, and specimen chamber as labeled boxes with connecting wires, live status indicators on each connection line, and pin number labels.

The display refreshes every 200 ms. Status indicators distinguish between live data (●, filled) and stale/absent data (○, hollow).

### 10.9 QMS Autoclicker

When a `StableHoldBlock` with `qms_trigger=True` completes, the executor pauses and fires the `on_program_paused(reason)` callback. The GUI displays a confirmation banner: "Start QMS + Continue Ramp." If QMS auto-click is enabled in settings, the system:

1. Uses `pygetwindow` to identify the QMS software window.
2. Uses `pyautogui.click(x, y)` to click the pre-configured screen coordinate.
3. Logs a `QMS_TRIGGER` event row to the CSV.
4. Calls `program_executor.confirm_and_continue()` to resume execution.

The click coordinates are configured interactively: the settings dialog offers a "Capture Location (3s)" button that starts a countdown and records the cursor position when it expires, allowing the operator to position the cursor over the QMS start button before the countdown ends.

---

## 11. Settings and Persistence

**Class: `AppSettings`** (`settings/app_settings.py`)

All application settings are persisted to the Windows Registry at `HKEY_CURRENT_USER\Software\T8_DAQ_System`. This eliminates external configuration files and provides per-user isolation on shared laboratory computers.

**All configurable parameters (with defaults):**

| Category | Parameter | Default | Description |
|----------|-----------|---------|-------------|
| **Sensors** | `tc_count` | 1 | Number of thermocouple channels |
| | `tc_type` | "C" | Default TC type |
| | `tc_types` | "" | Comma-separated per-channel types |
| | `tc_pins` | "" | Comma-separated AIN channel numbers |
| | `tc_names` | "" | Custom TC names |
| | `tc_unit` | "C" | Display unit (C, F, K) |
| | `frg_count` | 1 | Number of FRG-702 gauges |
| | `frg_names` | "" | Custom gauge names |
| | `frg_pins` | "AIN6,AIN7" | AIN pins for analog pressure |
| | `p_unit` | "mbar" | Pressure unit |
| **Acquisition** | `sample_rate_ms` | 1000 | Hardware poll interval (ms) |
| | `display_rate_ms` | 1000 | GUI update interval (ms) |
| **Axis Scales** | `use_absolute_scales` | True | Fixed vs auto-scale |
| | `temp_range_min/max` | 0.0 / 2500.0 | Temperature axis (°C or K) |
| | `press_range_min/max` | 1e-9 / 1e-3 | Pressure axis (mbar) |
| | `ps_v_range_min/max` | 0.0 / 6.0 | Voltage axis (V) |
| | `ps_i_range_min/max` | 0.0 / 180.0 | Current axis (A) |
| **Hardware** | `xgs600_port` | "COM4" | Serial port for XGS-600 |
| | `xgs600_baudrate` | 9600 | Serial baud rate |
| | `xgs_enabled` | False | Enable XGS-600 interface |
| | `ps_enabled` | False | Enable power supply control |
| **Power Supply** | `ps_voltage_limit` | 20.0 | Max output voltage safety ceiling |
| | `ps_current_limit` | 50.0 | Max output current safety ceiling |
| | `ps_interface` | "Analog" | Control method |
| | `ps_voltage_pin` | "DAC0" | DAC channel for voltage setpoint |
| | `ps_current_pin` | "DAC1" | DAC channel for current limit |
| | `ps_voltage_monitor_pin` | "AIN4" | AIN for voltage feedback |
| | `ps_current_monitor_pin` | "AIN5" | AIN for current feedback |
| **PID** | `pid_kp` | 0.02 | Proportional gain |
| | `pid_ki` | 0.001 | Integral gain |
| | `pid_kd` | 0.010 | Derivative gain |
| | `pid_output_max` | 1.5 | Max PID output (fraction) |
| | `pid_windup_limit` | 30.0 | Integral clamp (K·s) |
| **Soft-Start** | `soft_start_threshold_c` | 200.0 | Phase 1 → PID handoff (°C) |
| | `soft_start_current_limit_a` | 120.0 | Phase 1 current ceiling (A) |
| **QMS** | `qms_auto_click_enabled` | False | Enable auto-click |
| | `qms_auto_click_x/y` | 0 / 0 | Screen coordinates |
| **Logging** | `log_folder` | "" | CSV log folder (empty = "logs/") |
| | `skip_preflight_check` | False | Skip pre-flight dialog |

**Helper methods for list-valued settings:**
- `get_tc_type_list(count)`: Parses `tc_types` comma-separated string, padded to `count` with the default `tc_type`.
- `get_tc_pin_list(count)`: Parses `tc_pins` to list of integers, padded with sequential values.
- `get_tc_name_list(count, pin_list, type_list)`: Returns custom names or auto-generated defaults (e.g., `TC_AIN0_C`).
- `get_frg_name_list(count, interface, pin_list)`: Returns custom names or auto-generated defaults (e.g., `FRG702_T1`).

**Registry value types:** Integers stored as `REG_DWORD`; floats and strings as `REG_SZ`. Booleans stored as `REG_DWORD` (0/1). All type conversions are handled transparently by `load()` and `save()`.

---

## 12. Practice Mode

Practice mode provides full GUI and control-logic validation without any physical hardware. It is activated via the `--practice` command-line flag or the startup dialog.

**`MockPowerSupplyController`** (defined in `main_window.py`): A drop-in replacement for the real `KeysightAnalogController`. It maintains an internal `_voltage` and `_current` state. `get_voltage()` and `get_current()` return the stored setpoint values with added sinusoidal noise to simulate realistic meter jitter. When the Power Programmer is actively running (`programmer_active = True`), noise is suppressed so that the preview plot and status displays show clean signals.

**Simulated sensor data:** The `DataAcquisition` polling thread, when in practice mode, generates synthetic readings:
- Thermocouple temperatures: slowly rising sinusoids offset per channel.
- FRG-702 pressure: exponential decay from 10⁻³ to 10⁻⁷ mbar (simulating pump-down).
- Power supply: mirrors the mock controller's setpoints.

**Validation use cases:**
1. Verify CSV column headers and metadata format before a real run.
2. Test PID logic and observe simulated temperature tracking behavior.
3. Validate block program sequencing and QMS trigger gating logic.
4. Check GUI layout, tab navigation, and settings persistence.
5. Verify PyInstaller build integrity without hardware.

---

## 13. Deployment and Distribution

### 13.1 PyInstaller Build Configuration (`t8_daq_system.spec`)

The application is packaged as a standalone Windows folder distribution using PyInstaller. The `.spec` file contains the full build configuration.

**Anaconda environment detection:** The spec automatically detects the `CONDA_PREFIX` environment variable to locate DLL dependencies. If absent, it falls back to a hardcoded path (`C:\Users\IGLeg\anaconda3\Library\bin`). This handles both Anaconda and standard Python environments.

**Critical DLLs bundled:**

| DLL | Purpose |
|-----|---------|
| `LabJackM.dll` | LabJack LJM hardware driver |
| `tcl86t.dll`, `tk86t.dll` | Tkinter runtime |
| `libffi-7.dll`, `libffi-8.dll` | Foreign Function Interface (ctypes) |
| `libcrypto-*.dll`, `libssl-*.dll` | OpenSSL (pyserial TLS) |
| `msvcp140.dll`, `vcruntime140.dll` | MSVC C++ runtime |
| `libbz2.dll`, `liblzma.dll` | Compression (matplotlib font loading) |

**Hidden imports (170+ entries):** PyInstaller's static analysis cannot detect dynamically imported modules. The spec explicitly lists all required modules including `tkinter`, `tkinter.ttk`, `matplotlib.backends.backend_tkagg`, `labjack.ljm`, `pyautogui`, `pygetwindow`, `pyscreeze`, `serial.serialwin32`, and `winreg`.

**Performance optimizations:**
- **Folder-mode distribution** (COLLECT rather than single EXE): The application is distributed as a `dist/T8_DAQ_System/` directory. This avoids the startup latency of single-file extraction but requires distributing the whole folder.
- **UPX disabled**: UPX compression is disabled because DLL decompression on startup adds more latency than the compressed file size saves.
- **Zeroconf disabled**: Network service discovery is disabled in frozen mode, eliminating a noticeable startup delay caused by zeroconf's timeout-based network scan.

**Distribution:** The `dist/T8_DAQ_System/` folder is zipped and distributed to end users. No Python installation is required on the target computer. The LabJack LJM driver must be installed separately on the host.

### 13.2 Startup Profiler (`utils/startup_profiler.py`)

A lightweight startup timing utility (`PROFILER_ENABLED = False` by default) that records named checkpoints during application initialization and prints a summary table identifying slow-loading components. This was used during development to identify PyInstaller bottlenecks (large module imports, DLL loading delays). It can be re-enabled for performance regression testing.

---

## 14. Test Suite

### 14.1 Test Environment

- **Framework**: pytest
- **Configuration** (`pytest.ini`): Test discovery in `tests/` directory, verbose output, short traceback format, local variables printed on failure.
- **Mocking strategy**: All hardware dependencies are mocked at the module level in `conftest.py` via `sys.modules` injection before test collection begins. This ensures tests run on any platform (including Linux-based CI servers) without physical hardware, a display server, or the Windows Registry.

### 14.2 Hardware Mocking (`conftest.py`)

The `conftest.py` file inserts `MagicMock()` objects for the following modules before any test file is imported:

| Mocked Module | Reason |
|---------------|--------|
| `winreg` | Windows-only; unavailable on Linux/macOS CI |
| `labjack.ljm` | Requires LJM driver installation |
| `serial`, `serial.tools.list_ports` | Requires serial hardware or virtual port |
| `tkinter` (all submodules) | Requires display server (X11 or Windows GUI) |
| `matplotlib` (all submodules) | Requires display for rendering |

Custom exception classes (`LJMError`, `SerialException`) are also defined in the mock to allow tests to exercise hardware error-handling paths.

### 14.3 Test Coverage by Module

| Test File | Lines | What is Tested |
|-----------|-------|----------------|
| `test_data_buffer.py` | 77 | Ring buffer initialization, add_reading, FIFO circularity, sensor synchronization, clear |
| `test_data_logger.py` | 72 | CSV creation, header row format, data row writing, log file discovery |
| `test_hardware.py` | 90 | LJM openS/close, AIN EF register configuration, batch reads, -9999 error → None conversion |
| `test_safety_monitor.py` | 120+ | Limit set/remove, warning threshold, violation debounce, shutdown callback, status transitions |
| `test_live_plot.py` | 372 | Axis configuration, color cycles, dual-mode scrollbar (live/frozen), absolute scales, CSV replay |
| `test_dialogs.py` | 237 | Filename sanitization, CSV file discovery, axis scale validation, metadata structure |

### 14.4 Testing Philosophy

The test suite focuses on **core logic correctness** (data structures, algorithms, safety logic) and **structural GUI validation** (axes exist, color cycles defined, scrollbar modes correct) rather than deep interactivity testing. Hardware interface tests use LJM mocks to verify the correct API call sequences without requiring a physical device.

**Identified coverage gaps:**
- No standalone unit tests for `ProgramExecutor` block execution logic or PID step response.
- No integration test for the full DAQ → buffer → logger → plot pipeline.
- No test for XGS-600 serial protocol parsing.
- No test for GUI event handling (button clicks, scrollbar interaction) — requires complex Tkinter event simulation.
- No test for the safety monitor's 2200 °C controlled ramp-down thread.

These gaps are known and are mitigated by the extensive practice-mode validation capability, which exercises the full system end-to-end without hardware.

---

## 15. Known Issues and Future Work

### 15.1 Active Hardware Issues

**Keysight "SO" (Shut-Off) display on run start:**
The Keysight N5700 front panel displays "SO" (Shut-Off active) when the analog programming interface is not properly enabled. Root causes: SW1-1 and SW1-2 not set to UP (analog programming disabled), or SW1-5 polarity mismatch causing the FIO1 shutdown signal to be interpreted incorrectly. Resolution: verify dip-switch configuration per Section 3.3 before every run.

**FIO vs EIO pin mismatch:**
Some code paths reference `EIO0`/`EIO1` register names while the physical wiring uses `FIO0`/`FIO1`. This inconsistency needs to be reconciled across the hardware abstraction layer and verified against the physical wiring of the specific T8 unit.

### 15.2 PID Tuning Status

The PID gains (`Kp = 0.02`, `Ki = 0.001`, `Kd = 0.010` in `AppSettings` defaults; `Kp = 1.0`, `Ki = 0.05`, `Kd = 0.05` in `PIDController` defaults — a discrepancy that should be resolved) have not yet been validated on the physical system. The PID run logger and auto-suggestion system were specifically designed to support iterative gain tuning from real run data. Initial tuning should begin with low gains and the practice mode's simulated ramp to verify step-response behavior before hardware runs.

### 15.3 Potential Improvements

- **PID gain reconciliation**: Resolve the discrepancy between `AppSettings` default gains and `PIDController` default gains. Establish a single source of truth.
- **Soft-start integration test**: Add a unit test that exercises the cold-start current protection logic in `ProgramExecutor`.
- **XGS-600 protocol test**: Add a test using a `MagicMock` serial port to verify command framing and response parsing.
- **Cross-platform settings**: The Windows Registry backend limits the application to Windows. A JSON-file fallback would enable development and testing on Linux/macOS.
- **Rate-adaptive PID**: The current PID gains are fixed for a given run. An adaptive scheme that adjusts Kp based on the measured specimen thermal mass could improve performance across specimens of different sizes.
- **Cascade control**: For very precise TDS ramp rates, a cascade control structure (outer temperature loop commanding an inner voltage loop) could improve disturbance rejection.
- **Web dashboard**: For remote monitoring, a lightweight HTTP server exposing the live data buffer as a JSON endpoint would allow browser-based monitoring without a remote desktop connection.