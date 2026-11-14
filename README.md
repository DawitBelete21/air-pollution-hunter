# Air Pollution Hunter — Shared Website

## Features
- Public username + password registration and login (no email field shown to users).
- Supabase Auth securely handles passwords.
- Administrator-only Excel uploads and dataset deletion.
- Uploaded workbooks and parsed sensor rows are stored persistently in Supabase.
- Every authenticated user can view the same saved datasets, interpretations, charts, GPS points, and downloads.
- GPS coordinates are interpreted by N/S and E/W direction even when spreadsheet headings are reversed.

## Required Streamlit secrets
In Streamlit Community Cloud → your app → Settings → Secrets, add:

```toml
SUPABASE_URL = "https://YOUR_PROJECT_ID.supabase.co"
SUPABASE_KEY = "YOUR_SUPABASE_PUBLISHABLE_KEY"
```

Use the Supabase **Project URL** and **Publishable key** (or legacy anon key). Never put a Supabase secret/service_role key in GitHub or Streamlit's public source code.

## Supabase setup
1. In Supabase SQL Editor, run the original database setup SQL already provided in this project. It creates `profiles`, `uploads`, `sensor_readings`, the profile trigger, RLS policies, and the private `pollution-files` bucket.
2. Run the complete contents of `permissions_setup.sql` once in SQL Editor. This grants the minimum Data API table permissions used by the app; RLS still decides which rows each user can access.
3. In Authentication → Sign In / Providers → Email, keep Email enabled and turn **Confirm email OFF**. The app maps usernames to internal synthetic email identifiers; users only enter usernames and passwords.
4. Deploy this repository on Streamlit Community Cloud with the two secrets above.
5. Open the deployed website and create your own account first.
6. In Supabase SQL Editor, open `make_admin.sql`, replace `REPLACE_WITH_YOUR_USERNAME` with your exact username, and run it. Verify the result says `admin`.
7. Log out and back into the website. Your sidebar should show Administrator and the Excel upload controls should appear.

## Account notes
- Usernames are 3–24 characters: lowercase letters, numbers, dot, underscore, or hyphen.
- Passwords must contain at least 8 characters.
- Supabase Auth stores password hashes; this app never stores plaintext passwords.
- Users do not provide email addresses. There is no self-service email password reset; an administrator must handle forgotten-password cases securely.
- The first administrator must be promoted manually in Supabase using `make_admin.sql`. Public signups always receive the `user` role.

## Measurement limitations
- MQ-7 raw values are not calibrated CO ppm.
- MQ-135 digital output is a threshold state, not CO2 ppm.
- Dust percentage is not calibrated PM2.5/PM10 concentration in µg/m³.
- Official AQI requires calibrated pollutant concentrations and the applicable standard.
