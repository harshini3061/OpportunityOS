# OpportunityOS — Streamlit + MySQL

## Run locally on macOS

1. Ensure MySQL is running and the `opportunityos` database exists.
2. Run `01_create_tables.sql` first, then (if desired) `05_replace_with_real_data.sql`.
   **Warning:** the 05 script truncates rows in its target tables before inserting its data. Back up first if you need to preserve existing rows.
3. In this folder, run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
mkdir -p .streamlit
cp secrets.toml.example .streamlit/secrets.toml
```

4. Edit `.streamlit/secrets.toml` and replace `YOUR_MYSQL_PASSWORD` with your MySQL password.
5. Start the app:

```bash
streamlit run app.py
```

Open `http://localhost:8501`.

## Important
- Do not commit `.streamlit/secrets.toml` to GitHub.
- This app expects the schema created by `01_create_tables.sql`, including students, opportunities, applications, skills, domains, organizations and related tables.
- `05_replace_with_real_data.sql` includes fictional demo student profiles/application rows and a small number of opportunity listings. Verify listing details on official sites.
- For Streamlit Community Cloud, `localhost` will not point to your Mac. You need a remotely hosted database and must set the same `DB_*` values in Streamlit Cloud's Secrets settings.
