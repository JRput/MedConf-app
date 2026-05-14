**MedConf**

Agentic Scraper

**Technical Build & Implementation Guide**

  ----------------------------------- -----------------------------------
  **Version**                         1.0

  **Date**                            February 2026

  **Purpose**                         Cursor development reference

  **Language**                        Python 3.11+

  **Database**                        Supabase (PostgreSQL)
  ----------------------------------- -----------------------------------

**1. Overview & Purpose**

This document is a step-by-step technical build guide for the MedConf
Agentic Scraper. It is written to be used directly as a reference by
Cursor or any AI-assisted coding tool to implement the scraper from
scratch. Every section contains the exact project structure,
dependencies, code, configuration, and implementation logic required.
Nothing is left abstract --- each component can be built by following
the instructions in order.

The scraper is a background system that runs on a weekly schedule. It
reads a list of trusted medical conference websites from a Supabase
database table, navigates each site autonomously using a browser
automation tool (Playwright) guided by a large language model (Anthropic
Claude), extracts structured conference data, validates it, and writes
it back to Supabase. It handles duplicates, archives expired events, and
logs every run for monitoring.

+-----------------------------------------------------------------------+
| **How to use this document**                                          |
|                                                                       |
| Each section builds on the previous one. Follow the sections in       |
| order. Code blocks are production-ready and can be copied directly    |
| into files. File paths are specified at the top of each code block.   |
| Where environment variables or API keys are needed, they are called   |
| out explicitly.                                                       |
+-----------------------------------------------------------------------+

**2. Tech Stack & Dependencies**

**2.1 Technology Choices**

  ----------------- -------------------------- --------------------------
  **Component**     **Technology**             **Role in Scraper**

  Language          Python 3.11+               Core runtime for all
                                               scraper logic

  Browser           Playwright (Python SDK)    Navigates websites, reads
  Automation                                   page content, clicks links

  LLM               Anthropic Claude API       Decision-making brain ---
                                               interprets pages and
                                               decides next actions

  Database          Supabase (PostgreSQL)      Stores scraper source
                                               registry and extracted
                                               conference data

  Supabase Client   supabase Python SDK        Reads/writes data to
                                               Supabase from Python

  Scheduler         APScheduler                Runs the scraper on a
                                               weekly cron schedule
                                               within the Python process

  Environment       .env + python-dotenv       Securely stores API keys
  Variables                                    and configuration
  ----------------- -------------------------- --------------------------

**2.2 Installation**

Create a new Python project and install all dependencies with the
following commands:

+-----------------------------------------------------------------------+
| \# Create project directory and navigate into it                      |
|                                                                       |
| mkdir medconf-scraper                                                 |
|                                                                       |
| cd medconf-scraper                                                    |
|                                                                       |
| \# Create and activate a virtual environment                          |
|                                                                       |
| python -m venv venv                                                   |
|                                                                       |
| source venv/bin/activate \# macOS / Linux                             |
|                                                                       |
| \# venv\\Scripts\\activate \# Windows                                 |
|                                                                       |
| \# Install all required packages                                      |
|                                                                       |
| pip install playwright anthropic supabase apscheduler python-dotenv   |
|                                                                       |
| \# Install Playwright browser binaries (required --- do not skip)     |
|                                                                       |
| playwright install chromium                                           |
+-----------------------------------------------------------------------+

+-----------------------------------------------------------------------+
| **Important**                                                         |
|                                                                       |
| The playwright install chromium command downloads the actual browser  |
| binary that Playwright controls. This is separate from pip install    |
| playwright and must be run after. Without it, the scraper will fail   |
| at runtime.                                                           |
+-----------------------------------------------------------------------+

**3. Project Structure**

The scraper is organised into the following file structure. Each file
has a single, clear responsibility. Create all files and directories
exactly as shown before writing any code.

+-----------------------------------------------------------------------+
| medconf-scraper/                                                      |
|                                                                       |
| ├── .env \# Environment variables (API keys, Supabase URL)            |
|                                                                       |
| ├── requirements.txt \# Python dependencies (for deployment)          |
|                                                                       |
| ├── main.py \# Entry point --- starts the scheduler                   |
|                                                                       |
| ├── config.py \# Loads environment variables and exposes them as      |
| constants                                                             |
|                                                                       |
| ├── database.py \# All Supabase read/write functions                  |
|                                                                       |
| ├── browser.py \# Playwright browser wrapper --- open, navigate,      |
| read, close                                                           |
|                                                                       |
| ├── llm_agent.py \# LLM orchestration loop --- the reasoning engine   |
|                                                                       |
| ├── scraper.py \# Ties everything together --- the main scrape        |
| function per source                                                   |
|                                                                       |
| ├── validator.py \# Validates extracted data before it hits the       |
| database                                                              |
|                                                                       |
| ├── scheduler.py \# Defines the weekly schedule and triggers scraper  |
| runs                                                                  |
|                                                                       |
| └── logger.py \# Logging setup --- writes run logs to console and     |
| Supabase                                                              |
+-----------------------------------------------------------------------+

**4. Environment Variables & Configuration**

**4.1 .env File**

Create a .env file in the project root. This file must never be
committed to version control --- add it to your .gitignore. Replace the
placeholder values with your actual keys.

+-----------------------------------------------------------------------+
| \# .env                                                               |
|                                                                       |
| \# Anthropic API key --- used by the LLM agent                        |
|                                                                       |
| ANTHROPIC_API_KEY=sk-ant-your-key-here                                |
|                                                                       |
| \# Supabase project URL and anonymous public key                      |
|                                                                       |
| SUPABASE_URL=https://your-project-id.supabase.co                      |
|                                                                       |
| SUPABASE_KEY=your-supabase-anon-key-here                              |
|                                                                       |
| \# Scraper behaviour configuration                                    |
|                                                                       |
| SCRAPER_MAX_STEPS=30 \# Max navigation steps per source before        |
| timeout                                                               |
|                                                                       |
| SCRAPER_DELAY_SECONDS=2 \# Delay between page navigations (rate       |
| limiting)                                                             |
|                                                                       |
| SCRAPER_TIMEOUT_MS=10000 \# Browser page load timeout in milliseconds |
+-----------------------------------------------------------------------+

**4.2 config.py**

+-----------------------------------------------------------------------+
| \# config.py                                                          |
|                                                                       |
| import os                                                             |
|                                                                       |
| from dotenv import load_dotenv                                        |
|                                                                       |
| load_dotenv()                                                         |
|                                                                       |
| ANTHROPIC_API_KEY = os.getenv(\"ANTHROPIC_API_KEY\")                  |
|                                                                       |
| SUPABASE_URL = os.getenv(\"SUPABASE_URL\")                            |
|                                                                       |
| SUPABASE_KEY = os.getenv(\"SUPABASE_KEY\")                            |
|                                                                       |
| SCRAPER_MAX_STEPS = int(os.getenv(\"SCRAPER_MAX_STEPS\", \"30\"))     |
|                                                                       |
| SCRAPER_DELAY_SECS = int(os.getenv(\"SCRAPER_DELAY_SECONDS\", \"2\")) |
|                                                                       |
| SCRAPER_TIMEOUT_MS = int(os.getenv(\"SCRAPER_TIMEOUT_MS\",            |
| \"10000\"))                                                           |
+-----------------------------------------------------------------------+

**5. Database Layer**

**5.1 Supabase Table Setup**

Before writing any Python code, you must create the required tables in
Supabase. Log into your Supabase project, go to the SQL Editor, and run
the following statements. These create the two tables the scraper reads
from and writes to.

+-----------------------------------------------------------------------+
| \-- Table 1: Scraper source registry                                  |
|                                                                       |
| \-- Stores the list of websites the scraper will target               |
|                                                                       |
| CREATE TABLE IF NOT EXISTS scraper_sources (                          |
|                                                                       |
| id SERIAL PRIMARY KEY,                                                |
|                                                                       |
| source_name TEXT NOT NULL,                                            |
|                                                                       |
| base_url TEXT NOT NULL UNIQUE,                                        |
|                                                                       |
| extraction_instructions TEXT NOT NULL,                                |
|                                                                       |
| active BOOLEAN DEFAULT TRUE,                                          |
|                                                                       |
| last_scraped_at TIMESTAMPTZ,                                          |
|                                                                       |
| last_status TEXT DEFAULT \'pending\', \-- pending \| success \|       |
| partial \| failed                                                     |
|                                                                       |
| created_at TIMESTAMPTZ DEFAULT NOW(),                                 |
|                                                                       |
| updated_at TIMESTAMPTZ DEFAULT NOW()                                  |
|                                                                       |
| );                                                                    |
|                                                                       |
| \-- Table 2: Conferences                                              |
|                                                                       |
| \-- Stores all extracted conference data                              |
|                                                                       |
| CREATE TABLE IF NOT EXISTS conferences (                              |
|                                                                       |
| id SERIAL PRIMARY KEY,                                                |
|                                                                       |
| source_url TEXT NOT NULL UNIQUE, \-- unique key for duplicate         |
| detection                                                             |
|                                                                       |
| conference_name TEXT NOT NULL,                                        |
|                                                                       |
| specialty TEXT,                                                       |
|                                                                       |
| start_date DATE,                                                      |
|                                                                       |
| end_date DATE,                                                        |
|                                                                       |
| venue_name TEXT,                                                      |
|                                                                       |
| city TEXT,                                                            |
|                                                                       |
| region TEXT,                                                          |
|                                                                       |
| cpd_accredited BOOLEAN DEFAULT FALSE,                                 |
|                                                                       |
| cpd_points INTEGER,                                                   |
|                                                                       |
| abstract_open BOOLEAN DEFAULT FALSE,                                  |
|                                                                       |
| abstract_deadline DATE,                                               |
|                                                                       |
| organiser_url TEXT,                                                   |
|                                                                       |
| description TEXT,                                                     |
|                                                                       |
| archived BOOLEAN DEFAULT FALSE,                                       |
|                                                                       |
| created_at TIMESTAMPTZ DEFAULT NOW(),                                 |
|                                                                       |
| updated_at TIMESTAMPTZ DEFAULT NOW()                                  |
|                                                                       |
| );                                                                    |
|                                                                       |
| \-- Table 3: Conference pricing tiers                                 |
|                                                                       |
| \-- One row per pricing tier per conference                           |
|                                                                       |
| CREATE TABLE IF NOT EXISTS pricing_tiers (                            |
|                                                                       |
| id SERIAL PRIMARY KEY,                                                |
|                                                                       |
| conference_id INTEGER REFERENCES conferences(id) ON DELETE CASCADE,   |
|                                                                       |
| tier_label TEXT NOT NULL, \-- e.g. Student, Consultant, Member,       |
| Non-Member                                                            |
|                                                                       |
| price_gbp NUMERIC(10,2) NOT NULL,                                     |
|                                                                       |
| is_early_bird BOOLEAN DEFAULT FALSE,                                  |
|                                                                       |
| early_bird_deadline DATE,                                             |
|                                                                       |
| created_at TIMESTAMPTZ DEFAULT NOW()                                  |
|                                                                       |
| );                                                                    |
|                                                                       |
| \-- Table 4: Scraper run logs                                         |
|                                                                       |
| \-- Records the outcome of every scraper run for monitoring           |
|                                                                       |
| CREATE TABLE IF NOT EXISTS scraper_logs (                             |
|                                                                       |
| id SERIAL PRIMARY KEY,                                                |
|                                                                       |
| source_id INTEGER REFERENCES scraper_sources(id),                     |
|                                                                       |
| run_started_at TIMESTAMPTZ NOT NULL,                                  |
|                                                                       |
| run_ended_at TIMESTAMPTZ,                                             |
|                                                                       |
| status TEXT NOT NULL, \-- success \| partial \| failed                |
|                                                                       |
| conferences_found INTEGER DEFAULT 0,                                  |
|                                                                       |
| conferences_inserted INTEGER DEFAULT 0,                               |
|                                                                       |
| conferences_updated INTEGER DEFAULT 0,                                |
|                                                                       |
| errors_encountered INTEGER DEFAULT 0,                                 |
|                                                                       |
| error_details TEXT,                                                   |
|                                                                       |
| created_at TIMESTAMPTZ DEFAULT NOW()                                  |
|                                                                       |
| );                                                                    |
+-----------------------------------------------------------------------+

**5.2 Seeding Initial Sources**

After creating the tables, insert your initial source URLs. These are
the websites the scraper will target on its first run. The
extraction_instructions field is the natural language prompt the LLM
will use to navigate and extract data from that specific site.

+-----------------------------------------------------------------------+
| \-- Example: Seed two initial sources                                 |
|                                                                       |
| INSERT INTO scraper_sources (source_name, base_url,                   |
| extraction_instructions, active)                                      |
|                                                                       |
| VALUES (                                                              |
|                                                                       |
| \'British Heart Foundation --- Events\',                              |
|                                                                       |
| \'https://www.bhf.org.uk/what-we-do/our-research/events\',            |
|                                                                       |
| \'Find all upcoming conferences and events listed on this page. For   |
| each event, extract: the event name, the specialty or topic area, the |
| start and end dates, the venue name and city, any ticket prices       |
| broken down by professional level (e.g. Student, Consultant, Member,  |
| Non-Member), whether CPD points are awarded and how many, and whether |
| abstract or poster submissions are open. If individual event detail   |
| pages exist, navigate to each one to collect the full information.    |
| Return all data in a structured format.\',                            |
|                                                                       |
| TRUE                                                                  |
|                                                                       |
| );                                                                    |
|                                                                       |
| INSERT INTO scraper_sources (source_name, base_url,                   |
| extraction_instructions, active)                                      |
|                                                                       |
| VALUES (                                                              |
|                                                                       |
| \'Royal College of Surgeons --- Upcoming Events\',                    |
|                                                                       |
| \'https://www.rcs.ac.uk/education-and-training/events/\',             |
|                                                                       |
| \'Browse this page and find all upcoming surgical conferences,        |
| courses, and talks. For each one extract: the full event name, the    |
| surgical specialty, start and end dates, venue and location, all      |
| available pricing tiers with amounts in GBP, CPD or CME points if     |
| listed, and whether the event accepts abstract or poster submissions. |
| Follow links to individual event pages where needed to get complete   |
| details.\',                                                           |
|                                                                       |
| TRUE                                                                  |
|                                                                       |
| );                                                                    |
+-----------------------------------------------------------------------+

**5.3 database.py**

This module contains all functions that read from or write to Supabase.
The scraper and logger import from here --- no other file interacts with
the database directly.

+-----------------------------------------------------------------------+
| \# database.py                                                        |
|                                                                       |
| from supabase import create_client                                    |
|                                                                       |
| from config import SUPABASE_URL, SUPABASE_KEY                         |
|                                                                       |
| from datetime import datetime, date                                   |
|                                                                       |
| supabase = create_client(SUPABASE_URL, SUPABASE_KEY)                  |
|                                                                       |
| def get_active_sources():                                             |
|                                                                       |
| \"\"\"Fetch all active sources from the scraper registry.\"\"\"       |
|                                                                       |
| response =                                                            |
| supabase.table(\"scraper_sources\").select(\"\*\").eq(\"active\",     |
| True).execute()                                                       |
|                                                                       |
| return response.data                                                  |
|                                                                       |
| def update_source_status(source_id: int, status: str):                |
|                                                                       |
| \"\"\"Update a source\'s last_scraped_at and last_status after a      |
| run.\"\"\"                                                            |
|                                                                       |
| supabase.table(\"scraper_sources\").update({                          |
|                                                                       |
| \"last_scraped_at\": datetime.utcnow().isoformat(),                   |
|                                                                       |
| \"last_status\": status                                               |
|                                                                       |
| }).eq(\"id\", source_id).execute()                                    |
|                                                                       |
| def get_conference_by_source_url(source_url: str):                    |
|                                                                       |
| \"\"\"Check if a conference with this source URL already              |
| exists.\"\"\"                                                         |
|                                                                       |
| response =                                                            |
| supabase.table(\"conferences\").select(\"\*\").eq(\"source_url\",     |
| source_url).execute()                                                 |
|                                                                       |
| return response.data\[0\] if response.data else None                  |
|                                                                       |
| def insert_conference(data: dict) -\> int:                            |
|                                                                       |
| \"\"\"Insert a new conference record. Returns the new ID.\"\"\"       |
|                                                                       |
| response = supabase.table(\"conferences\").insert(data).execute()     |
|                                                                       |
| return response.data\[0\]\[\"id\"\]                                   |
|                                                                       |
| def update_conference(conference_id: int, data: dict):                |
|                                                                       |
| \"\"\"Update an existing conference record with changed fields.\"\"\" |
|                                                                       |
| data\[\"updated_at\"\] = datetime.utcnow().isoformat()                |
|                                                                       |
| supabase.table(\"conferences\").update(data).eq(\"id\",               |
| conference_id).execute()                                              |
|                                                                       |
| def insert_pricing_tiers(conference_id: int, tiers: list):            |
|                                                                       |
| \"\"\"Insert pricing tier rows for a conference.\"\"\"                |
|                                                                       |
| rows = \[{                                                            |
|                                                                       |
| \"conference_id\": conference_id,                                     |
|                                                                       |
| \"tier_label\": t\[\"tier_label\"\],                                  |
|                                                                       |
| \"price_gbp\": t\[\"price_gbp\"\],                                    |
|                                                                       |
| \"is_early_bird\": t.get(\"is_early_bird\", False),                   |
|                                                                       |
| \"early_bird_deadline\": t.get(\"early_bird_deadline\")               |
|                                                                       |
| } for t in tiers\]                                                    |
|                                                                       |
| if rows:                                                              |
|                                                                       |
| supabase.table(\"pricing_tiers\").insert(rows).execute()              |
|                                                                       |
| def delete_pricing_tiers(conference_id: int):                         |
|                                                                       |
| \"\"\"Remove all pricing tiers for a conference before re-inserting   |
| updated ones.\"\"\"                                                   |
|                                                                       |
| supabase.table(\"pricing_tiers\").delete().eq(\"conference_id\",      |
| conference_id).execute()                                              |
|                                                                       |
| def archive_expired_conferences():                                    |
|                                                                       |
| \"\"\"Mark conferences whose end_date has passed as archived.\"\"\"   |
|                                                                       |
| today = date.today().isoformat()                                      |
|                                                                       |
| supabase.table(\"conferences\").update({                              |
|                                                                       |
| \"archived\": True,                                                   |
|                                                                       |
| \"updated_at\": datetime.utcnow().isoformat()                         |
|                                                                       |
| }).lt(\"end_date\", today).eq(\"archived\", False).execute()          |
|                                                                       |
| def insert_scraper_log(log_data: dict):                               |
|                                                                       |
| \"\"\"Write a scraper run log entry.\"\"\"                            |
|                                                                       |
| supabase.table(\"scraper_logs\").insert(log_data).execute()           |
+-----------------------------------------------------------------------+

**6. Browser Automation Layer**

This module wraps Playwright and provides a clean interface for the LLM
agent to control the browser. It handles launching, navigating, reading
page content, and closing the browser. All interactions go through this
file.

+-----------------------------------------------------------------------+
| \# browser.py                                                         |
|                                                                       |
| from playwright.sync_api import sync_playwright                       |
|                                                                       |
| from config import SCRAPER_DELAY_SECS, SCRAPER_TIMEOUT_MS             |
|                                                                       |
| import time                                                           |
|                                                                       |
| class BrowserController:                                              |
|                                                                       |
| def \_\_init\_\_(self):                                               |
|                                                                       |
| self.playwright = None                                                |
|                                                                       |
| self.browser = None                                                   |
|                                                                       |
| self.page = None                                                      |
|                                                                       |
| def launch(self):                                                     |
|                                                                       |
| \"\"\"Launch a headless Chromium browser and open a blank page.\"\"\" |
|                                                                       |
| self.playwright = sync_playwright().start()                           |
|                                                                       |
| self.browser = self.playwright.chromium.launch(headless=True)         |
|                                                                       |
| self.page = self.browser.new_page()                                   |
|                                                                       |
| self.page.set_default_timeout(SCRAPER_TIMEOUT_MS)                     |
|                                                                       |
| def navigate(self, url: str) -\> str:                                 |
|                                                                       |
| \"\"\"Navigate to a URL and return the page text content.\"\"\"       |
|                                                                       |
| self.page.goto(url, wait_until=\"networkidle\")                       |
|                                                                       |
| time.sleep(SCRAPER_DELAY_SECS) \# Respectful delay                    |
|                                                                       |
| return self.get_page_text()                                           |
|                                                                       |
| def get_page_text(self) -\> str:                                      |
|                                                                       |
| \"\"\"Extract all visible text from the current page.\"\"\"           |
|                                                                       |
| return self.page.inner_text(\"body\")                                 |
|                                                                       |
| def get_page_links(self) -\> list:                                    |
|                                                                       |
| \"\"\"Extract all links (href + text) from the current page.\"\"\"    |
|                                                                       |
| links = self.page.evaluate(\"\"\"() =\> {                             |
|                                                                       |
| return Array.from(document.querySelectorAll(\'a\')).map(a =\> ({      |
|                                                                       |
| href: a.getAttribute(\'href\'),                                       |
|                                                                       |
| text: a.innerText.trim()                                              |
|                                                                       |
| })).filter(a =\> a.href && a.text);                                   |
|                                                                       |
| }\"\"\")                                                              |
|                                                                       |
| return links                                                          |
|                                                                       |
| def get_current_url(self) -\> str:                                    |
|                                                                       |
| \"\"\"Return the current page URL.\"\"\"                              |
|                                                                       |
| return self.page.url()                                                |
|                                                                       |
| def close(self):                                                      |
|                                                                       |
| \"\"\"Close the browser and clean up.\"\"\"                           |
|                                                                       |
| if self.page: self.page.close()                                       |
|                                                                       |
| if self.browser: self.browser.close()                                 |
|                                                                       |
| if self.playwright: self.playwright.stop()                            |
+-----------------------------------------------------------------------+

**7. LLM Orchestration Engine**

This is the core intelligence layer. It runs an iterative loop: at each
step it feeds the LLM the current page content, the original extraction
instructions, and a history of what has already been done. The LLM
returns a structured decision --- either navigate to a URL, extract data
from the current page, or declare the task complete. The loop repeats
until the task is done or the step limit is reached.

**7.1 LLM Decision Structure**

The LLM is instructed to respond only in valid JSON. Every response must
conform to this structure:

+-----------------------------------------------------------------------+
| {                                                                     |
|                                                                       |
| \"action\": \"navigate\" \| \"extract\" \| \"done\",                  |
|                                                                       |
| \"url\": \"\<url to navigate to --- only if action is navigate\>\",   |
|                                                                       |
| \"data\": \[ // only if action is extract                             |
|                                                                       |
| {                                                                     |
|                                                                       |
| \"conference_name\": \"\...\",                                        |
|                                                                       |
| \"specialty\": \"\...\",                                              |
|                                                                       |
| \"start_date\": \"YYYY-MM-DD\",                                       |
|                                                                       |
| \"end_date\": \"YYYY-MM-DD\",                                         |
|                                                                       |
| \"venue_name\": \"\...\",                                             |
|                                                                       |
| \"city\": \"\...\",                                                   |
|                                                                       |
| \"region\": \"\...\",                                                 |
|                                                                       |
| \"cpd_accredited\": true \| false,                                    |
|                                                                       |
| \"cpd_points\": \<integer or null\>,                                  |
|                                                                       |
| \"abstract_open\": true \| false,                                     |
|                                                                       |
| \"abstract_deadline\": \"YYYY-MM-DD or null\",                        |
|                                                                       |
| \"organiser_url\": \"\...\",                                          |
|                                                                       |
| \"description\": \"\...\",                                            |
|                                                                       |
| \"pricing_tiers\": \[                                                 |
|                                                                       |
| { \"tier_label\": \"Student\", \"price_gbp\": 50.00 },                |
|                                                                       |
| { \"tier_label\": \"Consultant\", \"price_gbp\": 250.00 }             |
|                                                                       |
| \]                                                                    |
|                                                                       |
| }                                                                     |
|                                                                       |
| \],                                                                   |
|                                                                       |
| \"reasoning\": \"\<brief explanation of why this action was           |
| chosen\>\"                                                            |
|                                                                       |
| }                                                                     |
+-----------------------------------------------------------------------+

**7.2 llm_agent.py**

+-----------------------------------------------------------------------+
| \# llm_agent.py                                                       |
|                                                                       |
| import json                                                           |
|                                                                       |
| import anthropic                                                      |
|                                                                       |
| from config import ANTHROPIC_API_KEY, SCRAPER_MAX_STEPS               |
|                                                                       |
| from browser import BrowserController                                 |
|                                                                       |
| class AgentLoop:                                                      |
|                                                                       |
| def \_\_init\_\_(self, source: dict):                                 |
|                                                                       |
| self.source = source                                                  |
|                                                                       |
| self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)          |
|                                                                       |
| self.browser = BrowserController()                                    |
|                                                                       |
| self.step_count = 0                                                   |
|                                                                       |
| self.extracted_data = \[\]                                            |
|                                                                       |
| self.history = \[\] \# Tracks actions taken so far                    |
|                                                                       |
| def run(self) -\> dict:                                               |
|                                                                       |
| \"\"\"                                                                |
|                                                                       |
| Main entry point. Launches browser, runs the reasoning loop,          |
|                                                                       |
| and returns all extracted conference data.                            |
|                                                                       |
| Returns: { \'data\': \[\...\], \'steps_taken\': int, \'error\': str   |
| or None }                                                             |
|                                                                       |
| \"\"\"                                                                |
|                                                                       |
| try:                                                                  |
|                                                                       |
| self.browser.launch()                                                 |
|                                                                       |
| \# Initial navigation to the source URL                               |
|                                                                       |
| page_text = self.browser.navigate(self.source\[\"base_url\"\])        |
|                                                                       |
| self.history.append(f\"Navigated to {self.source\[\'base_url\'\]}\")  |
|                                                                       |
| while self.step_count \< SCRAPER_MAX_STEPS:                           |
|                                                                       |
| self.step_count += 1                                                  |
|                                                                       |
| decision = self.\_get_llm_decision(page_text)                         |
|                                                                       |
| if decision\[\"action\"\] == \"done\":                                |
|                                                                       |
| break                                                                 |
|                                                                       |
| elif decision\[\"action\"\] == \"navigate\":                          |
|                                                                       |
| url = decision\[\"url\"\]                                             |
|                                                                       |
| \# Resolve relative URLs                                              |
|                                                                       |
| if url.startswith(\"/\"):                                             |
|                                                                       |
| from urllib.parse import urlparse                                     |
|                                                                       |
| base = urlparse(self.source\[\"base_url\"\])                          |
|                                                                       |
| url = f\"{base.scheme}://{base.netloc}{url}\"                         |
|                                                                       |
| page_text = self.browser.navigate(url)                                |
|                                                                       |
| self.history.append(f\"Navigated to {url}\")                          |
|                                                                       |
| elif decision\[\"action\"\] == \"extract\":                           |
|                                                                       |
| self.extracted_data.extend(decision.get(\"data\", \[\]))              |
|                                                                       |
| self.history.append(f\"Extracted {len(decision.get(\'data\', \[\]))}  |
| conference(s)\")                                                      |
|                                                                       |
| \# After extraction, signal done on next loop unless LLM says         |
| otherwise                                                             |
|                                                                       |
| return {                                                              |
|                                                                       |
| \"data\": self.extracted_data,                                        |
|                                                                       |
| \"steps_taken\": self.step_count,                                     |
|                                                                       |
| \"error\": None if self.extracted_data else \"No data extracted       |
| within step limit\"                                                   |
|                                                                       |
| }                                                                     |
|                                                                       |
| except Exception as e:                                                |
|                                                                       |
| return { \"data\": \[\], \"steps_taken\": self.step_count, \"error\": |
| str(e) }                                                              |
|                                                                       |
| finally:                                                              |
|                                                                       |
| self.browser.close()                                                  |
|                                                                       |
| def \_get_llm_decision(self, page_text: str) -\> dict:                |
|                                                                       |
| \"\"\"Send the current state to the LLM and parse its JSON            |
| response.\"\"\"                                                       |
|                                                                       |
| \# Truncate page text if very long to stay within token limits        |
|                                                                       |
| truncated_text = page_text\[:8000\]                                   |
|                                                                       |
| prompt = f\"\"\"You are a web scraping agent. Your task is to extract |
| medical conference data from websites.                                |
|                                                                       |
| ORIGINAL INSTRUCTIONS:                                                |
|                                                                       |
| {self.source\[\'extraction_instructions\'\]}                          |
|                                                                       |
| CURRENT PAGE URL: {self.browser.get_current_url()}                    |
|                                                                       |
| CURRENT PAGE CONTENT:                                                 |
|                                                                       |
| {truncated_text}                                                      |
|                                                                       |
| AVAILABLE LINKS ON PAGE:                                              |
|                                                                       |
| {json.dumps(self.browser.get_page_links()\[:50\], indent=2)}          |
|                                                                       |
| ACTIONS TAKEN SO FAR:                                                 |
|                                                                       |
| {chr(10).join(self.history)}                                          |
|                                                                       |
| CONFERENCES EXTRACTED SO FAR: {len(self.extracted_data)}              |
|                                                                       |
| INSTRUCTIONS:                                                         |
|                                                                       |
| Based on the page content and your extraction instructions, decide    |
| your next action.                                                     |
|                                                                       |
| \- If you can see conference data on this page, use action            |
| \'extract\' and return all conferences found.                         |
|                                                                       |
| \- If you need to navigate to a detail page or a different section to |
| find conferences, use action \'navigate\' and provide the full URL.   |
|                                                                       |
| \- If you have extracted all available conferences and there is       |
| nothing more to find, use action \'done\'.                            |
|                                                                       |
| CRITICAL: Respond ONLY with valid JSON. No text before or after. Use  |
| this exact structure:                                                 |
|                                                                       |
| {{                                                                    |
|                                                                       |
| \"action\": \"navigate\" \| \"extract\" \| \"done\",                  |
|                                                                       |
| \"url\": \"\<only if navigating\>\",                                  |
|                                                                       |
| \"data\": \[\<only if extracting --- array of conference objects\>\], |
|                                                                       |
| \"reasoning\": \"\<brief explanation\>\"                              |
|                                                                       |
| }}                                                                    |
|                                                                       |
| Conference object structure:                                          |
|                                                                       |
| {{                                                                    |
|                                                                       |
| \"conference_name\": string,                                          |
|                                                                       |
| \"specialty\": string,                                                |
|                                                                       |
| \"start_date\": \"YYYY-MM-DD\",                                       |
|                                                                       |
| \"end_date\": \"YYYY-MM-DD\",                                         |
|                                                                       |
| \"venue_name\": string,                                               |
|                                                                       |
| \"city\": string,                                                     |
|                                                                       |
| \"region\": string,                                                   |
|                                                                       |
| \"cpd_accredited\": boolean,                                          |
|                                                                       |
| \"cpd_points\": integer or null,                                      |
|                                                                       |
| \"abstract_open\": boolean,                                           |
|                                                                       |
| \"abstract_deadline\": \"YYYY-MM-DD\" or null,                        |
|                                                                       |
| \"organiser_url\": string (the direct URL to this conference on the   |
| organiser site),                                                      |
|                                                                       |
| \"description\": string,                                              |
|                                                                       |
| \"pricing_tiers\": \[{{ \"tier_label\": string, \"price_gbp\": number |
| }}\]                                                                  |
|                                                                       |
| }}\"\"\"                                                              |
|                                                                       |
| response = self.client.messages.create(                               |
|                                                                       |
| model=\"claude-sonnet-4-20250514\",                                   |
|                                                                       |
| max_tokens=4096,                                                      |
|                                                                       |
| messages=\[{ \"role\": \"user\", \"content\": prompt }\]              |
|                                                                       |
| )                                                                     |
|                                                                       |
| raw = response.content\[0\].text.strip()                              |
|                                                                       |
| \# Strip markdown code fences if present                              |
|                                                                       |
| if raw.startswith(\"\`\`\`\"):                                        |
|                                                                       |
| raw = raw.split(\"\`\`\`\")\[1\]                                      |
|                                                                       |
| if raw.startswith(\"json\"): raw = raw\[4:\]                          |
|                                                                       |
| return json.loads(raw)                                                |
+-----------------------------------------------------------------------+

**8. Data Validation**

Before any extracted data hits the database, it passes through the
validator. This checks for completeness, formats dates correctly, and
flags or discards records that are missing critical fields. It does not
silently insert bad data.

+-----------------------------------------------------------------------+
| \# validator.py                                                       |
|                                                                       |
| from datetime import datetime                                         |
|                                                                       |
| REQUIRED_FIELDS = \[\"conference_name\", \"source_url\"\]             |
|                                                                       |
| def validate_conference(data: dict) -\> dict:                         |
|                                                                       |
| \"\"\"                                                                |
|                                                                       |
| Validates a single conference record.                                 |
|                                                                       |
| Returns: { \'valid\': bool, \'data\': cleaned_data, \'warnings\':     |
| \[str\] }                                                             |
|                                                                       |
| \"\"\"                                                                |
|                                                                       |
| warnings = \[\]                                                       |
|                                                                       |
| cleaned = data.copy()                                                 |
|                                                                       |
| \# Check required fields                                              |
|                                                                       |
| for field in REQUIRED_FIELDS:                                         |
|                                                                       |
| if not cleaned.get(field):                                            |
|                                                                       |
| return { \"valid\": False, \"data\": None, \"warnings\": \[f\"Missing |
| required field: {field}\"\] }                                         |
|                                                                       |
| \# Validate and parse dates                                           |
|                                                                       |
| for date_field in \[\"start_date\", \"end_date\",                     |
| \"abstract_deadline\"\]:                                              |
|                                                                       |
| val = cleaned.get(date_field)                                         |
|                                                                       |
| if val:                                                               |
|                                                                       |
| try:                                                                  |
|                                                                       |
| datetime.strptime(val, \"%Y-%m-%d\")                                  |
|                                                                       |
| except (ValueError, TypeError):                                       |
|                                                                       |
| warnings.append(f\"Invalid date format for {date_field}: \'{val}\'    |
| --- set to null\")                                                    |
|                                                                       |
| cleaned\[date_field\] = None                                          |
|                                                                       |
| \# Validate pricing tiers                                             |
|                                                                       |
| tiers = cleaned.get(\"pricing_tiers\", \[\])                          |
|                                                                       |
| valid_tiers = \[\]                                                    |
|                                                                       |
| for t in tiers:                                                       |
|                                                                       |
| if t.get(\"tier_label\") and t.get(\"price_gbp\") is not None:        |
|                                                                       |
| try:                                                                  |
|                                                                       |
| t\[\"price_gbp\"\] = float(t\[\"price_gbp\"\])                        |
|                                                                       |
| valid_tiers.append(t)                                                 |
|                                                                       |
| except (ValueError, TypeError):                                       |
|                                                                       |
| warnings.append(f\"Invalid price for tier \'{t.get(\'tier_label\')}\' |
| --- skipped\")                                                        |
|                                                                       |
| else:                                                                 |
|                                                                       |
| warnings.append(f\"Incomplete pricing tier --- skipped: {t}\")        |
|                                                                       |
| cleaned\[\"pricing_tiers\"\] = valid_tiers                            |
|                                                                       |
| \# Ensure booleans are correct type                                   |
|                                                                       |
| for bool_field in \[\"cpd_accredited\", \"abstract_open\"\]:          |
|                                                                       |
| cleaned\[bool_field\] = bool(cleaned.get(bool_field, False))          |
|                                                                       |
| \# Warn if key optional fields are missing                            |
|                                                                       |
| for field in \[\"start_date\", \"city\", \"specialty\"\]:             |
|                                                                       |
| if not cleaned.get(field):                                            |
|                                                                       |
| warnings.append(f\"Missing optional field: {field}\")                 |
|                                                                       |
| return { \"valid\": True, \"data\": cleaned, \"warnings\": warnings } |
+-----------------------------------------------------------------------+

**9. Main Scraper Function**

This module ties everything together. For a given source, it runs the
LLM agent, validates the output, then handles the insert-or-update logic
against the database. It returns a summary of what happened for logging
purposes.

+-----------------------------------------------------------------------+
| \# scraper.py                                                         |
|                                                                       |
| from llm_agent import AgentLoop                                       |
|                                                                       |
| from validator import validate_conference                             |
|                                                                       |
| from database import (                                                |
|                                                                       |
| get_conference_by_source_url,                                         |
|                                                                       |
| insert_conference,                                                    |
|                                                                       |
| update_conference,                                                    |
|                                                                       |
| insert_pricing_tiers,                                                 |
|                                                                       |
| delete_pricing_tiers                                                  |
|                                                                       |
| )                                                                     |
|                                                                       |
| from datetime import datetime                                         |
|                                                                       |
| def scrape_source(source: dict) -\> dict:                             |
|                                                                       |
| \"\"\"                                                                |
|                                                                       |
| Runs the full scrape pipeline for a single source.                    |
|                                                                       |
| Returns a summary dict for logging.                                   |
|                                                                       |
| \"\"\"                                                                |
|                                                                       |
| summary = {                                                           |
|                                                                       |
| \"source_id\": source\[\"id\"\],                                      |
|                                                                       |
| \"run_started_at\": datetime.utcnow().isoformat(),                    |
|                                                                       |
| \"run_ended_at\": None,                                               |
|                                                                       |
| \"status\": \"pending\",                                              |
|                                                                       |
| \"conferences_found\": 0,                                             |
|                                                                       |
| \"conferences_inserted\": 0,                                          |
|                                                                       |
| \"conferences_updated\": 0,                                           |
|                                                                       |
| \"errors_encountered\": 0,                                            |
|                                                                       |
| \"error_details\": None                                               |
|                                                                       |
| }                                                                     |
|                                                                       |
| try:                                                                  |
|                                                                       |
| \# Step 1: Run the LLM agent                                          |
|                                                                       |
| agent = AgentLoop(source)                                             |
|                                                                       |
| result = agent.run()                                                  |
|                                                                       |
| if result\[\"error\"\] and not result\[\"data\"\]:                    |
|                                                                       |
| summary\[\"status\"\] = \"failed\"                                    |
|                                                                       |
| summary\[\"error_details\"\] = result\[\"error\"\]                    |
|                                                                       |
| summary\[\"run_ended_at\"\] = datetime.utcnow().isoformat()           |
|                                                                       |
| return summary                                                        |
|                                                                       |
| raw_conferences = result\[\"data\"\]                                  |
|                                                                       |
| summary\[\"conferences_found\"\] = len(raw_conferences)               |
|                                                                       |
| \# Step 2: Validate and process each conference                       |
|                                                                       |
| for conf in raw_conferences:                                          |
|                                                                       |
| \# Attach the source URL as the unique key for duplicate detection    |
|                                                                       |
| conf\[\"source_url\"\] = conf.get(\"organiser_url\",                  |
| source\[\"base_url\"\])                                               |
|                                                                       |
| validation = validate_conference(conf)                                |
|                                                                       |
| if not validation\[\"valid\"\]:                                       |
|                                                                       |
| summary\[\"errors_encountered\"\] += 1                                |
|                                                                       |
| continue                                                              |
|                                                                       |
| cleaned = validation\[\"data\"\]                                      |
|                                                                       |
| tiers = cleaned.pop(\"pricing_tiers\", \[\])                          |
|                                                                       |
| \# Step 3: Insert or update                                           |
|                                                                       |
| existing = get_conference_by_source_url(cleaned\[\"source_url\"\])    |
|                                                                       |
| if existing:                                                          |
|                                                                       |
| \# Compare and update only if something changed                       |
|                                                                       |
| changes = {k: v for k, v in cleaned.items() if existing.get(k) != v}  |
|                                                                       |
| if changes:                                                           |
|                                                                       |
| update_conference(existing\[\"id\"\], changes)                        |
|                                                                       |
| \# Re-insert pricing tiers if they exist                              |
|                                                                       |
| if tiers:                                                             |
|                                                                       |
| delete_pricing_tiers(existing\[\"id\"\])                              |
|                                                                       |
| insert_pricing_tiers(existing\[\"id\"\], tiers)                       |
|                                                                       |
| summary\[\"conferences_updated\"\] += 1                               |
|                                                                       |
| else:                                                                 |
|                                                                       |
| new_id = insert_conference(cleaned)                                   |
|                                                                       |
| if tiers:                                                             |
|                                                                       |
| insert_pricing_tiers(new_id, tiers)                                   |
|                                                                       |
| summary\[\"conferences_inserted\"\] += 1                              |
|                                                                       |
| \# Determine overall status                                           |
|                                                                       |
| if summary\[\"conferences_inserted\"\] +                              |
| summary\[\"conferences_updated\"\] \> 0:                              |
|                                                                       |
| summary\[\"status\"\] = \"success\" if                                |
| summary\[\"errors_encountered\"\] == 0 else \"partial\"               |
|                                                                       |
| else:                                                                 |
|                                                                       |
| summary\[\"status\"\] = \"failed\" if                                 |
| summary\[\"errors_encountered\"\] \> 0 else \"partial\"               |
|                                                                       |
| except Exception as e:                                                |
|                                                                       |
| summary\[\"status\"\] = \"failed\"                                    |
|                                                                       |
| summary\[\"error_details\"\] = str(e)                                 |
|                                                                       |
| summary\[\"errors_encountered\"\] += 1                                |
|                                                                       |
| summary\[\"run_ended_at\"\] = datetime.utcnow().isoformat()           |
|                                                                       |
| return summary                                                        |
+-----------------------------------------------------------------------+

**10. Logging**

The logger writes run summaries to both the console and the scraper_logs
table in Supabase. Every scrape run --- successful or not --- produces a
log entry. This is how you monitor the health of the pipeline.

+-----------------------------------------------------------------------+
| \# logger.py                                                          |
|                                                                       |
| import logging                                                        |
|                                                                       |
| from database import insert_scraper_log, update_source_status         |
|                                                                       |
| logging.basicConfig(                                                  |
|                                                                       |
| level=logging.INFO,                                                   |
|                                                                       |
| format=\"%(asctime)s \[%(levelname)s\] %(message)s\",                 |
|                                                                       |
| datefmt=\"%Y-%m-%d %H:%M:%S\"                                         |
|                                                                       |
| )                                                                     |
|                                                                       |
| logger = logging.getLogger(\"medconf-scraper\")                       |
|                                                                       |
| def log_scrape_run(summary: dict):                                    |
|                                                                       |
| \"\"\"Log a completed scrape run to console and Supabase.\"\"\"       |
|                                                                       |
| source_id = summary\[\"source_id\"\]                                  |
|                                                                       |
| status = summary\[\"status\"\]                                        |
|                                                                       |
| \# Console output                                                     |
|                                                                       |
| logger.info(f\"Source {source_id} \| Status: {status} \| Found:       |
| {summary\[\'conferences_found\'\]} \| Inserted:                       |
| {summary\[\'conferences_inserted\'\]} \| Updated:                     |
| {summary\[\'conferences_updated\'\]} \| Errors:                       |
| {summary\[\'errors_encountered\'\]}\")                                |
|                                                                       |
| if summary\[\"error_details\"\]:                                      |
|                                                                       |
| logger.warning(f\"Source {source_id} \| Error:                        |
| {summary\[\'error_details\'\]}\")                                     |
|                                                                       |
| \# Write to Supabase                                                  |
|                                                                       |
| insert_scraper_log(summary)                                           |
|                                                                       |
| \# Update the source\'s last_scraped_at and last_status               |
|                                                                       |
| update_source_status(source_id, status)                               |
+-----------------------------------------------------------------------+

**11. Scheduler**

The scheduler defines when the scraper runs. It uses APScheduler to
trigger a weekly job that fetches all active sources, runs the scraper
on each one, and logs the results. Each source runs independently --- a
failure on one does not affect the others.

+-----------------------------------------------------------------------+
| \# scheduler.py                                                       |
|                                                                       |
| from apscheduler.schedulers.blocking import BlockingScheduler         |
|                                                                       |
| from database import get_active_sources, archive_expired_conferences  |
|                                                                       |
| from scraper import scrape_source                                     |
|                                                                       |
| from logger import log_scrape_run, logger                             |
|                                                                       |
| def run_all_sources():                                                |
|                                                                       |
| \"\"\"Fetch all active sources and scrape each one.\"\"\"             |
|                                                                       |
| logger.info(\"=== Scraper run started ===\")                          |
|                                                                       |
| sources = get_active_sources()                                        |
|                                                                       |
| logger.info(f\"Found {len(sources)} active source(s)\")               |
|                                                                       |
| for source in sources:                                                |
|                                                                       |
| logger.info(f\"Starting scrape for source {source\[\'id\'\]}:         |
| {source\[\'source_name\'\]}\")                                        |
|                                                                       |
| summary = scrape_source(source)                                       |
|                                                                       |
| log_scrape_run(summary)                                               |
|                                                                       |
| \# Archive any conferences that have expired                          |
|                                                                       |
| archive_expired_conferences()                                         |
|                                                                       |
| logger.info(\"Archived expired conferences\")                         |
|                                                                       |
| logger.info(\"=== Scraper run complete ===\")                         |
|                                                                       |
| def start_scheduler():                                                |
|                                                                       |
| \"\"\"Start the APScheduler with a weekly cron job.\"\"\"             |
|                                                                       |
| scheduler = BlockingScheduler()                                       |
|                                                                       |
| \# Runs every Sunday at 02:00 AM                                      |
|                                                                       |
| scheduler.add_job(run_all_sources, \"cron\", day_of_week=\"sun\",     |
| hour=2, minute=0)                                                     |
|                                                                       |
| logger.info(\"Scheduler started. Next scrape run: Sunday at 02:00\")  |
|                                                                       |
| scheduler.start()                                                     |
+-----------------------------------------------------------------------+

**12. Entry Point**

main.py is the file you run to start the scraper. It can either trigger
an immediate scrape run (useful for testing) or start the scheduler for
regular automated runs.

+-----------------------------------------------------------------------+
| \# main.py                                                            |
|                                                                       |
| import sys                                                            |
|                                                                       |
| from scheduler import start_scheduler, run_all_sources                |
|                                                                       |
| from logger import logger                                             |
|                                                                       |
| if \_\_name\_\_ == \"\_\_main\_\_\":                                  |
|                                                                       |
| if len(sys.argv) \> 1 and sys.argv\[1\] == \"\--run-now\":            |
|                                                                       |
| \# Immediate run --- useful for testing                               |
|                                                                       |
| logger.info(\"Running scraper immediately (manual trigger)\")         |
|                                                                       |
| run_all_sources()                                                     |
|                                                                       |
| else:                                                                 |
|                                                                       |
| \# Start the weekly scheduler                                         |
|                                                                       |
| start_scheduler()                                                     |
+-----------------------------------------------------------------------+

To test the scraper manually, run:

  -----------------------------------------------------------------------
  python main.py \--run-now

  -----------------------------------------------------------------------

To start the automated weekly schedule, run:

  -----------------------------------------------------------------------
  python main.py

  -----------------------------------------------------------------------

**13. Requirements File**

Create this file in the project root for deployment purposes. It pins
the exact dependencies the scraper needs.

+-----------------------------------------------------------------------+
| \# requirements.txt                                                   |
|                                                                       |
| playwright\>=1.40.0                                                   |
|                                                                       |
| anthropic\>=0.20.0                                                    |
|                                                                       |
| supabase\>=2.0.0                                                      |
|                                                                       |
| APScheduler\>=3.10.0                                                  |
|                                                                       |
| python-dotenv\>=1.0.0                                                 |
+-----------------------------------------------------------------------+

**14. Testing & Verification Checklist**

Run through the following steps after building the scraper to verify
everything is working before deploying to a production schedule.

1.  **Environment check.** Run python -c \"from config import \*;
    print(\'OK\')\" --- if it prints OK, your .env file is loading
    correctly.

2.  **Database connection.** Run python -c \"from database import
    get_active_sources; print(get_active_sources())\" --- you should see
    your seeded source rows returned as a list.

3.  **Browser launch test.** Run python -c \"from browser import
    BrowserController; b = BrowserController(); b.launch();
    print(\'Browser OK\'); b.close()\" --- confirm no errors.

4.  **Single source scrape.** Run python main.py \--run-now --- watch
    the console output. You should see it connect to each active source,
    navigate, extract, and log results.

5.  **Database verification.** After a run, log into Supabase and check
    the conferences table for new rows, the pricing_tiers table for
    associated prices, and the scraper_logs table for the run summary.

6.  **Duplicate handling.** Run the scraper a second time immediately.
    The conferences_inserted count should be 0 and conferences_updated
    should reflect any changes (or also 0 if nothing changed). No
    duplicate rows should appear.

7.  **Error handling.** Temporarily set one source\'s base_url to an
    invalid URL in Supabase. Run the scraper. Confirm that source fails
    and logs an error, but the other sources still run successfully.

**15. Deployment Notes**

For the MVP, the scraper can run on any environment that supports Python
and outbound HTTP. Here are the recommended options in order of
simplicity:

-   **Railway.** The simplest option. Push your repository to Railway,
    set your environment variables in the Railway dashboard, and it runs
    the Python process continuously. The APScheduler handles the weekly
    timing internally. No additional configuration needed.

-   **Render.** Similar to Railway. Create a Background Worker service,
    point it at your repository, set environment variables, and deploy.
    Render will keep the process running.

-   **AWS Lambda + EventBridge (alternative).** If you prefer
    serverless, you can restructure the scraper to run as a Lambda
    function triggered by an EventBridge schedule. This requires
    removing APScheduler and adjusting the entry point, but reduces cost
    at low usage. Note: Lambda has execution time limits (up to 15
    minutes) which should be sufficient for most scrape runs but worth
    monitoring.

+-----------------------------------------------------------------------+
| **Environment variables**                                             |
|                                                                       |
| Whichever platform you deploy to, set ANTHROPIC_API_KEY,              |
| SUPABASE_URL, and SUPABASE_KEY as environment variables in the        |
| platform\'s dashboard. Never include them in your code or commit them |
| to version control.                                                   |
+-----------------------------------------------------------------------+
