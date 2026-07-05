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

import os
from dotenv import load_dotenv

load_dotenv()

# Price drop notification threshold (e.g., 0.10 for 10% drop)
PRICE_DROP_THRESHOLD = 0.10

# Fixed list of Israeli hotel chains to search systematically
HOTEL_CHAINS = [
    "Fattal",
    "Isrotel",
    "Dan Hotels",
    "VERT Hotels",
    "Prima Hotels",
    "Astral Hotels",
    "Marina Hotels Eilat",
    "Gordonia Hotels",
    "Israel Canada Hotels PLAY",
    "Israel Canada Hotels ENJOY"
]

# SMTP Configuration Settings
SMTP_HOST = "smtp.gmail.com"  # Default to Gmail SMTP
SMTP_PORT = 587  # TLS port
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_APP_PASSWORD = os.getenv("SMTP_APP_PASSWORD", "")
SMTP_TO_EMAIL = os.getenv("SMTP_TO_EMAIL", SMTP_USER)  # Default to sending to self
