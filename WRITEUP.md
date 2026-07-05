# Vacation Deal Agent 🏨✈️

An ADK 2.0 agent that hunts down Israeli hotel deals across 10 major chains, tracks price changes over time, and emails you the moment a real discount shows up.

## The Problem

Planning a vacation in Israel means checking half a dozen hotel chain websites separately, each with their own pricing quirks, and no easy way to know if today's price is actually a good deal. I wanted an agent that checks a destination, compares it against what it cost last time, and only bothers me by email when something is genuinely worth booking.

## Architecture

Built as an ADK 2.0 graph Workflow: START → parse_request → search_hotels → get_exchange_rate → compare_prices → notify_deal

- search_hotels runs 10 hotel-chain searches concurrently via asyncio.gather over ctx.run_node, each an LlmAgent with Google Search grounding.
- get_exchange_rate fetches today's live USD/ILS rate the same way.
- compare_prices is deterministic Python: no LLM, just history lookup, delta math, and deduplication.
- notify_deal emails price drops of 10%+ via smtplib, degrading gracefully with no SMTP configured.

## What Was Genuinely Interesting

Business logic lives in code; the LLM is only used where judgment or live web access is actually needed. Link quality was a real problem: LLM-written URLs were sometimes stale or hallucinated, so I extract real Google Search grounding citations from the ADK event history instead, falling back to a pre-filled Booking.com search link when no citation matches. Concurrency also mattered: sequential chain searches caused unreliable timeouts; running them in parallel made the workflow finish reliably, not just faster.

## Known Limitations

Prices reflect what search grounding surfaces, not a live scrape of the booking engine, so small discrepancies are possible. Currently scoped to Israeli hotel chains. Runs on-demand rather than as a persistent cloud service, by deliberate scope choice for this course.

## Tech Stack

Google ADK 2.0, Gemini with Google Search grounding, Agents CLI, Python asyncio, smtplib, vanilla HTML/CSS/JS.
