#!/bin/bash

# SafeTrade Environment Setup Script

echo "🔧 Setting up SafeTrade environment..."

# Check if .env file already exists
if [ -f ".env" ]; then
    echo "⚠️  .env file already exists. Skipping creation."
else
    # Copy example file to .env
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "✅ Created .env file from .env.example"
    elif [ -f "env_example.txt" ]; then
        cp env_example.txt .env
        echo "✅ Created .env file from env_example.txt"
    else
        echo "❌ No example environment file found. Please create .env manually."
        exit 1
    fi
fi

echo "📝 Please edit the .env file and add your actual API keys and credentials:"
echo "   nano .env"
echo "   or"
echo "   vim .env"
echo ""
echo "🚀 After editing .env, start the services with:"
echo "   docker-compose up -d"