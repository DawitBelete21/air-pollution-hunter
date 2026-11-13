# Air Pollution Hunter — Streamlit website

## Run locally
1. Install Python 3.10 or newer.
2. Open a terminal in this folder.
3. Install dependencies:
   `pip install -r requirements.txt`
4. Start the website:
   `streamlit run app.py`

## Deploy free with Streamlit Community Cloud
1. Create a GitHub repository for this app.
2. Upload `app.py`, `requirements.txt`, and this README.
3. Go to https://share.streamlit.io/ and sign in with GitHub.
4. Choose the repository, branch, and `app.py`.
5. Deploy. Choose an available app URL such as `pollution-hunter.streamlit.app`.

## Notes about sensor interpretation
- MQ-7 is shown as raw sensor response unless calibrated.
- MQ-135 digital output is a threshold state, not CO2 ppm.
- Dust percentage is not a calibrated PM2.5/PM10 concentration.
- GPS points are only plotted for rows marked GPS Fix = true with valid coordinates.
- Uploads are processed during the app session and are not permanently saved by this starter app.
