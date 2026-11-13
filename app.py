import io
import re
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

st.set_page_config(page_title="Air & Water Pollution Hunter", page_icon="🌍", layout="wide")
st.title("🌍 Air & Water Pollution Hunter")
st.caption("Upload the robot's Excel log to explore sensor readings, GPS locations, trends, and a downloadable analysis report.")
st.info(
    "Scientific note: raw sensor responses are not the same as calibrated pollutant concentrations. "
    "This dashboard does not invent CO/CO₂ ppm, PM2.5 µg/m³, or official AQI values."
)

uploaded = st.file_uploader("Upload your Pollution Hunter Excel workbook (.xlsx)", type=["xlsx"])

def find_col(df, wanted):
    wanted = wanted.strip().lower()
    for col in df.columns:
        if str(col).strip().lower() == wanted:
            return col
    return None

def parse_coordinate(value):
    """Accept decimal degrees or DMS text such as 038°48'33.9\\\"E."""
    if pd.isna(value):
        return np.nan
    s = str(value).strip().upper()
    hemi = re.search(r"([NSEW])", s)
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    if not nums:
        try:
            return float(s)
        except Exception:
            return np.nan
    try:
        if hemi:
            deg = float(nums[0])
            minute = float(nums[1]) if len(nums) > 1 else 0.0
            second = float(nums[2]) if len(nums) > 2 else 0.0
            result = deg + minute / 60 + second / 3600
            if hemi.group(1) in ("S", "W"):
                result = -result
            return result
        return float(s)
    except Exception:
        return np.nan

def to_num(df, name):
    col = find_col(df, name)
    return pd.to_numeric(df[col], errors="coerce") if col else pd.Series(np.nan, index=df.index)

def clean_text(value):
    return re.sub(r"\*\*", "", str(value))

def trend_sentence(series, label):
    s = pd.to_numeric(series, errors="coerce").dropna()
    if len(s) < 4:
        return f"{label}: not enough valid readings to estimate a trend."
    midpoint = len(s) // 2
    first, second = s.iloc[:midpoint].mean(), s.iloc[midpoint:].mean()
    if first == 0:
        change = None
    else:
        change = (second - first) / abs(first) * 100
    if change is None:
        direction = "changed between the first and second halves"
    elif change > 5:
        direction = f"increased by approximately {change:.1f}% from the first half to the second half"
    elif change < -5:
        direction = f"decreased by approximately {abs(change):.1f}% from the first half to the second half"
    else:
        direction = "was broadly stable between the first and second halves"
    return f"{label}: {direction}. This describes this dataset only, not a health or regulatory risk category."

if uploaded:
    try:
        book = pd.ExcelFile(uploaded)
        sheet = "Sensor Data" if "Sensor Data" in book.sheet_names else book.sheet_names[0]
        df = pd.read_excel(book, sheet_name=sheet)
        df.columns = [str(c).strip() for c in df.columns]

        timestamp_col = find_col(df, "Timestamp")
        df["Timestamp parsed"] = pd.to_datetime(df[timestamp_col], errors="coerce") if timestamp_col else pd.NaT

        # In this workbook the coordinate fields are reversed: the "Latitude" column
        # contains E coordinates and "Longitude" contains N coordinates.
        coord_a, coord_b = find_col(df, "Latitude"), find_col(df, "Longitude")
        latitudes, longitudes = [], []
        for _, row in df.iterrows():
            a = row.get(coord_a, np.nan) if coord_a else np.nan
            b = row.get(coord_b, np.nan) if coord_b else np.nan
            lat, lon = np.nan, np.nan
            for value in (a, b):
                if pd.isna(value):
                    continue
                parsed = parse_coordinate(value)
                text = str(value).upper()
                if "N" in text or "S" in text:
                    lat = parsed
                elif "E" in text or "W" in text:
                    lon = parsed
                elif np.isfinite(parsed):
                    # Decimal-degree fallback based on valid latitude/longitude ranges.
                    if -90 <= parsed <= 90 and not np.isfinite(lat):
                        lat = parsed
                    elif -180 <= parsed <= 180 and not np.isfinite(lon):
                        lon = parsed
            latitudes.append(lat)
            longitudes.append(lon)
        df["Map latitude"] = latitudes
        df["Map longitude"] = longitudes

        aliases = {
            "MQ-7 raw": "MQ-7",
            "MQ-135 digital output": "MQ-135",
            "Dust output (%)": "Dust (%)",
            "Distance (cm)": "Distance (cm)",
            "Temperature (°C)": "Temperature",
            "Humidity (%)": "Humidity",
            "Altitude (m)": "Altitude (m)",
            "Satellites": "Satellites",
        }
        for new_name, original in aliases.items():
            df[new_name] = to_num(df, original)

        fix_col = find_col(df, "GPS Fix")
        if fix_col:
            df["GPS fix valid"] = df[fix_col].astype(str).str.strip().str.lower().isin(["true", "1", "yes", "fix", "valid"])
        else:
            df["GPS fix valid"] = False

        df["Valid GPS point"] = (
            df["GPS fix valid"]
            & df["Map latitude"].between(-90, 90)
            & df["Map longitude"].between(-180, 180)
        )
        df["Valid distance (cm)"] = df["Distance (cm)"].where(df["Distance (cm)"] >= 0)

        temp, humidity = df["Temperature (°C)"], df["Humidity (%)"]
        rh = humidity.clip(lower=1, upper=100)
        gamma = np.log(rh / 100) + (17.625 * temp) / (243.04 + temp)
        df["Estimated dew point (°C)"] = (243.04 * gamma) / (17.625 - gamma)

        st.success(f"Successfully loaded {len(df):,} samples from **{uploaded.name}**.")
        st.caption(f"Reading sheet: {sheet} · Workbook sheets: {', '.join(book.sheet_names)}")

        gps_count = int(df["Valid GPS point"].sum())
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Sensor samples", f"{len(df):,}")
        c2.metric("Usable GPS points", f"{gps_count:,}")
        c3.metric("Average temperature", f"{temp.mean():.1f} °C" if temp.notna().any() else "N/A")
        c4.metric("Average dust output", f"{df['Dust output (%)'].mean():.2f}%" if df["Dust output (%)"].notna().any() else "N/A")

        tabs = st.tabs(["Interpretation", "Charts", "GPS map", "Data", "Downloads"])

        interpretations = []
        mq7 = df["MQ-7 raw"].dropna()
        mq135 = df["MQ-135 digital output"].dropna()
        dust = df["Dust output (%)"].dropna()

        if len(mq7):
            interpretations.append(
                f"**MQ-7 raw response:** minimum {mq7.min():.0f}, maximum {mq7.max():.0f}, "
                f"average {mq7.mean():.1f}. The first-to-second-half trend {trend_sentence(mq7, 'MQ-7').split(': ', 1)[-1]} "
                "These are raw sensor readings, not CO ppm. A calibrated sensor curve and correct heater cycle are required for concentration estimates."
            )
        if len(mq135):
            states = sorted(mq135.unique().tolist())
            interpretations.append(
                f"**MQ-135 digital output:** recorded state(s): {states}. "
                "This is a comparator/threshold signal, not a CO₂ concentration. The meaning of HIGH/LOW depends on module wiring and comparator adjustment."
            )
            if len(states) == 1:
                interpretations.append("**MQ-135 data-quality note:** the digital output never changed in this file. Check the module's threshold potentiometer, wiring, and whether the code is reading DO or AO.")
        if len(dust):
            interpretations.append(
                f"**Dust sensor output:** minimum {dust.min():.2f}%, maximum {dust.max():.2f}%, "
                f"average {dust.mean():.2f}%. {trend_sentence(dust, 'Dust output')} "
                "This logged percentage is not a calibrated PM2.5/PM10 value in µg/m³."
            )
        if temp.notna().any():
            interpretations.append(f"**Temperature:** {temp.min():.1f}–{temp.max():.1f} °C; average {temp.mean():.1f} °C.")
        if humidity.notna().any():
            interpretations.append(f"**Relative humidity:** {humidity.min():.1f}–{humidity.max():.1f}%; average {humidity.mean():.1f}%.")
        dew = df["Estimated dew point (°C)"].dropna()
        if len(dew):
            interpretations.append(f"**Estimated dew point:** average {dew.mean():.1f} °C, calculated from temperature and humidity; it is not a direct sensor reading.")
        interpretations.append(f"**GPS:** {gps_count} samples have both a valid GPS-fix flag and usable coordinates.")
        if df["Valid distance (cm)"].notna().any():
            d = df["Valid distance (cm)"].dropna()
            interpretations.append(f"**Obstacle distance:** {len(d)} valid distance readings, ranging from {d.min():.1f} to {d.max():.1f} cm. Negative sentinel readings were excluded.")

        with tabs[0]:
            st.subheader("What the readings suggest")
            for item in interpretations:
                st.markdown(f"- {item}")
            st.subheader("Data-quality checks")
            issues = []
            if gps_count == 0:
                issues.append("No GPS points passed both the GPS-fix and coordinate checks.")
            elif gps_count < int(df["GPS fix valid"].sum()):
                issues.append(f"{int(df['GPS fix valid'].sum()) - gps_count} GPS-fix rows had coordinates that could not be parsed.")
            if (df["Distance (cm)"] < 0).any():
                issues.append(f"{int((df['Distance (cm)'] < 0).sum())} negative distance values were treated as invalid.")
            if len(mq135) and mq135.nunique() == 1:
                issues.append("MQ-135 digital output is constant; inspect sensor threshold and signal wiring.")
            if issues:
                for issue in issues:
                    st.warning(issue)
            else:
                st.success("No basic data-quality warnings were found.")
            st.caption("Interpretations compare readings within this uploaded dataset. They are not medical advice, regulatory compliance results, or official AQI.")

        with tabs[1]:
            st.subheader("Sensor trends")
            chart_df = df.copy()
            if chart_df["Timestamp parsed"].notna().any():
                chart_df = chart_df.sort_values("Timestamp parsed")
                x_col = "Timestamp parsed"
            else:
                chart_df["Sample number"] = np.arange(1, len(chart_df) + 1)
                x_col = "Sample number"
            charts = [
                ("MQ-7 raw", "MQ-7 raw sensor response", "Raw sensor value"),
                ("Dust output (%)", "Dust sensor output", "Logged dust (%)"),
                ("Temperature (°C)", "Temperature", "°C"),
                ("Humidity (%)", "Relative humidity", "%"),
                ("Satellites", "GPS satellite count", "Satellites"),
                ("Estimated dew point (°C)", "Estimated dew point", "°C"),
            ]
            for col, title, ylabel in charts:
                if chart_df[col].notna().any():
                    fig = px.line(chart_df, x=x_col, y=col, markers=True, title=title, labels={x_col: "Time" if x_col == "Timestamp parsed" else "Sample", col: ylabel})
                    st.plotly_chart(fig, use_container_width=True)
            if chart_df["MQ-135 digital output"].notna().any():
                st.subheader("MQ-135 digital states")
                st.bar_chart(chart_df["MQ-135 digital output"].value_counts().sort_index())

        with tabs[2]:
            st.subheader("Robot GPS route / sample points")
            map_df = df[df["Valid GPS point"]].copy()
            if len(map_df):
                st.caption(f"Showing {len(map_df)} valid points. Coordinates are interpreted from N/S as latitude and E/W as longitude, even if the spreadsheet headings are reversed.")
                map_df = map_df.rename(columns={"Map latitude": "latitude", "Map longitude": "longitude"})
                st.map(map_df, latitude="latitude", longitude="longitude", size=15)
                st.dataframe(map_df[["Timestamp parsed", "latitude", "longitude", "Satellites", "Altitude (m)", "MQ-7 raw", "Dust output (%)"]], use_container_width=True, hide_index=True)
            else:
                st.warning("No usable GPS points were found. Check that GPS Fix is true and the coordinate cells contain valid N/S and E/W values.")

        with tabs[3]:
            st.subheader("Cleaned sensor readings")
            display_cols = [
                "Timestamp parsed", "Mode", "Command", "MQ-7 raw", "MQ-135 digital output",
                "Dust output (%)", "Valid distance (cm)", "GPS fix valid", "Map latitude",
                "Map longitude", "Satellites", "Altitude (m)", "Temperature (°C)",
                "Humidity (%)", "Estimated dew point (°C)"
            ]
            display_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

        with tabs[4]:
            st.subheader("Download your results")
            report_lines = [
                "AIR & WATER POLLUTION HUNTER — DATA ANALYSIS",
                f"Workbook: {uploaded.name}",
                f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                f"Samples analyzed: {len(df)}",
                f"Usable GPS points: {gps_count}",
                "",
                "INTERPRETATION",
            ] + [f"- {clean_text(item)}" for item in interpretations] + [
                "",
                "IMPORTANT MEASUREMENT LIMITATIONS",
                "- MQ-7 raw readings are not calibrated CO ppm.",
                "- MQ-135 digital output is a threshold state, not CO2 ppm.",
                "- Dust percentage is not PM2.5 or PM10 concentration in micrograms per cubic metre.",
                "- Official AQI requires calibrated pollutant concentrations and the applicable standard.",
                "- Dew point is estimated from temperature and relative humidity.",
                "- GPS points are plotted only when GPS Fix is true and coordinates are valid.",
            ]
            report_text = "\n".join(report_lines)
            st.download_button(
                "⬇ Download interpretation report (.txt)",
                data=report_text.encode("utf-8"),
                file_name="Pollution_Hunter_Analysis_Report.txt",
                mime="text/plain",
                use_container_width=True,
            )
            csv_data = df[display_cols].to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                "⬇ Download cleaned readings (.csv)",
                data=csv_data,
                file_name="Pollution_Hunter_Cleaned_Data.csv",
                mime="text/csv",
                use_container_width=True,
            )
            xlsx_buffer = io.BytesIO()
            with pd.ExcelWriter(xlsx_buffer, engine="openpyxl") as writer:
                df[display_cols].to_excel(writer, index=False, sheet_name="Cleaned Sensor Data")
                pd.DataFrame({"Interpretation": [clean_text(x) for x in interpretations]}).to_excel(writer, index=False, sheet_name="Analysis")
            st.download_button(
                "⬇ Download analyzed workbook (.xlsx)",
                data=xlsx_buffer.getvalue(),
                file_name="Pollution_Hunter_Analyzed_Data.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

            pdf_buffer = io.BytesIO()
            doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
            styles = getSampleStyleSheet()
            story = [Paragraph("Air & Water Pollution Hunter", styles["Title"]), Spacer(1, 12)]
            story.append(Paragraph(f"Workbook: {uploaded.name}<br/>Samples analyzed: {len(df)}<br/>Usable GPS points: {gps_count}", styles["BodyText"]))
            story.append(Spacer(1, 12))
            story.append(Paragraph("Automatic interpretation", styles["Heading2"]))
            for item in interpretations:
                story.append(Paragraph(clean_text(item).replace("&", "&amp;"), styles["BodyText"]))
                story.append(Spacer(1, 6))
            story.append(Paragraph("Measurement limitations", styles["Heading2"]))
            for item in report_lines[report_lines.index("IMPORTANT MEASUREMENT LIMITATIONS")+1:]:
                story.append(Paragraph(item.replace("&", "&amp;"), styles["BodyText"]))
                story.append(Spacer(1, 4))
            doc.build(story)
            st.download_button(
                "⬇ Download PDF report",
                data=pdf_buffer.getvalue(),
                file_name="Pollution_Hunter_Analysis_Report.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
            st.caption("Uploads are analyzed during the session and are not permanently stored by this starter app.")

    except Exception as exc:
        st.error(f"Could not analyze this workbook: {exc}")
        st.exception(exc)
else:
    st.markdown("### Upload your robot's Excel file")
    st.markdown("- Automatic interpretations and data-quality checks")
    st.markdown("- Sensor trend charts")
    st.markdown("- GPS map using coordinate directions")
    st.markdown("- Downloadable TXT, CSV, Excel, and PDF reports")
