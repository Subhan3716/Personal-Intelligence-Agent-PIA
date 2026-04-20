@echo off
title Personal Intelligence Agent Runner
cd /d "%~dp0"

echo [PIA] Starting Personal Intelligence Agent...
echo [PIA] Ensure LLAMA_API_KEY is configured in .env.

set TOKENIZERS_PARALLELISM=false
set TF_CPP_MIN_LOG_LEVEL=3
set PYTHONWARNINGS=ignore

.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501 --logger.level error --browser.gatherUsageStats false

echo [PIA] Personal Intelligence Agent stopped.
pause
