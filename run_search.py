import asyncio
import json
from google.genai import types
from google.adk.runners import InMemoryRunner
from app.agent import app

async def main():
    runner = InMemoryRunner(app=app)
    session = await runner.session_service.create_session(
        app_name="app", user_id="test_user"
    )
    search_payload = {
        "city": "Eilat",
        "check_in": "2026-07-10",
        "check_out": "2026-07-15",
        "guests": 2,
        "meal_plan": "breakfast only",
        "desired_price_range": "$100-$300"
    }
    print("Running vacation-deal-agent workflow...")
    async for event in runner.run_async(
        user_id="test_user",
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part.from_text(text=json.dumps(search_payload))]),
    ):
        if event.output:
            print(f"[{event.author}] output: {event.output}")

if __name__ == "__main__":
    asyncio.run(main())
