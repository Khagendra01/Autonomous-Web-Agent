@echo off
if "%~1"=="" (
    echo Usage: commit.bat "your commit message"
    echo Example: commit.bat "Add new feature"
    exit /b 1
)

echo Adding all changes...
git add .
git restore --staged app/(tabs)/profile.tsx

echo Committing with message: %~1
git commit -m "%~1"

if %errorlevel% equ 0 (
    echo Commit successful!
) else (
    echo Commit failed!
    exit /b 1
)
