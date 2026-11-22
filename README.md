# Udhaar Khata

**Udhaar Khata** is a voice-first, local customer credit ledger for small kirana shops. It lets shopkeepers record credit and payment entries in Kannada, Hindi, English, or mixed language using voice or text, while keeping the shopkeeper in control of every saved transaction.

The application is built with Python and Streamlit, uses Gemini function calling to interpret requests, and stores ledger data in a local SQLite database.

## For judges: 5-minute evaluation

1. Follow the [Quick start](#quick-start).
2. Open the app at `http://localhost:8501`.
3. Enter a clearly stated sample instruction, such as:
   - `Ramesh ne 200 udhaar liya`
   - `Ram ne 50 diya`
   - `Suresh ko kitna baaki hai?`
   - `Kisko sabse zyada baaki hai?`
   - `Lakshmi ko reminder bhejo`
4. Review the proposed entry and select **Yes, save**, or use **Edit** to correct it.
5. Open **Customer profiles**, **Transactions**, and **Analytics** to inspect the result.
6. Export the ledger from the **Dashboard** to verify CSV download.

The app starts with an empty ledger. It does not seed sample or customer data.

## Why this project matters

Small shops often maintain credit informally in notebooks or memory. This creates avoidable problems:

- A shopkeeper may be busy and unable to write while serving customers.
- Balances can be difficult to calculate accurately.
- A mistaken entry may be corrected by overwriting history.
- Hindi, Kannada, English, and mixed speech are not handled consistently by ordinary forms.

Udhaar Khata addresses these problems with a low-learning-curve interface:

- **Natural voice and text input** — Gemini identifies the customer, amount, and transaction type.
- **Human confirmation** — AI proposes an entry; the shopkeeper explicitly approves or edits it.
- **Local ledger** — balances and transaction history remain in SQLite on the shop computer.
- **Audit-safe corrections** — undo creates a compensating entry instead of deleting or rewriting history.
- **Accessible customer tools** — profiles, balances, reminders, charts, history, and CSV export are available in one interface.

## Core features

### Voice and text-ledger entry

- Accepts typed commands or live browser audio.
- Supports Kannada, Hindi, English, and Romanized mixed-language input.
- Converts an instruction into one structured ledger action.
- Asks a clarification question when customer, amount, or credit/payment direction is unclear.
- Prevents the AI from guessing or silently inventing ledger values.

### Payment and credit safeguards

- Separates `credit` (customer took goods on credit) from `payment` (customer paid back).
- Requires explicit confirmation before saving a proposed entry.
- Requires a balance check for every payment.
- Blocks a payment that exceeds the customer's current outstanding balance.
- Highlights unusually large amounts for review.
- Validates positive, finite amounts and valid transaction types at the database layer.

### Customer profiles

- Automatically creates a customer record when the first confirmed entry is saved.
- Matches common name variations and existing customer names.
- Stores optional phone numbers and private shop notes locally.
- Shows a customer's current balance and recent transactions.

### Transaction history and undo

- Displays the latest 100 transaction records.
- Shows an audit trail of entries and profile changes.
- **Undo latest transaction** appends an opposite counter-entry.
- The original transaction remains unchanged and is referenced by the counter-entry.

### Reminders and analytics

- Generates polite, 2–3 sentence WhatsApp reminder drafts in Kannada, Hindi, or English.
- Opens the draft in WhatsApp without automatically sending a message.
- Shows outstanding totals, credits, payments, customer count, 30-day totals, balances, and a debtor chart.
- Exports all transaction rows to CSV from the Dashboard.

## Quick start

### Prerequisites

- Python 3.10 or newer
- A Gemini API key
- A microphone if evaluating voice input
- Internet access for Gemini requests

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
$env:GEMINI_API_KEY = "your-gemini-api-key"
streamlit run app.py
```

Open `http://localhost:8501`. For a persistent shell variable on Windows, use:

```powershell
[Environment]::SetEnvironmentVariable("GEMINI_API_KEY", "your-gemini-api-key", "User")
```

Restart the terminal after setting a persistent environment variable.

### macOS or Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
export GEMINI_API_KEY="your-gemini-api-key"
streamlit run app.py
```

### Optional configuration

The default model and fallback model can be replaced with model IDs available to the API key:

```powershell
$env:GEMINI_MODEL = "your-primary-model"
$env:GEMINI_FALLBACK_MODEL = "your-fallback-model"
```

If `GEMINI_FALLBACK_MODEL` is not set, the code uses its built-in fallback model. Set it to another model ID or the same value as the primary model to control fallback behavior.

## Suggested demo commands

| Example | What the app evaluates |
|---|---|
| `Ramesh ne 200 udhaar liya` | Mixed-language credit entry |
| `Suresh kotte 100 rupees` | Kannada/English-style payment input |
| `Ram ne 50 diya` | Devanagari-script/romanized payment input |
| `Suresh ko kitna baaki hai?` | Customer balance query |
| `Kisko sabse zyada baaki hai?` | Top-debtors query |
| `Lakshmi ko reminder bhejo` | Polite WhatsApp reminder draft |
| `Send 500 for Ramesh` | Ambiguity handling: the app will ask whether this is credit or payment |

For voice evaluation, tap **Tap and speak**, give a short instruction, and wait for processing. The app sends the audio and existing customer names to Gemini in one request.

## How it works

```text
Shopkeeper voice or text
        |
        v
Streamlit interface (app.py)
        |
        v
Gemini function-calling layer (ledger_agent.py)
        |
        v
One structured action:
add entry | balance | top debtors | reminder | undo | clarification
        |
        v
Shopkeeper review and explicit confirmation
        |
        v
SQLite transaction and audit data (ledger_db.py)
```

### Project structure

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI, state management, callbacks, confirmation flow, and dashboard |
| `ledger_agent.py` | Gemini client, function declarations, voice/text interpretation, reminder generation, and user-friendly errors |
| `ledger_db.py` | SQLite schema, migrations, balances, profiles, analytics, export, undo, and audit operations |
| `requirements.txt` | Python dependencies |
| `.streamlit/config.toml` | App theme |
| `.gitignore` | Excludes local environment and database files |

## Data storage and safety

- `ledger.db` is created beside `app.py` on the first run.
- The database is the local source of truth.
- The repository excludes `ledger.db` and `.streamlit/secrets.toml`.
- Startup creates missing tables and adds missing columns; it does not seed or rewrite existing records.
- The app has no destructive reset command.
- Customer phone numbers and notes are stored locally in SQLite.
- CSV export contains transaction data and should be handled securely.
- Back up `ledger.db` before moving or replacing the application files.
- Do not upload real customer data to public demos or repositories.

Adding an entry is validated and saved inside a SQLite transaction. The database also rejects payments above the recorded outstanding balance. Undo appends a counter-entry rather than deleting the original or rebuilding earlier balances.

## Gemini API and privacy

The Gemini integration is used to:

- understand text and voice instructions;
- select a ledger tool;
- extract customer, amount, entry type, and optional reminder language;
- draft reminder messages.

Text or audio sent to Gemini should be considered external service data. A production deployment should obtain appropriate customer consent, define a data-retention policy, protect API credentials, and consider hosting or data-residency requirements.

No API key is stored in the repository. Set `GEMINI_API_KEY` through your shell environment.

## Troubleshooting

### `GEMINI_API_KEY is not set`

Set the key in the same terminal session that starts Streamlit, then restart the app.

### `Model not found`

Check `GEMINI_MODEL` and `GEMINI_FALLBACK_MODEL` against the models available to the configured Gemini API key.

### `The AI took too long`

The app uses a 12-second request timeout. Try the warm-up action in the sidebar, use a shorter instruction, or type the entry instead of using voice.

### Microphone does not appear

Use a supported modern browser, grant microphone permission, and serve the app over a local origin or HTTPS.

### Payment is disabled

The payment amount may be higher than the customer's recorded balance, or the **I checked the customer's outstanding balance** confirmation may not be selected.

### Ledger is empty after startup

This is intentional. `ledger.db` is not committed to Git because it may contain customer data. Confirmed entries will populate the database.

## Limitations

- This is a local, single-computer Streamlit application, not a multi-user hosted accounting system.
- AI interpretation depends on Gemini availability and API quota.
- Voice quality depends on browser audio capture and the clarity of the spoken request.
- WhatsApp is opened through a share link; the app does not send messages automatically.
- `ledger.db` should be backed up separately if it contains real shop data.

## Technology

- **Python 3.10+**
- **Streamlit**
- **Google Gemini / google-genai**
- **SQLite**
