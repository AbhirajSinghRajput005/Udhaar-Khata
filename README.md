# Udhaar Khata

A Streamlit customer credit ledger with Gemini-assisted voice and text entry. On first run, the app creates a local SQLite database named `ledger.db` alongside `app.py`. The database is intentionally not included in this repository because it can contain customer data. If a local database already exists, startup performs additive table migrations only; it does not seed, clear, or rewrite ledger records.

## Run locally (Windows PowerShell)

1. Install Python 3.10 or newer.
2. Open PowerShell in this folder and create/activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Set your Gemini API key for this PowerShell session:

   ```powershell
   $env:GEMINI_API_KEY = "your-key"
   ```

   Optional model overrides: `$env:GEMINI_MODEL` and `$env:GEMINI_FALLBACK_MODEL`.

4. Start the app:

   ```powershell
   streamlit run app.py
   ```

The app asks for confirmation before saving any proposed transaction. Payments must not exceed the customer's current outstanding balance and require an explicit balance-check confirmation. Undo appends a counter-entry and audit record, retaining the original transaction. Export the ledger from the Dashboard as CSV.

## Data safety

`ledger.db` is the local source of truth and is excluded from Git. Back it up before replacing or moving project files. The app never invokes a reset or deletes entries. Customer phone numbers and notes are stored locally in SQLite. Keep the database private and make backups in a secure location.
