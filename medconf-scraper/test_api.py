#!/usr/bin/env python3
"""Quick test script to check Kimi K2.5 API response format with thinking disabled."""

from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("KIMI_API_KEY"),
    base_url=os.getenv("KIMI_BASE_URL")
)

# Test with thinking DISABLED
print("=== Testing with thinking DISABLED ===")
response = client.chat.completions.create(
    model=os.getenv("KIMI_MODEL"),
    max_tokens=500,
    messages=[{"role": "user", "content": 'Respond with only this JSON: {"message": "hello", "status": "ok"}'}],
    extra_body={"chat_template_kwargs": {"thinking": False}}
)

msg = response.choices[0].message
print(f"content: {repr(msg.content)}")
print(f"model_extra: {msg.model_extra if hasattr(msg, 'model_extra') else 'N/A'}")

# Test with thinking ENABLED (default)
print("\n=== Testing with thinking ENABLED ===")
response2 = client.chat.completions.create(
    model=os.getenv("KIMI_MODEL"),
    max_tokens=500,
    messages=[{"role": "user", "content": 'Respond with only this JSON: {"message": "hello", "status": "ok"}'}],
    extra_body={"chat_template_kwargs": {"thinking": True}}
)

msg2 = response2.choices[0].message
print(f"content: {repr(msg2.content)}")
print(f"model_extra keys: {list(msg2.model_extra.keys()) if hasattr(msg2, 'model_extra') and msg2.model_extra else 'N/A'}")
if hasattr(msg2, 'model_extra') and msg2.model_extra:
    for key, val in msg2.model_extra.items():
        print(f"  {key}: {repr(val[:200] if isinstance(val, str) and len(val) > 200 else val)}")
