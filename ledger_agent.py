"""Gemini side: pick a tool from text or voice, draft reminders."""
import os

from google import genai
from google.genai import types

# Use the exact model ID shown in Google AI Studio (set GEMINI_MODEL in your terminal).
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
# Optional backup model, used automatically if the main one errors or times out.
FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")

SYSTEM_PROMPT = """You are a ledger assistant for a small kirana shop in India.
The shopkeeper speaks Kannada, Hindi, English or a mix, transcribed by
speech-to-text, so expect spelling errors and mishearings.

Your job: turn what they say into ledger actions by calling exactly one tool.

Vocabulary:
- "udhaar", "baaki", "sala", "credit", "liya" = customer took goods on credit (credit)
- "diya", "paid", "kotte", "vapas kiya", "jama", "wapas" = customer paid back (payment)
- "kitna baaki hai", "who owes", "kisko zyada baaki" = a query, not an entry

Rules:
1. Never guess. If the person, the amount, or credit-vs-payment is unclear,
   call ask_clarification with ONE short question. Do not call add_entry.
2. add_entry only PROPOSES an entry. The app asks the shopkeeper to confirm.
3. If the name could match several existing customers (e.g. "Ram" with Ramesh
   and Ramu), call ask_clarification with those names as options.
4. If the input is noise, empty, or unrelated to the ledger, call
   ask_clarification saying you could not understand, and to try again.
5. Amounts are in rupees. Never invent customers or amounts.
6. Ask questions in the language the shopkeeper used, in at most 12 words.
7. Input may be romanised, or in Kannada or Devanagari script. Understand all.
8. For payments, use only the amount the shopkeeper clearly stated. Never guess,
   round, or change it based on a customer's balance. The app validates it before saving."""


def _build_tools(with_heard):
    """Same six tools for text and voice. For voice, every tool also carries a
    'heard' field so one call both transcribes and decides."""
    heard = {
        "heard": {
            "type": "string",
            "description": "Exact words the shopkeeper said, romanised, numbers as digits",
        }
    }

    def decl(name, description, props, required=()):
        props = {**props, **(heard if with_heard else {})}
        req = list(required) + (["heard"] if with_heard else [])
        schema = {"type": "object", "properties": props}
        if req:
            schema["required"] = req
        return types.FunctionDeclaration(name=name, description=description, parameters=schema)

    return types.Tool(
        function_declarations=[
            decl(
                "add_entry",
                "Propose a ledger entry for the shopkeeper to confirm.",
                {
                    "person": {"type": "string", "description": "Customer name"},
                    "amount": {"type": "number", "description": "Rupees"},
                    "entry_type": {"type": "string", "enum": ["credit", "payment"]},
                    "note": {"type": "string", "description": "Optional item or remark"},
                },
                ["person", "amount", "entry_type"],
            ),
            decl(
                "get_balance",
                "How much one specific customer owes.",
                {"person": {"type": "string"}},
                ["person"],
            ),
            decl(
                "top_debtors",
                "Customers who owe the most, highest first.",
                {"limit": {"type": "integer"}},
            ),
            decl(
                "draft_reminder",
                "Draft a polite WhatsApp reminder for a customer who owes money.",
                {"person": {"type": "string"}},
                ["person"],
            ),
            decl("undo_last_entry", "Remove the most recent ledger entry.", {}),
            decl(
                "ask_clarification",
                "Ask one short question when the input is unclear or ambiguous.",
                {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tap-to-choose answers, e.g. matching names",
                    },
                },
                ["question"],
            ),
        ]
    )


TOOLS = _build_tools(with_heard=False)
TOOLS_AUDIO = _build_tools(with_heard=True)

FORCE_TOOL = types.ToolConfig(
    function_calling_config=types.FunctionCallingConfig(mode="ANY")
)


def get_client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    # Fail fast: a stuck call errors after 12 s instead of hanging for 40+.
    try:
        opts = types.HttpOptions(
            timeout=12000, retry_options=types.HttpRetryOptions(attempts=1)
        )
    except Exception:  # older SDK without retry_options
        opts = types.HttpOptions(timeout=12000)
    return genai.Client(api_key=key, http_options=opts)


def _generate(client, **kwargs):
    """Call the main model; on any failure try the fallback model once."""
    try:
        return client.models.generate_content(model=MODEL, **kwargs)
    except Exception:
        if FALLBACK_MODEL and FALLBACK_MODEL != MODEL:
            return client.models.generate_content(model=FALLBACK_MODEL, **kwargs)
        raise


def _first_call(resp):
    for part in resp.candidates[0].content.parts:
        if part.function_call:
            return part.function_call.name, dict(part.function_call.args)
    return None


def interpret(client, text, customers):
    """Typed or transcribed text -> (tool_name, args)."""
    resp = _generate(
        client,
        contents=f"Existing customers: {', '.join(customers) or 'none'}\nShopkeeper said: {text}",
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[TOOLS],
            temperature=0,
            tool_config=FORCE_TOOL,
        ),
    )
    return _first_call(resp) or (
        "ask_clarification",
        {"question": "I could not understand. Please try again."},
    )


def interpret_audio(client, audio_bytes, customers, mime_type="audio/wav"):
    """Voice -> (tool_name, args) in ONE call. args['heard'] holds the transcript."""
    resp = _generate(
        client,
        contents=[
            types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            f"Existing customers: {', '.join(customers) or 'none'}\n"
            "The shopkeeper's voice message is attached. Always fill 'heard' with "
            "what they said. If there is no clear speech, call ask_clarification.",
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[TOOLS_AUDIO],
            temperature=0,
            tool_config=FORCE_TOOL,
        ),
    )
    return _first_call(resp) or (
        "ask_clarification",
        {"question": "I could not hear that. Try again.", "heard": ""},
    )


def draft_reminder_text(client, person, amount, language_name):
    prompt = (
        f"Write a WhatsApp message in {language_name} from a kirana shop owner to "
        f"a customer named {person} who owes Rs {amount:,.0f}. "
        "Be warm and polite, 2 to 3 short sentences, mention the amount, ask them "
        "to pay when convenient. No threats, no shaming. Output only the message."
    )
    resp = _generate(
        client, contents=prompt, config=types.GenerateContentConfig(temperature=0.4)
    )
    return (resp.text or "").strip()


def warm_up(client):
    """One tiny request to open the connection before a demo."""
    _generate(client, contents="hi", config=types.GenerateContentConfig(max_output_tokens=5))


def friendly_error(e):
    """Turn an API exception into one plain sentence for the user."""
    s = str(e)
    if "429" in s or "RESOURCE_EXHAUSTED" in s:
        return "Daily AI limit reached for this model. Wait, or switch the model."
    if "503" in s or "UNAVAILABLE" in s or "overloaded" in s.lower():
        return "The AI is busy right now. Tap again in a few seconds."
    if "timed out" in s.lower() or "timeout" in s.lower() or "Deadline" in s:
        return "The AI took too long. Tap again, or type your entry."
    if "404" in s or "NOT_FOUND" in s:
        return "Model not found. Check GEMINI_MODEL against Google AI Studio."
    if "API key" in s or "403" in s or "400" in s:
        return "The API key or request was rejected. Check GEMINI_API_KEY."
    return "The AI could not be reached. Try again, or type your entry."
