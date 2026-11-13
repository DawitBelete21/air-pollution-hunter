# Air & Water Pollution Hunter — Website v2

## Deploying an update
1. Extract this ZIP.
2. Open your existing public GitHub repository.
3. Replace the old `app.py` and `requirements.txt` with the versions here.
4. Commit the changes. Streamlit Community Cloud should redeploy automatically.

## Features
- Upload an Excel workbook and analyze the `Sensor Data` sheet.
- Automatically interprets raw sensor response and environmental trends.
- Correctly identifies GPS latitude/longitude by N/S/E/W direction even when spreadsheet headings are reversed.
- Uses Streamlit's built-in map display.
- Downloads TXT, CSV, analyzed XLSX, and PDF reports.

## Measurement limitations
- MQ-7 raw readings are not calibrated CO ppm.
- MQ-135 digital output is a threshold state, not CO2 ppm.
- Dust percentage is not PM2.5/PM10 concentration in micrograms per cubic metre.
- Official AQI requires calibrated pollutant concentrations and the applicable standard.
