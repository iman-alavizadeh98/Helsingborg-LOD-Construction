@echo off
rem LOD2.2 Building Reconstruction - Helsingborg
rem Author: Iman Alavi Zadeh. Developed with AI-assisted (agentic) programming.
rem
rem Double-click to open the pipeline's window.
rem
rem Uses the Windows Python launcher to pick Python 3.12, the version the pipeline is
rem verified on, whatever "python" happens to mean on this machine. "start" plus pyw
rem opens the window with no console left behind.

cd /d "%~dp0"

where pyw >nul 2>nul
if %errorlevel%==0 (
    pyw -3.12 -c "import tkinter" >nul 2>nul
    if not errorlevel 1 (
        start "" pyw -3.12 gui.pyw
        exit /b 0
    )
)

rem No launcher, or no Python 3.12 registered with it: try the Python on PATH, in
rem this console so that any error stays readable.
where python >nul 2>nul
if %errorlevel%==0 (
    python gui.pyw
    if not errorlevel 1 exit /b 0
)

echo.
echo Could not start the window.
echo.
echo Install Python 3.12 from https://www.python.org/downloads/ with the "py launcher"
echo option ticked, then install the packages from this folder:
echo.
echo     py -3.12 -m pip install -r requirements.txt
echo.
pause
