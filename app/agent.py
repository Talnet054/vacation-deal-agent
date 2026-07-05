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

import asyncio
import json
import os
from typing import Literal, Optional

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.models import Gemini
from google.adk.tools import google_search
from google.adk.workflow import START, Workflow, node
from google.genai import types
from pydantic import BaseModel, Field

from app.config import HOTEL_CHAINS

# 1. Pydantic Schemas for input and output validation

class SearchRequest(BaseModel):
    city: str = Field(description="The city to search for hotels (e.g. 'Eilat', 'Tel Aviv').")
    check_in: str = Field(description="Check-in date (YYYY-MM-DD).")
    check_out: str = Field(description="Check-out date (YYYY-MM-DD).")
    guests: int = Field(description="Number of guests.")
    meal_plan: Literal["breakfast only", "half board", "full board", "room only"] = Field(
        description="Desired meal plan (breakfast only / half board / full board / room only)."
    )
    desired_price_range: str = Field(description="Desired price range (e.g., '$100-$200').")


class Hotel(BaseModel):
    name: str = Field(description="Name of the hotel.")
    price: float = Field(description="Nightly price of the hotel.")
    meal_plan: str = Field(description="The meal plan offered by the hotel.")
    chain: str = Field(description="The hotel chain this hotel belongs to.")


class HotelList(BaseModel):
    hotels: list[Hotel] = Field(description="A list of hotels matching the search criteria.")


class ExchangeRateOutput(BaseModel):
    rate: float = Field(description="The current USD to ILS exchange rate as a single float (e.g. 3.72).")


# Initialize model with retry options
model = Gemini(
    model="gemini-flash-latest",
    retry_options=types.HttpRetryOptions(attempts=3),
)

# 2. Workflow Nodes implementation

def parse_request(ctx: Context, node_input: SearchRequest) -> Event:
    """Parses input search request and stores it in context state."""
    return Event(output=node_input, state={"search_request": node_input.model_dump()})


# LlmAgent node used dynamically inside search_hotels loop
search_single_chain = LlmAgent(
    name="search_single_chain",
    model=model,
    instruction="""You are a hotel search assistant specializing in finding deals for a specific hotel chain in a city.
    You will receive a search request in JSON format containing: chain, city, check_in date, check_out date, guests, meal_plan, and desired_price_range.
    
    Your task:
    1. Use Google Search to find hotels belonging to the requested chain in the specified city that match the check-in and check-out dates and guest count.
    2. Check the nightly price and identify which meal plan is included/matched.
    3. Return a list of hotels conforming to the output schema. Ensure you populate the `chain` field for each hotel with the requested chain.
    """,
    tools=[google_search],
    output_schema=HotelList,
    generate_content_config=types.GenerateContentConfig(
        tool_config=types.ToolConfig(
            include_server_side_tool_invocations=True
        )
    )
)


@node(rerun_on_resume=True)
async def search_hotels(ctx: Context, node_input: SearchRequest) -> Event:
    """Queries all Israeli hotel chains concurrently and merges results."""
    all_hotels = []
    
    async def run_chain(chain: str):
        chain_input = {
            "chain": chain,
            "city": node_input.city,
            "check_in": node_input.check_in,
            "check_out": node_input.check_out,
            "guests": node_input.guests,
            "meal_plan": node_input.meal_plan,
            "desired_price_range": node_input.desired_price_range,
        }
        safe_chain_name = "".join(c if c.isalnum() else "_" for c in chain).lower()
        run_id = f"search_chain_{safe_chain_name}"
        
        try:
            result = await ctx.run_node(
                search_single_chain,
                node_input=chain_input,
                run_id=run_id
            )
            hotels = result.get("hotels", [])
            for h in hotels:
                h["chain"] = chain  # Tag each hotel with the chain
            return hotels
        except Exception as e:
            print(f"Error searching for chain {chain}: {e}")
            return []

    # Run all search queries concurrently in parallel
    tasks = [run_chain(chain) for chain in HOTEL_CHAINS]
    results = await asyncio.gather(*tasks)
    
    for hotels in results:
        all_hotels.extend(hotels)
            
    return Event(output={"hotels": all_hotels})


# LlmAgent node used dynamically to fetch today's USD to ILS exchange rate
exchange_rate_agent = LlmAgent(
    name="exchange_rate_agent",
    model=model,
    instruction="""Use Google Search to find today's current USD to ILS exchange rate.
    Return it as a single float in the rate field.""",
    tools=[google_search],
    output_schema=ExchangeRateOutput,
    generate_content_config=types.GenerateContentConfig(
        tool_config=types.ToolConfig(
            include_server_side_tool_invocations=True
        )
    )
)


@node(rerun_on_resume=True)
async def get_exchange_rate(ctx: Context, node_input: dict) -> Event:
    """Fetches the current exchange rate and passes the hotels list forward."""
    try:
        result = await ctx.run_node(exchange_rate_agent, run_id="fetch_rate")
        rate = result.get("rate", 3.65)
    except Exception as e:
        print(f"Error fetching exchange rate: {e}")
        rate = 3.65
        
    return Event(output=node_input, state={"exchange_rate": rate})


def compare_prices(ctx: Context, node_input: dict) -> Event:
    """Compares current search prices against database, computes shekel prices, and maps grounding URLs."""
    search_request = ctx.state.get("search_request")
    exchange_rate = ctx.state.get("exchange_rate", 3.65)
    
    if not search_request:
        return Event(output={"compared_hotels": []})
        
    city = search_request.get("city", "").lower().strip()
    check_in = search_request.get("check_in", "").strip()
    check_out = search_request.get("check_out", "").strip()
    guests = str(search_request.get("guests", ""))
    meal_plan = search_request.get("meal_plan", "").lower().strip()
    
    lookup_key = f"{city}|{check_in}|{check_out}|{guests}|{meal_plan}"
    
    db_dir = "data"
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, "price_history.json")
    
    if os.path.exists(db_path):
        try:
            with open(db_path, "r") as f:
                history = json.load(f)
        except Exception:
            history = {}
    else:
        history = {}
        
    prev_results = history.get(lookup_key, {})
    current_prices = {}
    compared_hotels = []
    seen_names = set()
    
    # Extract citations by chain from session events
    citations_by_chain = {}
    for event in ctx.session.events:
        if event.node_info.run_id and event.node_info.run_id.startswith("search_chain_"):
            matched_chain = None
            for chain in HOTEL_CHAINS:
                safe_chain = "".join(c if c.isalnum() else "_" for c in chain).lower()
                if event.node_info.run_id == f"search_chain_{safe_chain}":
                    matched_chain = chain
                    break
            if matched_chain and event.grounding_metadata and event.grounding_metadata.grounding_chunks:
                citations = []
                for chunk in event.grounding_metadata.grounding_chunks:
                    if chunk.web and chunk.web.uri:
                        citations.append((chunk.web.uri, chunk.web.title or ""))
                if citations:
                    if matched_chain not in citations_by_chain:
                        citations_by_chain[matched_chain] = []
                    citations_by_chain[matched_chain].extend(citations)
    
    hotels_list = node_input.get("hotels", [])
    for hotel_data in hotels_list:
        name = hotel_data.get("name")
        if name in seen_names:
            continue
        seen_names.add(name)
        
        price_usd = hotel_data.get("price")
        meal_plan_match = hotel_data.get("meal_plan")
        chain = hotel_data.get("chain", "")
        
        current_prices[name] = price_usd
        
        # Match each hotel to the most relevant citation URL
        hotel_url = None
        chain_citations = citations_by_chain.get(chain, [])
        name_lower = name.lower()
        
        # Core name: split by 'by', 'collection', 'resort', 'hotels', 'hotel'
        core_name = name_lower
        for suffix in ["by", "collection", "resort", "hotels", "hotel"]:
            if f" {suffix}" in core_name:
                core_name = core_name.split(f" {suffix}")[0].strip()
                
        # Try core name match on citation title or uri
        for uri, title in chain_citations:
            title_lower = title.lower()
            uri_lower = uri.lower()
            if core_name in title_lower or core_name.replace(" ", "-") in uri_lower:
                hotel_url = uri
                break
                
        # Try chain name match on citation title
        if not hotel_url:
            chain_lower = chain.lower()
            for uri, title in chain_citations:
                if chain_lower in title_lower:
                    hotel_url = uri
                    break
                    
        # Fallback to the first citation in the chain results if any exists
        if not hotel_url and chain_citations:
            hotel_url = chain_citations[0][0]
            
        # Last resort: fallback to Booking.com search link
        if not hotel_url:
            import urllib.parse
            fallback_query = f"{name} {city}"
            quoted_query = urllib.parse.quote_plus(fallback_query)
            hotel_url = f"https://www.booking.com/searchresults.html?ss={quoted_query}&checkin={check_in}&checkout={check_out}"
        
        # Calculate ILS price rounded to nearest shekel
        price_ils = round(price_usd * exchange_rate)
        
        if name in prev_results:
            prev_price = prev_results[name]
            delta = price_usd - prev_price
            if prev_price > 0:
                drop_pct = (prev_price - price_usd) / prev_price
            else:
                drop_pct = 0.0
            status = "price dropped" if delta < 0 else ("price increased" if delta > 0 else "no change")
        else:
            delta = None
            drop_pct = 0.0
            status = "new"
            
        compared_hotels.append({
            "name": name,
            "price_usd": price_usd,
            "price_ils": price_ils,
            "meal_plan": meal_plan_match,
            "url": hotel_url,
            "chain": chain,
            "delta": delta,
            "drop_percentage": drop_pct,
            "status": status
        })
        
    # Save updated results back to history
    history[lookup_key] = current_prices
    with open(db_path, "w") as f:
        json.dump(history, f, indent=2)
        
    # Save latest results with exchange rate for the web frontend
    latest_path = os.path.join(db_dir, "latest_results.json")
    latest_data = {
        "exchange_rate": exchange_rate,
        "hotels": compared_hotels
    }
    with open(latest_path, "w") as f:
        json.dump(latest_data, f, indent=2)
        
    return Event(output={"compared_hotels": compared_hotels})


def notify_deal(ctx: Context, node_input: dict) -> Event:
    """Sends email notifications for hotels that dropped in price by the configured threshold."""
    from app.config import (
        PRICE_DROP_THRESHOLD,
        SMTP_APP_PASSWORD,
        SMTP_HOST,
        SMTP_PORT,
        SMTP_TO_EMAIL,
        SMTP_USER,
    )
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    
    compared_hotels = node_input.get("compared_hotels", [])
    deals = []
    for h in compared_hotels:
        if h.get("status") == "price dropped" and h.get("drop_percentage", 0.0) >= PRICE_DROP_THRESHOLD:
            deals.append(h)
            
    sent_email = False
    
    if deals:
        subject = "Vacation Deal Alert: Hotel Price Drops!"
        body = "The following hotels have price drops of 10% or more:\n\n"
        for deal in deals:
            body += f"- {deal['name']} ({deal['meal_plan']}): Current nightly price is ${deal['price_usd']:.2f} / {deal['price_ils']} ₪ (Dropped by {deal['drop_percentage']*100:.1f}%, delta vs last time is -${abs(deal['delta']):.2f})\n"
            if deal.get("chain"):
                body += f"  Chain: {deal['chain']}\n"
            if deal.get("url"):
                body += f"  Link: {deal['url']}\n"
            body += "\n"
            
        print(f"Price drop deals found:\n{body}")
        
        if not SMTP_USER or not SMTP_APP_PASSWORD:
            print("WARNING: SMTP credentials (SMTP_USER or SMTP_APP_PASSWORD) not configured in .env. Skipping email notification.")
        else:
            try:
                msg = MIMEMultipart()
                msg['From'] = SMTP_USER
                msg['To'] = SMTP_TO_EMAIL
                msg['Subject'] = subject
                msg.attach(MIMEText(body, 'plain'))
                
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                    server.starttls()
                    server.login(SMTP_USER, SMTP_APP_PASSWORD)
                    server.send_message(msg)
                sent_email = True
                print(f"Successfully sent price drop email notification to {SMTP_TO_EMAIL}")
            except Exception as e:
                print(f"Error sending email: {e}")
    else:
        print("No hotels with price drops of 10% or more found. Skipping email notification.")
        
    output_result = {
        "deals_found": len(deals),
        "notified": sent_email,
        "deals": deals
    }
    
    message_text = f"Found {len(deals)} hotel price drops matching the search criteria."
    if sent_email:
        message_text += f" Email notification sent to {SMTP_TO_EMAIL}."
        
    return Event(
        output=output_result,
        message=message_text
    )


# 3. Create the Workflow Graph and wire up the nodes

vacation_deal_workflow = Workflow(
    name="vacation_deal_workflow",
    edges=[
        (START, parse_request),
        (parse_request, search_hotels),
        (search_hotels, get_exchange_rate),
        (get_exchange_rate, compare_prices),
        (compare_prices, notify_deal),
    ],
    input_schema=SearchRequest,
)

app = App(
    root_agent=vacation_deal_workflow,
    name="app",
)

# Set root_agent for the lifespans to import
root_agent = vacation_deal_workflow
