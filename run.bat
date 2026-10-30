@echo off
REM Windows launcher. Needs: Python 3.10+ and Tesseract (UB Mannheim build).
REM   Tesseract installer: https://github.com/UB-Mannheim/tesseract/wiki
set "TESS_DIR=C:\Program Files\Tesseract-OCR"
set "TESSERACT_CMD=%TESS_DIR%\tesseract.exe"
set "TESSDATA_PREFIX=%TESS_DIR%\tessdata"
set "OCR_WORKERS=2"

if not exist ".venv" (
  python -m venv .venv
  call .venv\Scripts\activate
  pip install -r backend\requirements.txt
) else (
  call .venv\Scripts\activate
)
if not exist "%TESSDATA_PREFIX%\tam.traineddata" (
  echo Tamil model missing. Run this once in an Administrator prompt:
  echo   python download_models.py "%TESSDATA_PREFIX%" tam eng
)
cd backend
start "" http://localhost:8000
uvicorn app:app --host 127.0.0.1 --port 8000
