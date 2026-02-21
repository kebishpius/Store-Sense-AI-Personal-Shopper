# -*- coding: utf-8 -*-
"""
auth_check.py — Store-Sense connection verification
Initializes genai.Client with Vertex AI and verifies the API is reachable
by fetching model metadata for a known Gemini model.
"""

import sys
from google import genai

# ─────────────────────────────────────────────
# Project configuration  (must match gcloud project)
# ─────────────────────────────────────────────
PROJECT_ID = "hackathons-461900"
LOCATION   = "us-central1"
# Use the verified working model for Live API in this project
MODEL_ID   = "gemini-2.0-flash-lite-001"

# ─────────────────────────────────────────────
# Initialize the Vertex AI–backed genai client
# ─────────────────────────────────────────────
print("[auth_check] Initializing genai.Client with Vertex AI …")
client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location=LOCATION,
)
print(f"[auth_check] Client initialized  | project={PROJECT_ID} | location={LOCATION}")

# ─────────────────────────────────────────────
# Smoke-test: fetch model metadata
# ─────────────────────────────────────────────
print(f"[auth_check] Calling models.get('{MODEL_ID}') …")
try:
    model = client.models.get(model=MODEL_ID)
    print("[auth_check] OK  Connection successful!")
    print(f"             Model name        : {model.name}")
    print(f"             Display name      : {getattr(model, 'display_name', 'N/A')}")
    print(f"             Supported actions : {getattr(model, 'supported_actions', 'N/A')}")
except Exception as exc:
    print(f"[auth_check] FAILED  Connection error: {exc}", file=sys.stderr)
    sys.exit(1)
