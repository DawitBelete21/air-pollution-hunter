import io
import re
from datetime import datetime

import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="Air & Water Pollution Hunter", page_icon="🌍", layout="wide")

st.title("🌍 Air & Water Pollution Hunter")
st.caption("Upload the robot's Excel log to explore sensor readings, GPS locations, trends, and an automatically generated interpretation.")

st.info(
    "Measurement note: this dashboard distinguishes raw sensor output from calibrated pollutant concentrations. "
    "It does not calculate official AQI or CO/CO₂ ppm unless calibrated measurements are supplied."
)

uploaded = st.file_uploader("Upload your Pollution Hunter Excel workbook (.xlsx)", type=["xlsx"])

def find_col(df, name):
    target = name.strip().lower()
    for c in df.columns:
        if str(c).strip().lower() == target:
            return c
    return None

def parse_dms(value):
    """Convert a DMS coordinate string to signed decimal degrees."""
    if pd.isna(value):
        return np.nan
    s = str(value).strip().replace(" ", "")
    hemi_match = re.search(r"([NSEW])", s, re.I)
    if not hemi_match:
        try:
            return float(s)
        except Exception:
            return np.nan
    hemi = hemi_match.group(1).upper()
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    if not nums:
        return np.nan
    try:
        deg = float(nums[0])
        minutes = float(nums[1]) if len(nums) > 1 else 0.0
        seconds = float(nums[2]) if len(nums) > 2 else 0.0
        result = deg + minutes / 60 + seconds / 3600
        if hemi in ("S", "W"):
            result *= -1
        return result
    except Exception:
        return np.nan

def dew_point_c(temp, rh):
    rh = np.clip(rh, 1, 100)
    a, b = 17.625, 243.04
    gamma = np.log(rh / 100.0) + (a * temp) / (b + temp)
    return (b * gamma) / (a - gamma)

def numeric(df, col):
    if col is None:
        return pd.Series(np.nan, index=df.index)
    return pd.to_numeric(df[col], errors="coerce")

if uploaded:
    try:
        book = pd.ExcelFile(uploaded)
        if "Sensor Data" in book.sheet_names:
            raw = pd.read_excel(book, sheet_name="Sensor Data")
        else:
            raw = pd.read_excel(book, sheet_name=book.sheet_names[0])
        df = raw.copy()
        df.columns = [str(c).strip() for c in df.columns]

        timestamp_col = find_col(df, "Timestamp")
        if timestamp_col:
            df["Parsed timestamp"] = pd.to_datetime(df[timestamp_col], errors="coerce")
        else:
            df["Parsed timestamp"] = pd.NaT

        # The workbook's coordinate labels may be reversed. Identify coordinates by N/S/E/W.
        lat_source = find_col(df, "Latitude")
        lon_source = find_col(df, "Longitude")
        coord_values = []
        for _, row in df.iterrows():
            vals = [row.get(lat_source, np.nan), row.get(lon_source, np.nan)]
            lat_val, lon_val = np.nan, np.nan
            for v in vals:
                if pd.isna(v):
                    continue
                s = str(v).upper()
                if "N" in s or "S" in s:
                    lat_val = parse_dms(v)
                elif "E" in s or "W" in s:
                    lon_val = parse_dms(v)
            coord_values.append((lat_val, lon_val))
        df["Map latitude"] = [x[0] for x in coord_values]
        df["Map longitude"] = [x[1] for x in coord_values]

        mapping = {
            "MQ-7 raw": "MQ-7",
            "MQ-135 output": "MQ-135",
            "Dust (%)": "Dust (%)",
            "Temperature (°C)": "Temperature",
            "Humidity (%)": "Humidity",
            "Altitude (m)": "Altitude (m)",
            "Satellites": "Satellites",
            "Distance (cm)": "Distance (cm)",
        }
        for new, old in mapping.items():
            df[new] = numeric(df, find_col(df, old))

        gps_col = find_col(df, "GPS Fix")
        if gps_col:
            df["GPS valid"] = df[gps_col].astype(str).str.lower().isin(["true", "1", "yes"])
        else:
            df["GPS valid"] = False

        df["Valid distance (cm)"] = df["Distance (cm)"].where(df["Distance (cm)"] >= 0)
        df["Calculated dew point (°C)"] = dew_point_c(df["Temperature (°C)"], df["Humidity (%)"])

        st.success(f"Loaded {len(df):,} rows from **{uploaded.name}**.")
        st.caption(f"Workbook sheets: {', '.join(book.sheet_names)}")

        # Summary metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Recorded samples", f"{len(df):,}")
        c2.metric("GPS-valid samples", f"{int(df['GPS valid'].sum()):,}")
        c3.metric("Average temperature", f"{df['Temperature (°C)'].mean():.1f} °C" if df['Temperature (°C)'].notna().any() else "N/A")
        c4.metric("Average dust sensor output", f"{df['Dust (%)'].mean():.2f}%" if df['Dust (%)'].notna().any() else "N/A")

        tabs = st.tabs(["Overview & interpretation", "Charts", "GPS map", "Data table", "Download report"])

        with tabs[0]:
            st.subheader("Automatic interpretation")
            notes = []
            mq7 = df["MQ-7 raw"].dropna()
            mq135 = df["MQ-135 output"].dropna()
            dust = df["Dust (%)"].dropna()
            temp = df["Temperature (°C)"].dropna()
            hum = df["Humidity (%)"].dropna()

            if len(mq7):
                notes.append(
                    f"**MQ-7:** recorded raw values range from {mq7.min():.0f} to {mq7.max():.0f} "
                    f"(average {mq7.mean():.1f}). These values show the sensor's response trend only; "
                    "they cannot be reported as CO ppm without calibration and the correct heater/readout procedure."
                )
            if len(mq135):
                unique_vals = sorted(mq135.unique().tolist())
                if len(unique_vals) == 1:
                    notes.append(
                        f"**MQ-135:** the recorded output is constant at {unique_vals[0]:g} in this file. "
                        "This may indicate a digital threshold output that did not change during logging. "
                        "It is not a CO₂ ppm measurement."
                    )
                else:
                    notes.append(
                        f"**MQ-135:** the output takes {len(unique_vals)} distinct value(s): {unique_vals[:8]}. "
                        "If this is the module's digital output, interpret it as a threshold state, not gas concentration."
                    )
            if len(dust):
                notes.append(
                    f"**Dust sensor:** recorded output ranges from {dust.min():.1f}% to {dust.max():.1f}% "
                    f"(average {dust.mean():.1f}%). This is the logged sensor percentage, not a calibrated PM2.5 "
                    "concentration in µg/m³."
                )
            if len(temp):
                notes.append(
                    f"**Temperature:** ranges from {temp.min():.1f}°C to {temp.max():.1f}°C "
                    f"(average {temp.mean():.1f}°C)."
                )
            if len(hum):
                notes.append(
                    f"**Relative humidity:** ranges from {hum.min():.1f}% to {hum.max():.1f}% "
                    f"(average {hum.mean():.1f}%)."
                )
            if df["GPS valid"].any():
                good = df[df["GPS valid"] & df["Map latitude"].between(-90, 90) & df["Map longitude"].between(-180, 180)]
                notes.append(f"**GPS:** {len(good)} sample(s) have a GPS fix and usable coordinates.")
            else:
                notes.append("**GPS:** no rows are marked as having a valid GPS fix.")
            for n in notes:
                st.markdown("- " + n)

            st.subheader("Data quality checks")
            issues = []
            if not df["GPS valid"].all():
                issues.append(f"{int((~df['GPS valid']).sum())} row(s) are marked without GPS fix.")
            bad_dist = int((df["Distance (cm)"] < 0).sum())
            if bad_dist:
                issues.append(f"{bad_dist} distance reading(s) are negative/sentinel values and are excluded from distance summaries.")
            if df["MQ-135 output"].nunique(dropna=True) <= 1:
                issues.append("MQ-135 output has no variation in this workbook; verify whether the digital output pin and sensor threshold are working as intended.")
            if issues:
                for issue in issues:
                    st.warning(issue)
            else:
                st.success("No basic data-quality flags were detected.")

            st.subheader("Calculated dew point")
            st.write(
                "The dew point below is estimated from the recorded temperature and relative humidity using a standard approximation. "
                "It is not a direct dew-point sensor measurement."
            )
            if df["Calculated dew point (°C)"].notna().any():
                st.metric("Average estimated dew point", f"{df['Calculated dew point (°C)'].mean():.1f} °C")

        with tabs[1]:
            st.subheader("Sensor trends")
            chart_df = df.copy()
            if chart_df["Parsed timestamp"].notna().any():
                chart_df = chart_df.sort_values("Parsed timestamp")
                x = "Parsed timestamp"
            else:
                chart_df["Sample"] = np.arange(1, len(chart_df) + 1)
                x = "Sample"
            for col, title, ytitle in [
                ("MQ-7 raw", "MQ-7 raw sensor response", "Raw ADC / sensor value"),
                ("Dust (%)", "Dust sensor output", "Logged dust (%)"),
                ("Temperature (°C)", "Temperature over time", "°C"),
                ("Humidity (%)", "Relative humidity over time", "%"),
                ("Satellites", "GPS satellites", "Satellite count"),
            ]:
                if chart_df[col].notna().any():
                    fig = px.line(chart_df, x=x, y=col, markers=True, title=title, labels={col: ytitle, x: "Time" if x == "Parsed timestamp" else "Sample"})
                    st.plotly_chart(fig, use_container_width=True)
            if chart_df["MQ-135 output"].notna().any():
                st.write("MQ-135 output values")
                st.bar_chart(chart_df["MQ-135 output"].value_counts().sort_index())

        with tabs[2]:
            st.subheader("GPS sample locations")
            map_df = df[df["GPS valid"] & df["Map latitude"].between(-90, 90) & df["Map longitude"].between(-180, 180)].copy()
            if len(map_df):
                map_df["Sample time"] = map_df["Parsed timestamp"].astype(str)
                fig = px.scatter_mapbox(
                    map_df, lat="Map latitude", lon="Map longitude",
                    hover_name="Sample time",
                    hover_data={"MQ-7 raw": True, "Dust (%)": True, "Temperature (°C)": True, "Map latitude": False, "Map longitude": False},
                    zoom=13, height=520
                )
                fig.update_layout(mapbox_style="open-street-map", margin={"r":0,"t":0,"l":0,"b":0})
                st.plotly_chart(fig, use_container_width=True)
                st.caption("Map points are plotted only where GPS Fix is true and coordinates could be parsed.")
            else:
                st.warning("No usable GPS points were found in this workbook.")

        with tabs[3]:
            st.subheader("Cleaned sensor data")
            visible_cols = [c for c in ["Parsed timestamp", "Mode", "Command", "MQ-7 raw", "MQ-135 output", "Dust (%)", "Valid distance (cm)", "GPS valid", "Map latitude", "Map longitude", "Satellites", "Altitude (m)", "Temperature (°C)", "Humidity (%)", "Calculated dew point (°C)"] if c in df.columns]
            st.dataframe(df[visible_cols], use_container_width=True, hide_index=True)

        with tabs[4]:
            st.subheader("Download analysis")
            report_lines = [
                "# Air & Water Pollution Hunter — Data Analysis",
                f"Workbook: {uploaded.name}",
                f"Rows analyzed: {len(df)}",
                f"GPS-valid rows: {int(df['GPS valid'].sum())}",
                "",
                "## Interpretation",
                *[f"- {re.sub(r'\\*\\*', '', n)}" for n in notes],
                "",
                "## Important limitations",
                "- MQ-7 values are raw sensor response, not calibrated CO ppm.",
                "- MQ-135 output is not a CO₂ ppm measurement.",
                "- Dust (%) is not PM2.5/PM10 concentration in µg/m³.",
                "- Official AQI requires calibrated pollutant concentrations and the relevant standard.",
                "- Estimated dew point is calculated from temperature and relative humidity.",
            ]
            report = "\n".join(report_lines)
            st.download_button("Download interpretation report (.md)", report, file_name="pollution_hunter_report.md", mime="text/markdown")
            cleaned = df[visible_cols].to_csv(index=False).encode("utf-8")
            st.download_button("Download cleaned data (.csv)", cleaned, file_name="pollution_hunter_cleaned.csv", mime="text/csv")
            st.caption("The uploaded workbook is analyzed in this app session; this starter app does not permanently store uploaded files.")

    except Exception as e:
        st.error(f"Could not read this workbook: {e}")
        st.write("Please upload an .xlsx workbook with a sheet containing the sensor data.")
else:
    st.markdown("### What you'll get")
    st.markdown("- Automatic sensor summaries and cautious interpretations\n- Time-series charts and data-quality warnings\n- GPS map of valid recorded points\n- Downloadable cleaned CSV and written report")
    st.markdown("Upload the Excel file above to begin.")
