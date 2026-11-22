"""Udhaar Khata: voice ledger for kirana shops. Run: streamlit run app.py"""
import hashlib
from datetime import datetime
import urllib.parse

import streamlit as st

import ledger_agent as agent
import ledger_db as db

st.set_page_config(page_title="Udhaar Khata", page_icon="📒", layout="wide")
db.init(seed=False)

LANGS = {"ಕನ್ನಡ": "Kannada", "हिन्दी": "Hindi", "English": "English"}
BIG_AMOUNT = 5000
EXAMPLES = [
    "Ramesh ne 200 udhaar liya",
    "Suresh kotte 100 rupees",
    "Kisko sabse zyada baaki hai?",
    "Lakshmi ko reminder bhejo",
    "Ram ne 50 diya",
]

st.markdown(
    """<style>
    .stApp {background: #f5f9f6;}
    [data-testid="stSidebar"] {background: #edf5ef;}
    .amount {font-size: 3rem; font-weight: 700; line-height: 1.1; margin: 0.2rem 0; color:#116149;}
    .kind {font-size: 1rem; opacity: 0.7;}
    [data-testid="stMetric"] {background:white;border:1px solid #dbe9df;padding:16px;border-radius:14px;}
    div.stButton > button[kind="primary"] {background:#147451;border-color:#147451;}
    </style>""",
    unsafe_allow_html=True,
)

ss = st.session_state
for key, default in {
    "pending": None,    # entry waiting for confirmation
    "editing": False,
    "output": None,     # last result to show
    "clarify": None,    # question the agent is asking
    "heard": "",
    "to_process": None, # text queued for the agent
    "last_audio": None, # hash of last processed recording
}.items():
    ss.setdefault(key, default)


@st.cache_resource
def get_client():
    return agent.get_client()


try:
    client = get_client()
except RuntimeError as e:
    st.error(f"{e}. Set it in your terminal, then restart the app.")
    st.stop()


# ---------- callbacks ----------
def queue(text):
    ss.to_process = text


def cancel():
    ss.pending, ss.editing = None, False
    ss.payment_authorized = False
    ss.output = {"kind": "info", "text": "Cancelled. Nothing was saved."}


def confirm():
    p = ss.pending
    if p["entry_type"] == "payment" and not ss.get("payment_authorized", False):
        ss.output = {"kind": "error", "text": "Confirm that you checked the customer's balance before recording this payment."}
        return
    try:
        db.add_entry(p["person"], p["amount"], p["entry_type"], p.get("note", ""))
        ss.output = {"kind": "saved", "entry": p, "balance": db.balance(p["person"])}
        ss.pending, ss.editing = None, False
    except ValueError as e:
        ss.output = {"kind": "error", "text": str(e)}


def start_edit():
    p = ss.pending
    ss.edit_person, ss.edit_amount, ss.edit_type = p["person"], p["amount"], p["entry_type"]
    ss.editing = True


def save_edit():
    person = ss.edit_person.strip() or ss.pending["person"]
    canon = db.canonical(person)
    ss.pending = {
        **ss.pending,
        "person": canon or person,
        "amount": float(ss.edit_amount),
        "entry_type": ss.edit_type,
        "is_new": canon is None,
    }
    ss.editing = False
    ss.payment_authorized = False


def undo():
    row = db.undo_last()
    if row:
        ss.output = {
            "kind": "info",
            "text": f"Recorded a reversal for {row['person']}, ₹{row['amount']:,.0f} ({row['entry_type']}). Original entry #{row['id']} remains in the audit history.",
        }
    else:
        ss.output = {"kind": "info", "text": "Nothing to undo."}


def reset_demo():
    ss.output = {"kind": "error", "text": "Reset is disabled to protect your ledger history."}


# ---------- agent turn ----------
def process(text=None, audio=None):
    """One agent turn. Give typed/queued text, or raw audio bytes (one call)."""
    ss.pending, ss.editing, ss.clarify, ss.output = None, False, None, None
    ss.payment_authorized = False
    try:
        if audio is not None:
            name, args = agent.interpret_audio(client, audio, db.customers())
            text = str(args.pop("heard", "")).strip()
        else:
            name, args = agent.interpret(client, text, db.customers())
    except Exception as e:
        ss.heard = text or ""
        ss.output = {"kind": "error", "text": agent.friendly_error(e)}
        return
    ss.heard = text or ""

    if name == "add_entry":
        person = str(args.get("person", "")).strip()
        amount = float(args.get("amount") or 0)
        if not person or amount <= 0:
            ss.clarify = {"question": "Who, and how much?", "options": [], "original": text}
            return
        canon = db.canonical(person)
        ss.pending = {
            "person": canon or person,
            "amount": amount,
            "entry_type": args.get("entry_type", "credit"),
            "note": args.get("note", ""),
            "is_new": canon is None,
        }
    elif name == "get_balance":
        canon = db.canonical(args.get("person", ""))
        if canon is None:
            ss.output = {"kind": "info", "text": f"No customer named {args.get('person')}. "
                                                  f"Customers: {', '.join(db.customers())}."}
        else:
            ss.output = {"kind": "balance", "person": canon, "balance": db.balance(canon)}
    elif name == "top_debtors":
        ss.output = {"kind": "debtors", "rows": db.top_debtors(int(args.get("limit") or 3))}
    elif name == "draft_reminder":
        canon = db.canonical(args.get("person", ""))
        if canon is None:
            ss.output = {"kind": "info", "text": f"No customer named {args.get('person')}."}
        elif db.balance(canon) <= 0:
            ss.output = {"kind": "info", "text": f"{canon} does not owe anything."}
        else:
            bal = db.balance(canon)
            try:
                msg = agent.draft_reminder_text(client, canon, bal, LANGS[ss.lang_label])
                ss.reminder_box = msg
                ss.output = {"kind": "reminder", "person": canon}
            except Exception as e:
                ss.output = {"kind": "error", "text": agent.friendly_error(e)}
    elif name == "undo_last_entry":
        undo()
    else:  # ask_clarification
        ss.clarify = {
            "question": args.get("question", "Can you say that again?"),
            "options": list(args.get("options") or []),
            "original": text,
        }


# ---------- header ----------
st.title("📒 Udhaar Khata")
st.caption("A clear, reliable view of your shop's customer credit ledger.")
summary = db.analytics()
k1,k2,k3,k4 = st.columns(4)
k1.metric("Outstanding", f"₹{summary['outstanding']:,.0f}")
k2.metric("Credits recorded", f"₹{summary['credits']:,.0f}")
k3.metric("Payments received", f"₹{summary['payments']:,.0f}")
k4.metric("Customers", len(db.customers()))
with st.expander("Last 30 days", expanded=False):
    a,b=st.columns(2)
    a.metric("Credit added",f"₹{summary['recent_credits']:,.0f}")
    b.metric("Payments received",f"₹{summary['recent_payments']:,.0f}")
st.caption("Speak or type a transaction. Every entry waits for your confirmation.")
st.radio("Reminder language", list(LANGS), horizontal=True, key="lang_label")

# ---------- input ----------
audio = st.audio_input("Tap and speak")
with st.form("typed", clear_on_submit=True):
    typed = st.text_input("Or type it", placeholder="Ramesh ne 200 udhaar liya")
    sent = st.form_submit_button("Send")
if sent and typed.strip():
    queue(typed.strip())

if audio is not None:
    data = audio.getvalue()
    digest = hashlib.md5(data).hexdigest()
    if digest != ss.last_audio:
        ss.last_audio = digest
        with st.spinner("Listening..."):
            process(audio=data)

if ss.to_process:
    text, ss.to_process = ss.to_process, None
    with st.spinner("Understanding..."):
        process(text)

# ---------- result area ----------
if ss.heard:
    st.caption(f'🎧 Heard: "{ss.heard}"')

if ss.clarify:
    c = ss.clarify
    with st.container(border=True):
        st.markdown(f"**{c['question']}**")
        for opt in c["options"]:
            st.button(opt, key=f"opt_{opt}", on_click=queue,
                      args=(f"{c['original']} (I mean {opt})",))
        st.caption("Or say it again, or type it above.")

if ss.pending:
    p = ss.pending
    with st.container(border=True):
        if ss.editing:
            st.text_input("Customer", key="edit_person")
            st.number_input("Amount (₹)", min_value=0.0, step=10.0, key="edit_amount")
            st.radio("Type", ["credit", "payment"], horizontal=True, key="edit_type",
                     format_func=lambda x: "Udhaar (took on credit)" if x == "credit" else "Payment (paid back)")
            st.button("Update", type="primary", on_click=save_edit)
        else:
            kind = "Udhaar: customer took on credit" if p["entry_type"] == "credit" else "Payment: customer paid back"
            st.markdown(f'<div class="kind">{kind}</div><div class="amount">₹{p["amount"]:,.0f}</div>',
                        unsafe_allow_html=True)
            st.markdown(f"**{p['person']}**" + ("  ·  new customer" if p["is_new"] else ""))
            if p["amount"] >= BIG_AMOUNT:
                st.warning("This is a large amount. Check the number before saving.")
            if p["entry_type"] == "payment":
                current = db.balance(p["person"])
                if p["amount"] > current:
                    st.error(f"This payment is greater than the current balance (₹{max(0,current):,.2f}). Please edit it.")
                st.checkbox("I checked the customer's outstanding balance", key="payment_authorized")
            b1, b2, b3 = st.columns(3)
            b1.button("Yes, save", type="primary", on_click=confirm,
                      disabled=(p["entry_type"] == "payment" and (p["amount"] > db.balance(p["person"]) or not ss.get("payment_authorized",False))))
            b2.button("Edit", on_click=start_edit)
            b3.button("Cancel", on_click=cancel)

out = ss.output
if out:
    k = out["kind"]
    if k == "saved":
        e = out["entry"]
        verb = "added to" if e["entry_type"] == "credit" else "taken off"
        st.success(f"Saved. ₹{e['amount']:,.0f} {verb} {e['person']}'s account. "
                   f"They now owe ₹{out['balance']:,.0f}.")
    elif k == "balance":
        st.info(f"{out['person']} owes ₹{out['balance']:,.0f}.")
    elif k == "debtors":
        if out["rows"]:
            st.info("Owe the most:\n\n" + "\n".join(f"- {p}: ₹{b:,.0f}" for p, b in out["rows"]))
        else:
            st.info("Nobody owes anything right now.")
    elif k == "reminder":
        st.markdown(f"**Reminder for {out['person']}**")
        st.text_area("Edit before sending", key="reminder_box", height=130)
        link = "https://wa.me/?text=" + urllib.parse.quote(ss.reminder_box)
        st.link_button("Open in WhatsApp", link)
    elif k == "error":
        st.error(out["text"])
    else:
        st.info(out["text"])

# ---------- ledger ----------
st.divider()
st.divider()
tab_dash, tab_customers, tab_history, tab_analytics = st.tabs(["Dashboard", "Customer profiles", "Transactions", "Analytics"])
with tab_dash:
    st.subheader("Customer balances")
    rows = [{"Customer": p, "Outstanding (₹)": round(b,2)} for p, b in db.balances().items()]
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.download_button("Export ledger as CSV",data=db.export_csv(),file_name=f"udhaar-ledger-{datetime.now():%Y%m%d}.csv",mime="text/csv")
with tab_customers:
    st.subheader("Customer profiles")
    people=db.customers()
    if people:
        selected=st.selectbox("Select customer",people,key="profile_customer")
        profile=db.customer_profile(selected)
        with st.form("profile_form"):
            phone=st.text_input("Phone number",value=profile.get("phone",""))
            notes=st.text_area("Notes",value=profile.get("notes",""),help="Optional shop notes; avoid storing sensitive information.")
            saved=st.form_submit_button("Save profile")
        if saved:
            db.save_customer_profile(selected,phone,notes)
            st.success("Profile saved.")
        st.metric("Current outstanding",f"₹{db.balance(selected):,.2f}")
        st.caption("Recent transactions")
        st.dataframe([dict(r) for r in db.customer_entries(selected,20)],hide_index=True,use_container_width=True)
    else:
        st.info("Customer profiles will appear after the first confirmed entry.")
with tab_history:
    st.subheader("Transaction history")
    st.dataframe([dict(r) for r in db.recent(100)],hide_index=True,use_container_width=True)
    st.button("Undo latest transaction",on_click=undo,help="Adds an audited counter-entry; original history is retained.")
    with st.expander("Audit trail"):
        st.dataframe([dict(r) for r in db.audit_recent(50)],hide_index=True,use_container_width=True)
with tab_analytics:
    st.subheader("Ledger analytics")
    balrows=[{"Customer":p,"Outstanding (₹)":round(b,2)} for p,b in db.top_debtors(10)]
    if balrows: st.bar_chart(balrows,x="Customer",y="Outstanding (₹)")
    st.caption(f"{summary['count']} transaction records, including any audit-preserving reversals.")

# ---------- sidebar ----------
with st.sidebar:
    st.subheader("Try saying")
    for ex in EXAMPLES:
        st.button(ex, on_click=queue, args=(ex,), key=f"ex_{ex}")
    st.divider()
    if st.button("Warm up AI (before demo)"):
        with st.spinner("Warming up..."):
            try:
                agent.warm_up(client)
                st.success("Ready.")
            except Exception as e:
                st.error(agent.friendly_error(e))
    st.caption(f"Model: {agent.MODEL}" + (f" (backup: {agent.FALLBACK_MODEL})" if agent.FALLBACK_MODEL else ""))
    st.caption("Ledger reset is disabled to protect existing records.")
