@echo off
REM ============================================================================
REM  add_firewall_rule.bat
REM  PURPOSE: Add a permanent Windows Firewall exception for T8_DAQ_System.exe
REM
REM  HOW TO USE
REM  ----------
REM  Run this script ONCE as Administrator after placing the distribution
REM  folder on the target machine.  After it runs successfully Windows will
REM  never show a firewall prompt for T8_DAQ_System.exe regardless of which
REM  ethernet cable is plugged in.
REM
REM  You do NOT need to re-run this script when you update the application,
REM  as long as the EXE remains in the same folder.
REM
REM  REQUIREMENTS
REM  ------------
REM  Must be run as Administrator (right-click → "Run as administrator").
REM  The T8_DAQ_System.exe must be in the same folder as this .bat file.
REM ============================================================================

echo.
echo T8 DAQ System — Windows Firewall Rule Installer
echo ================================================
echo.

REM Check for administrator privileges
net session >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: This script must be run as Administrator.
    echo Right-click the .bat file and choose "Run as administrator".
    echo.
    pause
    exit /b 1
)

set EXE_PATH=%~dp0T8_DAQ_System.exe

if not exist "%EXE_PATH%" (
    echo ERROR: T8_DAQ_System.exe not found at:
    echo   %EXE_PATH%
    echo.
    echo Make sure this .bat file is in the same folder as T8_DAQ_System.exe
    echo.
    pause
    exit /b 1
)

echo Adding inbound firewall rule...
netsh advfirewall firewall add rule ^
    name="T8_DAQ_System" ^
    dir=in ^
    action=allow ^
    program="%EXE_PATH%" ^
    enable=yes ^
    profile=any ^
    description="T8 DAQ System — allows pyvisa TCPIP instrument discovery"

if %ERRORLEVEL% neq 0 (
    echo WARNING: Inbound rule may have failed. Try running as Administrator.
) else (
    echo   [OK] Inbound rule added.
)

echo Adding outbound firewall rule...
netsh advfirewall firewall add rule ^
    name="T8_DAQ_System" ^
    dir=out ^
    action=allow ^
    program="%EXE_PATH%" ^
    enable=yes ^
    profile=any ^
    description="T8 DAQ System — allows pyvisa TCPIP instrument communication"

if %ERRORLEVEL% neq 0 (
    echo WARNING: Outbound rule may have failed. Try running as Administrator.
) else (
    echo   [OK] Outbound rule added.
)

echo.
echo Done!  Firewall rules added for:
echo   %EXE_PATH%
echo.
echo You only need to run this script once.
echo Windows will no longer prompt about network access for T8_DAQ_System.exe.
echo.
pause
