# Vacation Deal Agent 🏨✈️

An ADK 2.0 graph workflow agent that searches 10 major Israeli hotel chains in parallel, tracks nightly prices over time, converts them to shekels at today's live exchange rate, and emails you when a hotel drops 10% or more in price.

Built with [Google's Agent Development Kit (ADK) 2.0](https://adk.dev/) and [Agents CLI](https://github.com/google/agents-cli), as part of Google's 5-Day AI Agents Intensive Vibe Coding Course.

📄 **Full writeup:** see [`WRITEUP.md`](./WRITEUP.md) for the rationale, architecture deep-dive, and known limitations.

## What it does

Given a city, check-in/check-out dates, number of guests, and meal plan:

1. Searches Fattal, Isrotel, Dan Hotels, VERT, Prima, Astral, Marina Hotels Eilat, and the Israel Canada PLAY/ENJOY brands **concurrently**, using Gemini with Google Search grounding.
2. Fetches today's live USD→ILS exchange rate the same way.
3. Compares every hotel's price against its own search history and computes the percentage change.
4. Emails a summary of any hotel that dropped 10%+ since the last check, with a working booking link.
5. Serves a live dashboard (`web/index.html`) showing every result, sorted deals-first.

## Setup

```bash
uv sync
```

Copy `.env.example` to `.env` and fill in your `GEMINI_API_KEY` and SMTP credentials.

## Running it

```bash
uv run python run_search.py
```

**View the dashboard:**

```bash
python3 -m http.server 8000
# then open http://localhost:8000/web/index.html
```

## Tech Stack

Google ADK 2.0 · Gemini (`gemini-flash-latest`) with Google Search grounding · Agents CLI · Python `asyncio` · `smtplib` · vanilla HTML/CSS/JS
