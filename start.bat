@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM  Oracle-X Financial Terminal - Windows Quick Start
REM  Windows counterpart of start.sh: provisions deps, frees ports 8000/3100,
REM  boots backend + frontend in their own windows, seeds the RAG 2.0 index.
REM ============================================================================

cd /d "%~dp0"
title Oracle-X Launcher

echo.
echo     ===============================================================
echo                    ORACLE-X - FINANCIAL INTELLIGENCE
echo     ===============================================================
echo.

REM ---------------------------------------------------------------------------
REM  SYSTEM CHECK
REM ---------------------------------------------------------------------------
echo     [ SYSTEM CHECK ]
echo.

where npm >nul 2>&1
if errorlevel 1 (
    echo       [X] npm not found^^!
    echo           Install Node.js 18+ from https://nodejs.org/
    goto :fail
)
for /f "delims=" %%v in ('node -v 2^>nul') do set "NODE_VER=%%v"
echo       [OK] Node.js !NODE_VER! detected

set "PY_CMD="
python --version >nul 2>&1 && set "PY_CMD=python"
if not defined PY_CMD (
    py -3 --version >nul 2>&1 && set "PY_CMD=py -3"
)
if not defined PY_CMD (
    echo       [X] Python not found^^!
    echo           Install Python 3.11+ from https://www.python.org/downloads/
    echo           Make sure "Add python.exe to PATH" is checked during setup.
    goto :fail
)
for /f "delims=" %%v in ('!PY_CMD! --version 2^>^&1') do set "PY_VER=%%v"
echo       [OK] !PY_VER! detected

REM  3.11 is the floor rather than a preference: the backend annotates with
REM  `X | None` and CI runs 3.11. An older interpreter - and the one the
REM  Microsoft Store offers is often older - fails at import with a syntax
REM  error that reads like a corrupt source file instead of a wrong Python.
!PY_CMD! -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo       [X] Python 3.11 or newer is required^^!
    echo           Install it from https://www.python.org/downloads/
    goto :fail
)

REM ---------------------------------------------------------------------------
REM  ENVIRONMENT FILES
REM ---------------------------------------------------------------------------
echo.
echo     [ ENVIRONMENT ]
echo.

if not exist "backend\.env" (
    if exist "backend\.env.example" (
        copy /y "backend\.env.example" "backend\.env" >nul
        echo       [OK] backend\.env created from .env.example - fill in your keys
    )
) else (
    echo       [OK] backend\.env present
)

if not exist "frontend\.env.local" (
    if exist "frontend\.env.example" (
        copy /y "frontend\.env.example" "frontend\.env.local" >nul
        echo       [OK] frontend\.env.local created from .env.example
    )
) else (
    echo       [OK] frontend\.env.local present
)

REM ---------------------------------------------------------------------------
REM  DEPENDENCIES
REM ---------------------------------------------------------------------------
echo.
echo     [ DEPENDENCIES ]
echo.

REM  Windows uses its own venv dir so it never collides with a macOS/Linux
REM  "backend\venv" created by start.sh in the same checkout.

REM  Existence is not readiness. The first install pulls torch through
REM  sentence-transformers, which is a multi-gigabyte download that people
REM  interrupt - and a half-installed venv still activates, so the old check
REM  reported "cached" and then uvicorn died on an import in a window that
REM  scrolled past. Probe the imports instead.
set "VENV_READY="
if exist "backend\venv-win\Scripts\activate.bat" (
    call "backend\venv-win\Scripts\activate.bat"
    REM  find_spec rather than a real import: importing chromadb costs seconds
    REM  of model-registry work on a cold filesystem, and this runs every time.
    python -c "import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(m) for m in ('fastapi','uvicorn','chromadb')) else 1)" >nul 2>&1 && set "VENV_READY=1"
)

if defined VENV_READY (
    echo       [OK] Python environment cached
) else (
    if not exist "backend\venv-win\Scripts\activate.bat" (
        echo       [~] Creating Python virtual environment...
        !PY_CMD! -m venv "backend\venv-win"
        if errorlevel 1 (
            echo       [X] Failed to create the virtual environment.
            goto :fail
        )
        call "backend\venv-win\Scripts\activate.bat"
    )
    echo       [~] Installing Python packages - budget a few GB and ten
    echo           minutes on the first run. Progress is left visible on
    echo           purpose: quiet output here looks like a hang.
    python -m pip install --upgrade pip -q
    pip install -r "backend\requirements.txt"
    if errorlevel 1 (
        echo       [X] pip install failed - see the output above.
        echo           On Windows this is usually chromadb's hnswlib with no
        echo           matching wheel: install "Microsoft C++ Build Tools", or
        echo           use Python 3.11/3.12, which have prebuilt wheels.
        goto :fail
    )
    echo       [OK] Python environment ready
)

if not exist "frontend\node_modules" (
    echo       [~] Installing frontend packages...
    pushd "frontend"
    call npm install --silent
    popd
    echo       [OK] Frontend packages installed
) else (
    echo       [OK] Frontend packages cached
)

REM ---------------------------------------------------------------------------
REM  PORT CLEANUP
REM ---------------------------------------------------------------------------
echo.
echo     [ PORT CLEANUP ]
echo.
call :free_port 8000
call :free_port 3100

REM ---------------------------------------------------------------------------
REM  STARTING SERVICES
REM ---------------------------------------------------------------------------
echo.
echo     [ STARTING SERVICES ]
echo.

REM  uvicorn must run with cwd=backend - the app uses flat imports.
pushd "backend"
start "Oracle-X Backend" cmd /k "call venv-win\Scripts\activate.bat && set PYTHONUNBUFFERED=1 && uvicorn main:app --reload --host 0.0.0.0 --port 8000"
popd
echo       [OK] Backend starting - FastAPI on port 8000

pushd "frontend"
start "Oracle-X Frontend" cmd /k "npm run dev"
popd
echo       [OK] Frontend starting - Next.js on port 3100

REM ---------------------------------------------------------------------------
REM  RAG 2.0 INITIALIZATION
REM ---------------------------------------------------------------------------
echo.
echo     [ RAG 2.0 INITIALIZATION ]
echo.
where curl >nul 2>&1
if errorlevel 1 (
    echo       [!] curl not found - seed manually once the API is up:
    echo           curl -X POST http://localhost:8000/api/rag/initialize
    goto :seeded
)

REM  Poll rather than sleep ten seconds. A cold start loads Chroma and can
REM  take longer than that, and a backend that died on a missing
REM  SUPABASE_SERVICE_ROLE_KEY never takes any time at all - both were
REM  reported the same way by a fixed wait followed by one attempt.
echo       [~] Waiting for the API to come up...
set "API_UP="
for /l %%i in (1,1,30) do (
    if not defined API_UP (
        curl -s -o nul http://localhost:8000/api/system/health && set "API_UP=1"
        if not defined API_UP timeout /t 2 /nobreak >nul
    )
)

if not defined API_UP (
    echo       [!] The API did not answer within a minute. Read the backend
    echo           window - it will say why, and it usually says a missing key.
    goto :seeded
)

curl -s -X POST http://localhost:8000/api/rag/initialize >nul 2>&1
if errorlevel 1 (
    echo       [!] RAG seed did not respond.
    echo           Retry with: curl -X POST http://localhost:8000/api/rag/initialize
) else (
    echo       [OK] RAG 2.0 index seeded
)

:seeded

REM ---------------------------------------------------------------------------
REM  READY
REM ---------------------------------------------------------------------------
echo.
echo     ===============================================================
echo                        ORACLE-X IS READY
echo     ===============================================================
echo         Frontend : http://localhost:3100
echo         Backend  : http://localhost:8000
echo         API Docs : http://localhost:8000/docs
echo     ===============================================================
echo.
echo       Backend and frontend run in their own windows.
echo       Close those windows to stop the services.
echo.

start "" http://localhost:3100

pause
exit /b 0

REM ---------------------------------------------------------------------------
REM  SUBROUTINES
REM ---------------------------------------------------------------------------

:free_port
set "PORT=%~1"
set "FOUND="
REM  The trailing space matters: ":3100" is a substring of ":31000", so the
REM  unanchored match could kill an unrelated listener on a five-digit port.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /C:":%PORT% " ^| findstr "LISTENING"') do (
    if not "%%p"=="0" (
        taskkill /F /PID %%p >nul 2>&1
        set "FOUND=1"
    )
)
if defined FOUND (
    echo       [OK] Port %PORT% freed
) else (
    echo       [OK] Port %PORT% available
)
goto :eof

:fail
echo.
echo     Startup aborted.
echo.
pause
exit /b 1
