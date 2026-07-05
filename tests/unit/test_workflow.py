# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json
import os
import pytest
from unittest.mock import MagicMock, patch

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from google.adk.runners import InMemoryRunner

from app.agent import vacation_deal_workflow, search_single_chain, exchange_rate_agent, app
from app.config import HOTEL_CHAINS

run_counter = 0

@pytest.fixture(autouse=True)
def clean_history_files():
    """Ensure history and latest results files are clean before/after tests."""
    paths = ["data/price_history.json", "data/latest_results.json"]
    for path in paths:
        if os.path.exists(path):
            os.remove(path)
    yield
    for path in paths:
        if os.path.exists(path):
            os.remove(path)


async def mock_before_model(callback_context: CallbackContext, llm_request: LlmRequest) -> LlmResponse:
    global run_counter
    # Get user message text
    user_msg = llm_request.contents[-1]
    prompt_text = "".join(p.text for p in user_msg.parts if p.text)
    
    try:
        data = json.loads(prompt_text)
        chain_name = data.get("chain", "Mock Chain")
    except Exception:
        chain_name = "Mock Chain"
        
    # Price drops from $100.0 to $85.0 on the second run (15% drop)
    price = 100.0 if run_counter == 0 else 85.0
    
    mock_hotel_data = {
        "hotels": [
            {
                "name": f"{chain_name} Resort Eilat",
                "price": price,
                "meal_plan": "breakfast only",
                "chain": chain_name
            }
        ]
    }
    
    content = types.Content(
        role="model",
        parts=[types.Part.from_text(text=json.dumps(mock_hotel_data))]
    )
    
    grounding_metadata = types.GroundingMetadata(
        grounding_chunks=[
            types.GroundingChunk(
                web=types.GroundingChunkWeb(
                    uri=f"http://{chain_name.lower().replace(' ', '')}.co.il/resort",
                    title=f"{chain_name} Resort Eilat Website"
                )
            )
        ]
    )
    return LlmResponse(content=content, grounding_metadata=grounding_metadata)


async def mock_rate_before_model(callback_context: CallbackContext, llm_request: LlmRequest) -> LlmResponse:
    # Return mock rate of 3.72
    content = types.Content(
        role="model",
        parts=[types.Part.from_text(text='{"rate": 3.72}')]
    )
    return LlmResponse(content=content)


@pytest.mark.asyncio
@patch("smtplib.SMTP")
async def test_workflow_e2e(mock_smtp_class):
    global run_counter
    run_counter = 0
    
    # Configure mock SMTP
    mock_smtp_instance = MagicMock()
    mock_smtp_class.return_value.__enter__.return_value = mock_smtp_instance
    
    # Inject our mock callbacks to intercept LLM calls
    search_single_chain.before_model_callback = mock_before_model
    exchange_rate_agent.before_model_callback = mock_rate_before_model
    
    with patch("app.config.SMTP_USER", "test@example.com"), \
         patch("app.config.SMTP_APP_PASSWORD", "secretpassword"), \
         patch("app.config.SMTP_TO_EMAIL", "alert@example.com"):
        # Setup runner
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
            "desired_price_range": "$50-$150"
        }
        
        # 1. Run Tour 1 (Initial Search: new hotels, no price drop)
        print("\n--- Running Tour 1 (Initial Search) ---")
        async for event in runner.run_async(
            user_id="test_user",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part.from_text(text=json.dumps(search_payload))]),
        ):
            if event.output:
                print(f"Tour 1 Event: author={event.author}, output={type(event.output)}")
                if isinstance(event.output, dict) and "deals_found" in event.output:
                    print("Tour 1 Output:", event.output)
                    assert event.output["deals_found"] == 0
                    assert event.output["notified"] is False
                
        mock_smtp_instance.send_message.assert_not_called()
        
        # Verify history database was written
        db_path = "data/price_history.json"
        assert os.path.exists(db_path)
        with open(db_path, "r") as f:
            history = json.load(f)
        assert len(history) == 1
        
        # Verify latest results database was written and contains ILS conversion ($100 * 3.72 = 372 shekels)
        latest_path = "data/latest_results.json"
        assert os.path.exists(latest_path)
        with open(latest_path, "r") as f:
            latest = json.load(f)
        assert latest["exchange_rate"] == 3.72
        assert len(latest["hotels"]) == len(HOTEL_CHAINS)
        # Verify first hotel price details and matched citation URL
        first_hotel = latest["hotels"][0]
        assert first_hotel["price_usd"] == 100.0
        assert first_hotel["price_ils"] == 372  # 100 * 3.72 = 372
        assert first_hotel["url"] == "http://fattal.co.il/resort"
        
        # 2. Run Tour 2 (Second Search - Price Drop: price dropped to $85, 15% drop)
        run_counter = 1
        print("\n--- Running Tour 2 (Second Search - Price Drop) ---")
        
        session2 = await runner.session_service.create_session(
            app_name="app", user_id="test_user"
        )
        
        async for event in runner.run_async(
            user_id="test_user",
            session_id=session2.id,
            new_message=types.Content(role="user", parts=[types.Part.from_text(text=json.dumps(search_payload))]),
        ):
            if event.output:
                print(f"Tour 2 Event: author={event.author}, output={type(event.output)}")
                if isinstance(event.output, dict) and "deals_found" in event.output:
                    print("Tour 2 Output:", event.output)
                    assert event.output["deals_found"] == len(HOTEL_CHAINS)
                    assert event.output["notified"] is True
                    
        # Verify latest results updated to new shekel prices ($85 * 3.72 = 316.2 -> rounded to 316 shekels)
        with open(latest_path, "r") as f:
            latest = json.load(f)
        first_hotel = latest["hotels"][0]
        assert first_hotel["price_usd"] == 85.0
        assert first_hotel["price_ils"] == 316  # 85 * 3.72 = 316.2 -> 316
        
        # Verify email sent
        mock_smtp_instance.send_message.assert_called_once()
        
        # Verify email headers and content (contains both USD and ILS prices)
        sent_msg = mock_smtp_instance.send_message.call_args[0][0]
        assert sent_msg["From"] == "test@example.com"
        assert sent_msg["To"] == "alert@example.com"
        assert "Vacation Deal Alert" in sent_msg["Subject"]
        
        # Decode email parts to check body text
        body_text = ""
        for part in sent_msg.walk():
            if part.get_content_type() == "text/plain":
                body_text += part.get_payload(decode=True).decode()
                
        assert "Dropped by 15.0%" in body_text
        assert "Fattal Resort Eilat" in body_text
        assert "$85.00 / 316 ₪" in body_text
