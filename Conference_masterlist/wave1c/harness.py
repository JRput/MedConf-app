"""No-DB test harness for a new extractor (wave 1b).

Usage (from medconf-scraper/, with the venv):
  PYTHONPATH=. ./.venv/bin/python ../Conference_masterlist/wave1b/harness.py <module> <ClassName> <build.json> [--details N] [--force-fallback]

Reads `source_row` from the build JSON, runs Phase A (list shells — extractor
override, else the generic paginated DOM walker) and Phase B (detail
extraction) on N shells spread across the listing. Never writes to
Supabase. --force-fallback makes http_fetch's httpx path report 403 so the
Playwright path (what GitHub runners often need) is exercised.
"""
import sys, json, importlib, argparse, logging
logging.basicConfig(level=logging.WARNING)

ap = argparse.ArgumentParser()
ap.add_argument("module"); ap.add_argument("cls"); ap.add_argument("build_json")
ap.add_argument("--details", type=int, default=5); ap.add_argument("--force-fallback", action="store_true")
a = ap.parse_args()

if a.force_fallback:
    from extractors import http_fetch
    http_fetch._fetch_httpx = lambda url, headers, timeout: (403, "")

from openai import OpenAI
from config import KIMI_API_KEY, KIMI_BASE_URL
from llm_client import chat_completion
from browser import BrowserController

source = dict(json.load(open(a.build_json))["source_row"]); source.setdefault("id", 0)
Ext = getattr(importlib.import_module(f"extractors.{a.module}"), a.cls)
ext = Ext(source)
client = OpenAI(api_key=KIMI_API_KEY, base_url=KIMI_BASE_URL, max_retries=5, timeout=90.0)

def llm_call(prompt):
    try:
        r = chat_completion(client, chain="text", max_tokens=512, temperature=0.3,
                            messages=[{"role": "user", "content": prompt}],
                            extra_body={"chat_template_kwargs": {"thinking": False}})
        return r.choices[0].message.content or ""
    except Exception as e:
        print("  LLM call failed:", e); return None

b = BrowserController(); b.launch()
try:
    ext.browser = b
    shells = ext.list_shells_override()
    via = "override"
    if shells is None:
        shells = b.get_event_cards_paginated(source); via = "generic DOM walker"
    print(f"PHASE A via {via}: {len(shells)} shells; dated={sum(1 for s in shells if s.get('start_date'))}")
    for s in shells[:5]: print("   ", (s.get("title") or "")[:60], "|", s.get("start_date"), "|", s.get("booking_url"))
    if shells:
        step = max(1, len(shells) // a.details)
        for s in shells[::step][: a.details]:
            b.navigate(s["booking_url"])
            d = ext.extract_detail(page=b.page, shell=s, llm_call=llm_call) or {}
            merged = {**s, **{k: v for k, v in d.items() if v not in (None, "", [])}}
            tiers = merged.get("pricing_tiers") or []
            print("\nDETAIL", merged.get("booking_url"))
            for k in ("title", "start_date", "end_date", "start_time", "event_type", "specialty", "venue_name", "city", "region",
                      "event_format", "cpd_points", "cpd_accredited", "abstract_open", "abstract_deadline", "is_sold_out"):
                print(f"   {k:18} {merged.get(k)!r}")
            print(f"   description        {(merged.get('description') or '')[:200]!r}")
            print(f"   pricing_tiers      {len(tiers)}"); [print("      ", t) for t in tiers[:6]]
            ss = merged.get("course_sessions") or merged.get("sessions") or []
            if ss: print(f"   sessions           {len(ss)}"); [print("      ", x) for x in ss[:3]]
finally:
    b.close()
