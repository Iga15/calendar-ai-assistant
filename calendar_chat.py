import os
import sys
import json
import datetime as dt
from dateutil import tz
from dateutil.parser import isoparse

from typing import List, Dict, Any, Optional

# --- Google Calendar imports ---
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- OpenAI (responses) ---
from openai import OpenAI

# ====== CONFIG ======
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
_LOCAL_TZ = tz.gettz("Europe/Warsaw")
if _LOCAL_TZ is None:
    # Fallback just in case the named zone isn't available on the host
    _LOCAL_TZ = tz.tzlocal()
LOCAL_TIMEZONE = _LOCAL_TZ

# ====== AUTH / SERVICE ======
def get_calendar_service() -> Any:
    """
    - Loads OAuth tokens from token.json if present.
    - If missing/expired, runs a local consent flow using credentials.json.
    - Returns a Google Calendar API service client.
    """
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                print("Missing credentials.json (OAuth client). Put it next to this file.")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)

# ====== EVENT HELPERS ======
def rfc3339(dt_obj: dt.datetime) -> str:
    """Return an RFC3339 string in UTC for Google API queries."""
    return dt_obj.astimezone(tz.UTC).isoformat()

def to_local(when: Optional[str]) -> dt.datetime:
    """
    Convert a Google Calendar date/time field to local datetime.
    Handles all-day events (date) and timed events (dateTime).
    If value is missing, returns 'now' in local tz (better than crashing).
    """
    if not when:
        return dt.datetime.now(LOCAL_TIMEZONE)
    # Could be 'YYYY-MM-DD' (all-day) or an ISO dateTime with 'T'
    if "T" in when:
        return isoparse(when).astimezone(LOCAL_TIMEZONE)
    # All-day events: interpret as midnight local
    return dt.datetime.fromisoformat(when).replace(tzinfo=LOCAL_TIMEZONE)

def fetch_events(
    service,
    time_min: dt.datetime,
    time_max: dt.datetime,
    max_results: int = 250
) -> List[Dict[str, Any]]:
    """
    - Pulls events between time_min and time_max.
    - Returns a simplified list of dicts you can display or feed to the model.
    """
    try:
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=rfc3339(time_min),
                timeMax=rfc3339(time_max),
                singleEvents=True,
                orderBy="startTime",
                maxResults=max_results,
            )
            .execute()
        )
    except HttpError as e:
        print(f"Google Calendar API error: {e}")
        return []

    items = events_result.get("items", [])

    simplified = []
    for ev in items:
        start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
        end = ev.get("end", {}).get("dateTime") or ev.get("end", {}).get("date")
        start_local = to_local(start)
        end_local = to_local(end)

        simplified.append({
            "id": ev.get("id"),
            "summary": ev.get("summary", "(No title)"),
            "location": ev.get("location"),
            "description": ev.get("description"),
            "start_local": start_local.isoformat(),
            "end_local": end_local.isoformat(),
            "attendees": [a.get("email") for a in ev.get("attendees", [])] if ev.get("attendees") else [],
            "hangoutLink": ev.get("hangoutLink"),
        })
    return simplified

def summarize_day(events: List[Dict[str, Any]], day: dt.date) -> str:
    """
    - Formats one day’s events into a compact bullet list for the model/user.
    - Groups all events that occur on the given day.
    """
    lines = []
    for ev in events:
        s = isoparse(ev["start_local"])
        if s.date() != day:
            continue
        e = isoparse(ev["end_local"])
        time_str = f"{s.strftime('%a %b %d')} {s.strftime('%H:%M')}–{e.strftime('%H:%M')}"
        loc = f" @ {ev['location']}" if ev.get("location") else ""
        lines.append(f"- {time_str}: {ev['summary']}{loc}")
    return "\n".join(lines) if lines else "- No events."

def find_next_event(events: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    - Returns the next upcoming event from 'now' in local timezone.
    """
    now = dt.datetime.now(LOCAL_TIMEZONE)
    upcoming = []
    for ev in events:
        s = isoparse(ev["start_local"])
        if s >= now:
            upcoming.append(ev)
    if not upcoming:
        return None
    # Sort by actual datetime (safer than string sort, though ISO strings would work)
    upcoming.sort(key=lambda x: isoparse(x["start_local"]))
    return upcoming[0]

# ====== OPENAI CHAT ======
def openai_client() -> OpenAI:
    """
    - Creates an OpenAI client using OPENAI_API_KEY from environment.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY in your environment.")
        sys.exit(1)
    return OpenAI(api_key=api_key)

SYSTEM_PROMPT = """You are a helpful calendar assistant.
You are given the user's calendar context (events) and their question.
- Answer using the events provided.
- If the answer depends on time, assume the user's timezone is Europe/Warsaw.
- Be concise and specific; include concrete times and dates.
- If something is not in the events, say you don't know.
"""

def ask_llm(client: OpenAI, question: str, context_text: str, model: str = "gpt-4o-mini") -> str:
    """
    - Sends the user's question + calendar context to the model.
    - Returns the model's reply text.
    """
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"CALENDAR CONTEXT:\n{context_text}\n\nUSER QUESTION:\n{question}"}
    ]
    resp = client.chat.completions.create(model=model, messages=msgs, temperature=0.2)
    return resp.choices[0].message.content.strip()

def build_context(events: List[Dict[str, Any]]) -> str:
    """
    - Creates a compact, model-friendly context of:
      * Next event
      * Today’s agenda
      * Upcoming 7 days (titles + times)
    """
    now = dt.datetime.now(LOCAL_TIMEZONE)
    today = now.date()

    # Today
    today_block = summarize_day(events, today)

    # Next event
    nxt = find_next_event(events)
    if nxt:
        s = isoparse(nxt["start_local"])
        e = isoparse(nxt["end_local"])
        next_block = (
            f"- {nxt['summary']} on {s.strftime('%a %b %d')} from "
            f"{s.strftime('%H:%M')} to {e.strftime('%H:%M')}"
            f"{' @ ' + nxt['location'] if nxt.get('location') else ''}"
        )
    else:
        next_block = "- No upcoming events."

    # Next 7 days overview
    seven_lines = []
    for ev in events:
        s = isoparse(ev["start_local"])
        if today <= s.date() <= (today + dt.timedelta(days=7)):
            e = isoparse(ev["end_local"])
            seven_lines.append(
                f"- {s.strftime('%a %b %d %H:%M')}–{e.strftime('%H:%M')}: {ev['summary']}"
            )
    seven_block = "\n".join(seven_lines) if seven_lines else "- No events in the next 7 days."

    return (
        f"NOW: {now.strftime('%Y-%m-%d %H:%M %Z')}\n\n"
        f"NEXT EVENT:\n{next_block}\n\n"
        f"TODAY ({today.isoformat()}) AGENDA:\n{today_block}\n\n"
        f"UPCOMING 7 DAYS:\n{seven_block}"
    )

# ====== MAIN CHAT LOOP ======
def main():
    """
    - Auths to Google Calendar.
    - Fetches events from yesterday to +14 days (covers most questions).
    - Enters a chat loop where you can ask about your day.
    """
    service = get_calendar_service()

    now = dt.datetime.now(LOCAL_TIMEZONE)
    start_window = (now - dt.timedelta(days=1)).replace(microsecond=0)
    end_window = (now + dt.timedelta(days=14)).replace(microsecond=0)

    events = fetch_events(service, start_window, end_window)

    # Build initial context
    context_text = build_context(events)

    client = openai_client()

    print("Calendar Chatbot ready. Ask about your day (type 'exit' to quit).")
    while True:
        try:
            user_q = input("\nYou: ").strip()
            if user_q.lower() in {"exit", "quit"}:
                print("Bye!")
                break

            # For very specific queries, you could refresh events here if you want:
            # events = fetch_events(service, start_window, end_window)
            # context_text = build_context(events)

            answer = ask_llm(client, user_q, context_text)
            print(f"\nBot: {answer}")
        except KeyboardInterrupt:
            print("\nBye!")
            break
        except Exception as e:
            print(f"\nUnexpected error: {e}")
            break

if __name__ == "__main__":
    main()
