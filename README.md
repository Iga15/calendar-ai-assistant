# Calendar AI Assistant

A command-line assistant that connects to your **Google Calendar** and uses an **OpenAI model** to answer natural language questions about your schedule — like “What’s my next meeting?” or “Do I have anything on Friday afternoon?”

---

## 🧩 Features
- Authenticates securely with **Google Calendar API** (OAuth 2.0)
- Fetches upcoming and past events automatically
- Converts event data into a compact natural-language context
- Uses an **OpenAI model** (e.g. `gpt-4o-mini`) to answer calendar-related questions
- Handles both all-day and timed events in your local timezone

---

## 📂 Project Structure
```
calendar-ai-assistant/
├── calendar_assistant.py    # Main code (this file)
├── requirements.txt          # Dependencies
├── .gitignore
├── README.md
├── credentials.json          # (OAuth client from Google Cloud) – not tracked
└── token.json                # Generated automatically after first login
```

---

## ⚙️ Setup

1. **Clone the repo**
   ```bash
   git clone https://github.com/Iga15/calendar-ai-assistant.git
   cd calendar-ai-assistant
   ```
2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
3.	**Set up Google Calendar API**
	-	Go to Google Cloud Console → APIs & Services → Credentials
	-	Create an OAuth client ID for “Desktop app”
	-	Download the JSON and rename it to credentials.json
	-	Place it in the project root

4.	**Set your OpenAI key**
    ```bash
    export OPENAI_API_KEY="your_api_key_here"
    ```
5. **Run**

   The script will:
	-	Open a browser for Google sign-in (first run only)
	-	Cache your token in token.json
	-	Fetch recent and upcoming events
	-	Let you chat about your calendar

---

## 🧠 How It Works
-	fetch_events() → downloads your calendar events via Google API
-	build_context() → builds a readable, model-friendly summary
-	ask_llm() → sends your question and context to the OpenAI API
-	The model replies concisely based on your actual events

---
## 🪪 Notes
- Your tokens (token.json) and credentials are never uploaded.
- The local timezone defaults to Europe/Warsaw.
- You can change the model or timezone directly in the script.
