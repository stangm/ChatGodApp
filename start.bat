@echo off
setlocal enabledelayedexpansion
title Chat God
cd /d "%~dp0"

REM ===========================================================================
REM  Chat God launcher.
REM
REM  Double-click this. It finds Python, sets up the virtual environment the
REM  first time, starts the app and opens the control panel.
REM
REM  Why a .bat and not a packaged .exe: installing Python once buys everything
REM  a PyInstaller build would, without a build pipeline that breaks on every
REM  dependency bump or an unsigned exe tripping SmartScreen on a streamer's PC.
REM
REM  Why the window stays visible: the first run spends two minutes installing
REM  dependencies, and a hidden window looks like nothing happened. It also
REM  means there's always a last line to read out when something goes wrong.
REM
REM  To use a virtual environment somewhere else, set CHATGOD_VENV to its
REM  folder. Otherwise .venv beside this file is created and used.
REM ===========================================================================

set "APP=chat_god_app.py"
set "URL=http://127.0.0.1:5000/"

echo.
echo   Chat God
echo   --------
echo.

REM --- Already running? -------------------------------------------------------
REM Double-clicking twice is the most likely mistake, and the raw failure is a
REM socket bind error that reads like a crash. Note this check looks for the
REM English word LISTENING, so it silently does nothing on a non-English
REM Windows -- in that case the app still starts and fails with the friendly
REM message at :app_failed, which names this as the likely cause.
netstat -ano | findstr /c:":5000" | findstr /c:"LISTENING" >nul 2>&1
if not errorlevel 1 goto already_running

REM --- Find a virtual environment ---------------------------------------------
set "VENV="
if defined CHATGOD_VENV call :use_if_venv "%CHATGOD_VENV%"
if not defined VENV call :use_if_venv ".venv"
if not defined VENV call :use_if_venv "venv"
if defined VENV goto have_venv

REM --- No venv, so this is a first run -----------------------------------------
echo   First run. Setting things up, which takes a couple of minutes.
echo.

call :find_python
if not defined PY goto no_python

echo   Using !PY!
echo   Creating the virtual environment...
!PY! -m venv .venv
if errorlevel 1 goto venv_failed
set "VENV=.venv"

:have_venv
set "PYEXE=%VENV%\Scripts\python.exe"

REM --- Dependencies -----------------------------------------------------------
REM "Can the app import what it needs" rather than comparing against
REM requirements.txt. It answers the question that actually matters and it's far
REM less fragile in batch than timestamp bookkeeping. Consequence: changing
REM requirements.txt won't retrigger this on its own -- run pip yourself, or
REM delete the venv folder and let this rebuild it.
"%PYEXE%" -c "import flask, flask_socketio, twitchio, pygame, azure.cognitiveservices.speech" >nul 2>&1
if not errorlevel 1 goto deps_ok

echo   Installing dependencies. This is the slow part, and only happens once.
echo.
"%PYEXE%" -m pip install --upgrade pip --quiet
"%PYEXE%" -m pip install -r requirements.txt --quiet
if errorlevel 1 goto pip_failed

"%PYEXE%" -c "import flask, flask_socketio, twitchio, pygame, azure.cognitiveservices.speech" >nul 2>&1
if errorlevel 1 goto pip_failed
echo   Dependencies installed.
echo.

:deps_ok
echo   Starting. The control panel will open in your browser in a moment.
echo.
echo   Leave this window open while you stream.
echo   Closing it stops Chat God.
echo.

REM Open the browser from a separate detached window after a delay, so the app
REM has time to bind port 5000. Doing it before starting the app would race; the
REM app itself runs in the foreground so its output lands in this window.
REM No quotes around the URL: cmd's own parser would take the /c string's inner
REM quotes as the end of it, and "start" treats a quoted first argument as a
REM window title rather than a target. Unquoted is correct here.
start "" /min cmd /c "timeout /t 5 /nobreak >nul & start %URL%"

"%PYEXE%" %APP%
if errorlevel 1 goto app_failed

echo.
echo   Chat God has stopped.
timeout /t 3 /nobreak >nul
exit /b 0


REM ===========================================================================
REM  Subroutines
REM ===========================================================================

:use_if_venv
REM Sets VENV if the given folder looks like a usable virtual environment.
if exist "%~1\Scripts\python.exe" set "VENV=%~1"
goto :eof

:find_python
REM Newest supported first. 3.13+ is excluded deliberately: several pinned
REM dependencies have no wheels for it yet, and the failure is a wall of
REM compiler errors rather than anything readable.
set "PY="
for %%V in (3.12 3.11 3.10 3.9) do call :try_python "py -%%V"
if not defined PY call :try_python "python"
goto :eof

:try_python
if defined PY goto :eof
%~1 -c "import sys; raise SystemExit(0 if (3,9) <= sys.version_info < (3,13) else 1)" >nul 2>&1
if errorlevel 1 goto :eof
set "PY=%~1"
goto :eof


REM ===========================================================================
REM  Failures. Each one names the cause and what to do, and holds the window
REM  open. A traceback on screen is a design failure.
REM ===========================================================================

:already_running
echo   Chat God is already running.
echo   Opening the control panel.
start "" %URL%
timeout /t 3 /nobreak >nul
exit /b 0

:no_python
echo   Python isn't installed, or the version installed can't run this.
echo.
echo   Chat God needs Python 3.9 to 3.12. Version 3.13 and newer won't work
echo   yet - some of the pieces it depends on haven't been updated.
echo.
echo   Download 3.12 from:
echo     https://www.python.org/downloads/release/python-3128/
echo.
echo   During installation, tick "Add python.exe to PATH".
echo   Then close this window and double-click start.bat again.
echo.
pause
exit /b 1

:venv_failed
echo.
echo   Couldn't create the virtual environment.
echo.
echo   The usual cause is this folder being read-only, or antivirus blocking
echo   it. Moving Chat God somewhere like C:\dev\ChatGodApp usually fixes it.
echo.
pause
exit /b 1

:pip_failed
echo.
echo   Couldn't install the dependencies.
echo.
echo   Almost always no internet connection, or a firewall blocking it.
echo   Check your connection and double-click start.bat again - it will pick
echo   up where it left off.
echo.
pause
exit /b 1

:app_failed
echo.
echo   Chat God stopped unexpectedly.
echo.
echo   If the last lines above mention an address already in use, it's
echo   already running in another window - close that one first.
echo.
echo   Otherwise, send whatever is printed above to Mark.
echo.
pause
exit /b 1
