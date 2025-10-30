@echo off
echo ============================================
echo Setting up Autonomous Web Agent
echo ============================================
echo.

echo [1/4] Deactivating conda...
call conda deactivate 2>nul

echo [2/4] Creating virtual environment...
if not exist .venv (
    python -m venv .venv
    echo Virtual environment created.
) else (
    echo Virtual environment already exists.
)

echo [3/4] Activating virtual environment...
call .venv\Scripts\activate.bat

echo [4/4] Installing dependencies...
pip install -e .
playwright install chromium

echo.
echo ============================================
echo Setup complete!
echo ============================================
echo.
echo Next steps:
echo 1. Set your OpenAI API key:
echo    $env:OPENAI_API_KEY="your_key_here"
echo.
echo 2. Record Linear cookies (one time):
echo    python -m scripts.record_cookies
echo.
echo 3. Start the driver (in terminal 1):
echo    python -m src.drivers.playwright_driver
echo.
echo 4. Run the agent (in terminal 2):
echo    python -m src.agents.graph run linear "create a project in linear named alpha"
echo.
pause

