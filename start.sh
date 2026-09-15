#!/usr/bin/env bash
set -e

echo "============================================================"
echo "  ZAPYTAJ ONET RESCUE - WORKER"
echo "============================================================"
echo ""

if ! command -v python3 &> /dev/null; then
    echo "[BŁĄD] Nie znaleziono python3 w systemie!"
    exit 1
fi

if [ ! -f ".env" ]; then
    echo "[INFO] Tworzenie pliku .env z szablonu .env.example..."
    cp .env.example .env
    echo ""
    echo "============================================================"
    echo "WAŻNE: Skonfiguruj darmowe klucze Internet Archive!"
    echo "Wejdź na: https://archive.org/account/s3.php"
    echo "i uzupełnij IA_ACCESS_KEY i IA_SECRET_KEY w pliku .env."
    echo "============================================================"
    echo ""
fi

if [ ! -d ".venv" ]; then
    echo "[INFO] Tworzenie środowiska wirtualnego Python (venv)..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "[1/2] Instalacja/aktualizacja bibliotek..."
pip install -q -r requirements.txt

echo ""
echo "[2/2] Startowanie workera..."
python main.py worker
