@echo off
REM BlueSight AI - double-click to start. First start installs everything (needs internet once, 10-20 min).
REM After that it starts in under a minute and works with the internet off.
cd /d "%~dp0"
title BlueSight AI

if exist ".venv\Scripts\python.exe" goto run

echo.
echo  First-time setup. This needs the internet ONCE and takes 10-20 minutes.
echo  It installs Python packages and downloads the open-source AI models into this folder.
echo.
where uv >nul 2>nul
if errorlevel 1 (
  echo  Installing uv, a small Python installer...
  powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex" || goto fail
)
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
uv venv --python 3.11 .venv || goto fail
REM --torch-backend=auto picks the NVIDIA (CUDA) build of PyTorch when an NVIDIA GPU is present, else the CPU build.
uv pip install --python .venv\Scripts\python.exe --torch-backend=auto -r requirements.txt -e . || goto fail
.venv\Scripts\python.exe scripts\setup_models.py || goto fail
.venv\Scripts\python.exe scripts\fetch_reference_photos.py || echo  Field-guide photos skipped (optional).
.venv\Scripts\python.exe scripts\prepare_resources.py
.venv\Scripts\python.exe scripts\build_registry.py
echo.
echo  Setup finished.

:run
echo.
echo  Starting BlueSight. Your browser opens at http://localhost:8501
echo  Keep this window open while you use BlueSight. Close it to stop.
echo.
start "" /b cmd /c "timeout /t 6 >nul & start http://localhost:8501"
.venv\Scripts\python.exe -m streamlit run app\streamlit_app.py
pause
goto :eof

:fail
echo.
echo  Setup stopped with an error (see the message above). Check the internet connection and try again.
echo  If it keeps failing, send this window's text to your tech contact.
pause
