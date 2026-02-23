@echo off
echo [INSTRUCTIONS FOR iPAD]
echo 1. Ensure your Laptop is ON and connected to the internet/Tailscale.
echo 2. Look for the "Network URL" below (e.g. http://100.x.y.z:8501).
echo 3. Type that URL into Safari on your iPad.
echo.

echo [STATUS] Activating Virtual Environment...
call .venv\Scripts\activate.bat

echo [STATUS] Launching Streamlit engine and opening browser...
streamlit run notam_filter_app.py

pause