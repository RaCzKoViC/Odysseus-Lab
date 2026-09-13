@echo off
setlocal
title Update Odysseus Docker Deployment

pushd "%~dp0" >nul

echo =========================================
echo Updating Odysseus Docker deployment
echo =========================================
echo.

where git >nul 2>nul
if errorlevel 1 (
  echo [!] Git was not found on PATH.
  echo     Install Git for Windows, then run this script again.
  goto :fail
)

where docker >nul 2>nul
if errorlevel 1 (
  echo [!] Docker was not found on PATH.
  echo     Start Docker Desktop, then run this script again.
  goto :fail
)

docker compose version >nul 2>nul
if errorlevel 1 (
  echo [!] Docker Compose is not available.
  echo     Update Docker Desktop, then run this script again.
  goto :fail
)

set "ACTIVE_COMPOSE_FILE=%COMPOSE_FILE%"
set "ACTIVE_APP_PORT=%APP_PORT%"
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /I "%%A"=="COMPOSE_FILE" if not defined ACTIVE_COMPOSE_FILE set "ACTIVE_COMPOSE_FILE=%%B"
    if /I "%%A"=="APP_PORT" if not defined ACTIVE_APP_PORT set "ACTIVE_APP_PORT=%%B"
  )
)
if not defined ACTIVE_APP_PORT set "ACTIVE_APP_PORT=7000"
if defined ACTIVE_COMPOSE_FILE (
  echo [+] Compose files: %ACTIVE_COMPOSE_FILE%
) else (
  echo [+] Compose files: docker-compose.yml
)

for /f %%I in ('git rev-parse HEAD') do set "PREVIOUS_SHA=%%I"

echo.
echo [+] Creating a full pre-update backup...
where py >nul 2>nul
if not errorlevel 1 (
  py -3 scripts\odysseus-compose-backup snapshot
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [!] Python was not found. It is required for the safe backup step.
    goto :fail
  )
  python scripts\odysseus-compose-backup snapshot
)
if errorlevel 1 goto :fail

echo [+] Pulling latest code...
git pull --ff-only
if errorlevel 1 goto :fail

echo.
echo [+] Rebuilding and restarting containers...
docker compose up -d --build
if errorlevel 1 goto :fail

echo.
echo [+] Waiting for Odysseus-Lab readiness...
powershell -NoProfile -Command "$deadline=(Get-Date).AddMinutes(5); do { try { $r=Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:%ACTIVE_APP_PORT%/api/ready' -TimeoutSec 5; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Seconds 5 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 goto :fail

echo.
echo [+] Removing dangling Docker images...
docker image prune -f
if errorlevel 1 goto :fail

echo.
echo =========================================
echo Update completed successfully.
echo =========================================
goto :done

:fail
echo.
echo Update failed. Check the message above and try again.
if defined PREVIOUS_SHA (
  echo Previous commit: %PREVIOUS_SHA%
  echo Rollback review command: git diff %PREVIOUS_SHA%..HEAD
  echo Restore the pre-update bundle with:
  echo   py -3 scripts\odysseus-compose-backup restore backups\BUNDLE.tar.gz --yes
)

:done
popd >nul
pause
