@echo off
title SafeTrade Environment Setup

echo 🔧 Setting up SafeTrade environment...

REM Check if .env file already exists
if exist ".env" (
    echo ⚠️  .env file already exists. Skipping creation.
) else (
    REM Copy example file to .env
    if exist ".env.example" (
        copy .env.example .env
        echo ✅ Created .env file from .env.example
    ) else if exist "env_example.txt" (
        copy env_example.txt .env
        echo ✅ Created .env file from env_example.txt
    ) else (
        echo ❌ No example environment file found. Please create .env manually.
        pause
        exit /b 1
    )
)

echo.
echo 📝 Please edit the .env file and add your actual API keys and credentials:
echo    Using any text editor, open and modify the .env file
echo.
echo 🚀 After editing .env, start the services with:
echo    docker-compose up -d
echo.
pause