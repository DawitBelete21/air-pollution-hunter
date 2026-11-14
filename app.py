import io
import re
import json
import uuid
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from supabase import create_client
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

st.set_page_config(page_title="Air Pollution Hunter", page_icon="🌍", layout="wide")
st.title("🌍 Air Pollution Hunter")
st.caption("Shared pollution-monitoring dashboard")

BUCKET = "pollution-files"
EMAIL_SUFFIX = "@airpollutionhunter.invalid"


def get_secret(name):
    try:
        return st.secrets[name]
    except Exception:
        return None


SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_KEY = get_secret("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Supabase credentials are missing. Add SUPABASE_URL and SUPABASE_KEY in Streamlit → App settings → Secrets.")
    st.stop()


def new_session_client():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


if "supabase_client" not in st.session_state:
    st.session_state.supabase_client = new_session_client()
client = st.session_state.supabase_client


def username_email(username):
    return username.strip().lower() + EMAIL_SUFFIX


def get_profile(user_id):
    result = client.table("profiles").select("id, username, role").eq("id", user_id).single().execute()
    return result.data


def establish_login(auth_response):
    user = getattr(auth_response, "user", None)
    session = getattr(auth_response, "session", None)
    if user is None or session is None:
        raise RuntimeError("No login session was returned. Confirm that Email authentication is enabled and Confirm email is OFF in Supabase.")
    profile = get_profile(user.id)
    st.session_state.user_id = user.id
    st.session_state.username = profile["username"]
    st.session_state.role = profile["role"]


def auth_screen():
    st.subheader("Welcome")
    st.write("Create an account or sign in with your username and password.")
    signup_tab, login_tab = st.tabs(["Create account", "Log in"])

    with signup_tab:
        with st.form("signup_form"):
            new_username = st.text_input("Choose a username", max_chars=24).strip().lower()
            new_password = st.text_input("Create a password", type="password")
            confirm_password = st.text_input("Confirm password", type="password")
            signup = st.form_submit_button("Sign up", use_container_width=True)
        if signup:
            if not re.fullmatch(r"[a-z0-9_.-]{3,24}", new_username):
                st.error("Username must be 3–24 characters and use lowercase letters, numbers, dots, underscores, or hyphens.")
            elif len(new_password) < 8:
                st.error("Use a password with at least 8 characters.")
            elif new_password != confirm_password:
                st.error("The passwords do not match.")
            else:
                try:
                    response = client.auth.sign_up({
                        "email": username_email(new_username),
                        "password": new_password,
                        "options": {"data": {"username": new_username}},
                    })
                    establish_login(response)
                    st.success("Account created. You are now signed in.")
                    st.rerun()
                except Exception as exc:
                    message = str(exc)
                    if "already" in message.lower() or "unique" in message.lower():
                        st.error("That username is already taken. Choose another one.")
                    else:
                        st.error(f"Could not create the account: {message}")

    with login_tab:
        with st.form("login_form"):
            username = st.text_input("Username").strip().lower()
            password = st.text_input("Password", type="password")
            login = st.form_submit_button("Log in", use_container_width=True)
        if login:
            if not re.fullmatch(r"[a-z0-9_.-]{3,24}", username):
                st.error("Enter a valid username.")
            elif not password:
                st.error("Enter your password.")
            else:
                try:
                    response = client.auth.sign_in_with_password({
                        "email": username_email(username),
                        "password": password,
                    })
                    establish_login(response)
                    st.rerun()
                except Exception:
                    st.error("Incorrect username or password.")

    st.info("Passwords are handled by Supabase Auth and are not stored as plain text by this app. Accounts do not use email addresses, so users must contact the administrator if they forget a password.")


if "user_id" not in st.session_state:
    auth_screen()
    st.stop()

try:
    profile = get_profile(st.session_state.user_id)
    st.session_state.username = profile["username"]
    st.session_state.role = profile["role"]
except Exception:
    for key in ("user_id", "username", "role", "supabase_client"):
        st.session_state.pop(key, None)
    st.error("Your session could not be verified. Please log in again.")
    st.stop()

is_admin = st.session_state.role == "admin"
with st.sidebar:
    st.markdown("### Account")
    st.write(f"**{st.session_state.username}**")
    st.caption("Administrator" if is_admin else "Registered user")
    if st.button("Log out", use_container_width=True):
        try:
            client.auth.sign_out()
        finally:
            for key in ("user_id", "username", "role", "supabase_client"):
                st.session_state.pop(key, None)
        st.rerun()

st.divider()


def persist_workbook(uploaded_file):
    content = uploaded_file.getvalue()
    workbook = pd.ExcelFile(io.BytesIO(content))
    sheet = "Sensor Data" if "Sensor Data" in workbook.sheet_names else workbook.sheet_names[0]
    frame = pd.read_excel(workbook, sheet_name=sheet)
    frame.columns = [str(c).strip() for c in frame.columns]
    records = json.loads(frame.to_json(orient="records", date_format="iso"))
    upload_id = str(uuid.uuid4())
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", uploaded_file.name)[:100]
    file_path = f"{st.session_state.user_id}/{upload_id}_{safe_name}"

    client.storage.from_(BUCKET).upload(
        file_path,
        content,
        file_options={
            "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "upsert": "false",
        },
    )
    try:
        client.table("uploads").insert({
            "id": upload_id,
            "original_name": uploaded_file.name,
            "file_path": file_path,
            "uploaded_by": st.session_state.user_id,
        }).execute()
        for start in range(0, len(records), 400):
            batch = [{"upload_id": upload_id, "row_data": row} for row in records[start:start + 400]]
            if batch:
                client.table("sensor_readings").insert(batch).execute()
    except Exception:
        try:
            client.table("uploads").delete().eq("id", upload_id).execute()
            client.storage.from_(BUCKET).remove([file_path])
        except Exception:
            pass
        raise
    return upload_id, len(records), sheet


if is_admin:
    with st.expander("⬆ Upload a new Excel workbook", expanded=False):
        st.write("Only your administrator account can add shared datasets.")
        new_file = st.file_uploader("Choose an Excel workbook", type=["xlsx"], key="admin_excel_upload")
        if st.button("Save workbook for everyone", type="primary", disabled=new_file is None):
            try:
                with st.spinner("Saving the workbook and sensor rows to Supabase..."):
                    upload_id, count, sheet_name = persist_workbook(new_file)
                st.success(f"Saved {count:,} rows from '{sheet_name}'. Everyone with an account can now access this dataset.")
                st.rerun()
            except Exception as exc:
                st.error(f"Upload failed: {exc}")

try:
    uploads_result = client.table("uploads").select("id, original_name, uploaded_at, file_path").order("uploaded_at", desc=True).execute()
    uploads = uploads_result.data or []
except Exception as exc:
    st.error(f"Could not load shared datasets: {exc}")
    st.stop()

if not uploads:
    st.info("No shared pollution datasets have been uploaded yet.")
    st.write("The administrator can upload the first Excel workbook. It will then appear here for all registered users.")
    st.stop()

upload_labels = {
    item["id"]: f'{item["original_name"]} — {item.get("uploaded_at", "")[:16]}'
    for item in uploads
}
selected_id = st.selectbox(
    "Choose a shared dataset",
    options=[item["id"] for item in uploads],
    format_func=lambda value: upload_labels.get(value, value),
)
selected_upload = next(item for item in uploads if item["id"] == selected_id)

if is_admin:
    with st.expander("Manage selected dataset"):
        st.caption("Deleting a dataset permanently removes its saved readings and uploaded Excel file.")
        confirm_delete = st.checkbox("I understand this permanently deletes the selected dataset.")
        if st.button("Delete selected dataset", disabled=not confirm_delete):
            try:
                client.table("uploads").delete().eq("id", selected_id).execute()
                client.storage.from_(BUCKET).remove([selected_upload["file_path"]])
                st.success("Dataset deleted.")
                st.rerun()
            except Exception as exc:
                st.error(f"Could not delete dataset: {exc}")

try:
    rows = []
    page_size = 1000
    start = 0
    while True:
        page = client.table("sensor_readings").select("row_data").eq("upload_id", selected_id).order("id").range(start, start + page_size - 1).execute()
        batch = page.data or []
        rows.extend([item["row_data"] for item in batch])
        if len(batch) < page_size:
            break
        start += page_size
    if not rows:
        st.warning("This dataset has no saved sensor rows.")
        st.stop()
    df = pd.DataFrame(rows)
except Exception as exc:
    st.error(f"Could not read this dataset: {exc}")
    st.stop()

st.success(f"Loaded **{len(df):,} saved samples** from **{selected_upload['original_name']}**.")
st.caption("This dataset is stored in Supabase and is shared with every registered user.")


def find_col(frame, wanted):
    wanted = wanted.strip().lower()
    for col in frame.columns:
        if str(col).strip().lower() == wanted:
            return col
    return None


def parse_coordinate(value):
    if pd.isna(value):
        return np.nan
    value_text = str(value).strip().upper()
    hemi = re.search(r"([NSEW])", value_text)
    nums = re.findall(r"\d+(?:\.\d+)?", value_text)
    if not nums:
        try:
            return float(value_text)
        except Exception:
            return np.nan
    try:
        if hemi:
            degrees = float(nums[0])
            minutes = float(nums[1]) if len(nums) > 1 else 0.0
            seconds = float(nums[2]) if len(nums) > 2 else 0.0
            result = degrees + minutes / 60 + seconds / 3600
            return -result if hemi.group(1) in ("S", "W") else result
        return float(value_text)
    except Exception:
        return np.nan


def to_num(frame, name):
    col = find_col(frame, name)
    return pd.to_numeric(frame[col], errors="coerce") if col else pd.Series(np.nan, index=frame.index)


def clean_text(value):
    return re.sub(r"\*\*", "", str(value))


def trend_sentence(series, label):
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) < 4:
        return f"{label}: not enough valid readings to estimate a trend."
    midpoint = len(values) // 2
    first, second = values.iloc[:midpoint].mean(), values.iloc[midpoint:].mean()
    change = None if first == 0 else (second - first) / abs(first) * 100
    if change is None:
        direction = "changed between the first and second halves"
    elif change > 5:
        direction = f"increased by approximately {change:.1f}% from the first half to the second half"
    elif change < -5:
        direction = f"decreased by approximately {abs(change):.1f}% from the first half to the second half"
    else:
        direction = "was broadly stable between the first and second halves"
    return f"{label}: {direction}. This describes this dataset only, not a health or regulatory risk category."


df.columns = [str(c).strip() for c in df.columns]
timestamp_col = find_col(df, "Timestamp")
df["Timestamp parsed"] = pd.to_datetime(df[timestamp_col], errors="coerce") if timestamp_col else pd.NaT

coord_a, coord_b = find_col(df, "Latitude"), find_col(df, "Longitude")
latitudes, longitudes = [], []
for _, row in df.iterrows():
    values = [row.get(coord_a, np.nan) if coord_a else np.nan, row.get(coord_b, np.nan) if coord_b else np.nan]
    lat, lon = np.nan, np.nan
    for value in values:
        if pd.isna(value):
            continue
        parsed = parse_coordinate(value)
        text_value = str(value).upper()
        if "N" in text_value or "S" in text_value:
            lat = parsed
        elif "E" in text_value or "W" in text_value:
            lon = parsed
        elif np.isfinite(parsed):
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
df["GPS fix valid"] = df[fix_col].astype(str).str.strip().str.lower().isin(["true", "1", "yes", "fix", "valid"]) if fix_col else False
df["Valid GPS point"] = df["GPS fix valid"] & df["Map latitude"].between(-90, 90) & df["Map longitude"].between(-180, 180)
df["Valid distance (cm)"] = df["Distance (cm)"].where(df["Distance (cm)"] >= 0)

temp, humidity = df["Temperature (°C)"], df["Humidity (%)"]
rh = humidity.clip(lower=1, upper=100)
gamma = np.log(rh / 100) + (17.625 * temp) / (243.04 + temp)
df["Estimated dew point (°C)"] = (243.04 * gamma) / (17.625 - gamma)

gps_count = int(df["Valid GPS point"].sum())
mq7 = df["MQ-7 raw"].dropna()
mq135 = df["MQ-135 digital output"].dropna()
dust = df["Dust output (%)"].dropna()
interpretations = []

if len(mq7):
    interpretations.append(f"**MQ-7 raw response:** minimum {mq7.min():.0f}, maximum {mq7.max():.0f}, average {mq7.mean():.1f}. {trend_sentence(mq7, 'MQ-7').split(': ', 1)[-1]} These are raw sensor readings, not CO ppm.")
if len(mq135):
    interpretations.append(f"**MQ-135 digital output:** recorded state(s): {sorted(mq135.unique().tolist())}. This is a comparator/threshold signal, not a CO₂ concentration.")
    if mq135.nunique() == 1:
        interpretations.append("**MQ-135 data-quality note:** the digital output never changed in this file. Check the threshold potentiometer, wiring, and whether the code reads DO or AO.")
if len(dust):
    interpretations.append(f"**Dust sensor output:** minimum {dust.min():.2f}%, maximum {dust.max():.2f}%, average {dust.mean():.2f}%. {trend_sentence(dust, 'Dust output')} This is not calibrated PM2.5/PM10 in µg/m³.")
if temp.notna().any():
    interpretations.append(f"**Temperature:** {temp.min():.1f}–{temp.max():.1f} °C; average {temp.mean():.1f} °C.")
if humidity.notna().any():
    interpretations.append(f"**Relative humidity:** {humidity.min():.1f}–{humidity.max():.1f}%; average {humidity.mean():.1f}%.")
dew = df["Estimated dew point (°C)"].dropna()
if len(dew):
    interpretations.append(f"**Estimated dew point:** average {dew.mean():.1f} °C, calculated from temperature and humidity; not a direct sensor reading.")
interpretations.append(f"**GPS:** {gps_count} samples have a valid GPS-fix flag and usable coordinates.")
if df["Valid distance (cm)"].notna().any():
    valid_distance = df["Valid distance (cm)"].dropna()
    interpretations.append(f"**Obstacle distance:** {len(valid_distance)} valid distance readings, ranging from {valid_distance.min():.1f} to {valid_distance.max():.1f} cm. Negative sentinel readings were excluded.")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Sensor samples", f"{len(df):,}")
c2.metric("Usable GPS points", f"{gps_count:,}")
c3.metric("Average temperature", f"{temp.mean():.1f} °C" if temp.notna().any() else "N/A")
c4.metric("Average dust output", f"{dust.mean():.2f}%" if dust.notna().any() else "N/A")

tabs = st.tabs(["Interpretation", "Charts", "GPS map", "Data", "Downloads"])
with tabs[0]:
    st.subheader("What the readings suggest")
    for item in interpretations:
        st.markdown(f"- {item}")
    issues = []
    if gps_count == 0:
        issues.append("No GPS points passed the GPS-fix and coordinate checks.")
    if (df["Distance (cm)"] < 0).any():
        issues.append(f"{int((df['Distance (cm)'] < 0).sum())} negative distance values were treated as invalid.")
    if len(mq135) and mq135.nunique() == 1:
        issues.append("MQ-135 digital output is constant; inspect its threshold and signal wiring.")
    st.subheader("Data-quality checks")
    for issue in issues:
        st.warning(issue)
    if not issues:
        st.success("No basic data-quality warnings were found.")
    st.caption("These interpretations describe the uploaded dataset. They are not medical advice, regulatory compliance results, or official AQI.")

with tabs[1]:
    st.subheader("Sensor trends")
    chart_df = df.copy()
    if chart_df["Timestamp parsed"].notna().any():
        chart_df = chart_df.sort_values("Timestamp parsed")
        x_col = "Timestamp parsed"
    else:
        chart_df["Sample number"] = np.arange(1, len(chart_df) + 1)
        x_col = "Sample number"
    chart_specs = [
        ("MQ-7 raw", "MQ-7 raw sensor response", "Raw sensor value"),
        ("Dust output (%)", "Dust sensor output", "Logged dust (%)"),
        ("Temperature (°C)", "Temperature", "°C"),
        ("Humidity (%)", "Relative humidity", "%"),
        ("Satellites", "GPS satellite count", "Satellites"),
        ("Estimated dew point (°C)", "Estimated dew point", "°C"),
    ]
    for column, title, ylabel in chart_specs:
        if chart_df[column].notna().any():
            fig = px.line(chart_df, x=x_col, y=column, markers=True, title=title, labels={x_col: "Time" if x_col == "Timestamp parsed" else "Sample", column: ylabel})
            st.plotly_chart(fig, use_container_width=True)
    if chart_df["MQ-135 digital output"].notna().any():
        st.subheader("MQ-135 digital states")
        st.bar_chart(chart_df["MQ-135 digital output"].value_counts().sort_index())

with tabs[2]:
    st.subheader("Robot GPS route / sample points")
    map_df = df[df["Valid GPS point"]].copy()
    if len(map_df):
        st.caption(f"Showing {len(map_df)} valid points. N/S are treated as latitude and E/W as longitude.")
        map_df = map_df.rename(columns={"Map latitude": "latitude", "Map longitude": "longitude"})
        st.map(map_df, latitude="latitude", longitude="longitude", size=15)
        map_cols = ["Timestamp parsed", "latitude", "longitude", "Satellites", "Altitude (m)", "MQ-7 raw", "Dust output (%)"]
        st.dataframe(map_df[[col for col in map_cols if col in map_df.columns]], use_container_width=True, hide_index=True)
    else:
        st.warning("No usable GPS points were found. Check GPS Fix and the coordinate cells.")

with tabs[3]:
    st.subheader("Saved sensor readings")
    display_cols = [
        "Timestamp parsed", "Mode", "Command", "MQ-7 raw", "MQ-135 digital output",
        "Dust output (%)", "Valid distance (cm)", "GPS fix valid", "Map latitude",
        "Map longitude", "Satellites", "Altitude (m)", "Temperature (°C)",
        "Humidity (%)", "Estimated dew point (°C)"
    ]
    display_cols = [col for col in display_cols if col in df.columns]
    st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

with tabs[4]:
    st.subheader("Download results")
    report_lines = [
        "AIR POLLUTION HUNTER — DATA ANALYSIS",
        f"Workbook: {selected_upload['original_name']}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Samples analyzed: {len(df)}",
        f"Usable GPS points: {gps_count}",
        "",
        "INTERPRETATION",
    ] + [f"- {clean_text(item)}" for item in interpretations] + [
        "",
        "MEASUREMENT LIMITATIONS",
        "- MQ-7 raw readings are not calibrated CO ppm.",
        "- MQ-135 digital output is a threshold state, not CO₂ ppm.",
        "- Dust percentage is not calibrated PM2.5/PM10 in µg/m³.",
        "- Official AQI requires calibrated pollutant concentrations and the applicable standard.",
        "- Dew point is estimated from temperature and relative humidity.",
    ]
    report_text = "\n".join(report_lines)
    st.download_button("⬇ Download interpretation report (.txt)", report_text.encode("utf-8"), "Air_Pollution_Hunter_Report.txt", "text/plain", use_container_width=True)
    csv_data = df[display_cols].to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇ Download cleaned readings (.csv)", csv_data, "Air_Pollution_Hunter_Data.csv", "text/csv", use_container_width=True)

    xlsx_buffer = io.BytesIO()
    with pd.ExcelWriter(xlsx_buffer, engine="openpyxl") as writer:
        df[display_cols].to_excel(writer, index=False, sheet_name="Sensor Data")
        pd.DataFrame({"Interpretation": [clean_text(item) for item in interpretations]}).to_excel(writer, index=False, sheet_name="Interpretation")
    st.download_button("⬇ Download analyzed workbook (.xlsx)", xlsx_buffer.getvalue(), "Air_Pollution_Hunter_Analyzed.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    story = [Paragraph("Air Pollution Hunter", styles["Title"]), Spacer(1, 12)]
    story.append(Paragraph(f"Workbook: {selected_upload['original_name']}<br/>Samples analyzed: {len(df)}<br/>Usable GPS points: {gps_count}", styles["BodyText"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Automatic interpretation", styles["Heading2"]))
    for item in interpretations:
        story.append(Paragraph(clean_text(item).replace("&", "&amp;"), styles["BodyText"]))
        story.append(Spacer(1, 6))
    story.append(Paragraph("Measurement limitations", styles["Heading2"]))
    for item in report_lines[report_lines.index("MEASUREMENT LIMITATIONS") + 1:]:
        story.append(Paragraph(item.replace("&", "&amp;"), styles["BodyText"]))
        story.append(Spacer(1, 4))
    doc.build(story)
    st.download_button("⬇ Download PDF report", pdf_buffer.getvalue(), "Air_Pollution_Hunter_Report.pdf", "application/pdf", use_container_width=True)

st.caption("Shared data is stored in Supabase. MQ-7, MQ-135 digital, and dust outputs retain their calibration limitations; they are not automatically converted to ppm or official AQI.")
