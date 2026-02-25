"""
product_db.py — Store-Sense Price-Tracking Database
====================================================
Async Firestore integration for logging products and querying price
history across stores.

Schema
------
  products/{product_id}
      name          : str       — normalised product name
      display_name  : str       — original product name from Gemini
      category      : str       — "dairy", "snacks", "produce", …
      nutrition_score : str     — Gemini's health grade ("A", "B+", …)
      created_at    : timestamp
      updated_at    : timestamp

  products/{product_id}/sightings/{auto}
      store         : str       — store name ("Walmart", "Kroger", …)
      price         : float     — shelf price
      unit_price    : float     — price per unit (oz, lb, count)
      unit          : str       — unit label ("oz", "lb", "count")
      date          : timestamp
      on_sale       : bool
"""

import asyncio
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional

from google.cloud.firestore import AsyncClient
from google.cloud import firestore

# ─────────────────────────────────────────────
# Module-level client (lazy-initialised)
# ─────────────────────────────────────────────

_db: Optional[AsyncClient] = None


def _get_db() -> AsyncClient:
    """Return (and lazily create) the async Firestore client."""
    global _db
    if _db is None:
        _db = AsyncClient()
    return _db


# ─────────────────────────────────────────────
# Name normalisation
# ─────────────────────────────────────────────

def _normalize_name(name: str) -> str:
    """
    Lowercase, strip packaging sizes and extra whitespace so that
    'Chobani Greek Yogurt 32oz' and 'chobani greek yogurt' match.
    """
    n = name.lower().strip()
    # Strip common size patterns: "32oz", "16 oz", "1.5L", "500ml", "42-count", etc.
    n = re.sub(r"\b\d+[\-\.]?\d*\s*(?:oz|fl\.?\s*oz|ml|l|lb|lbs|kg|g|ct|count|pk|pack)\b", "", n)
    n = re.sub(r"\b\d+\-?(?:pack|count)\b", "", n)
    n = re.sub(r"[^\w\s]", "", n)      # drop punctuation
    n = re.sub(r"\s+", " ", n).strip() # collapse whitespace
    return n


def _product_id(name: str) -> str:
    """Deterministic document ID from normalised name."""
    norm = _normalize_name(name)
    return hashlib.md5(norm.encode()).hexdigest()[:16]


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

async def log_product(
    name: str,
    price: float,
    unit_price: float,
    unit: str,
    store: str,
    category: str = "",
    nutrition_score: str = "",
    on_sale: bool = False,
) -> dict:
    """
    Upsert a product document and append a price sighting.
    Returns a summary dict suitable for returning to the Gemini model.
    """
    db = _get_db()
    pid = _product_id(name)
    prod_ref = db.collection("products").document(pid)
    now = datetime.now(timezone.utc)

    # Upsert product metadata
    await prod_ref.set(
        {
            "name": _normalize_name(name),
            "display_name": name,
            "category": category,
            "nutrition_score": nutrition_score,
            "updated_at": now,
        },
        merge=True,
    )

    # If this is the first write, set created_at
    snap = await prod_ref.get()
    if snap.exists and "created_at" not in (snap.to_dict() or {}):
        await prod_ref.update({"created_at": now})

    # Add sighting
    sighting_data = {
        "store": store,
        "price": price,
        "unit_price": unit_price,
        "unit": unit,
        "date": now,
        "on_sale": on_sale,
    }
    await prod_ref.collection("sightings").add(sighting_data)

    print(f"[product_db] Logged: {name} @ ${price} ({store})")
    return {
        "status": "saved",
        "product_id": pid,
        "product": name,
        "price": price,
        "unit_price": unit_price,
        "unit": unit,
        "store": store,
        "on_sale": on_sale,
        "message": f"Logged {name} at ${price:.2f} in {store}.",
    }


async def query_price_history(product_name: str) -> dict:
    """
    Look up all sightings for a product across stores.
    Returns them sorted by unit_price (cheapest first).
    """
    db = _get_db()
    pid = _product_id(product_name)
    prod_ref = db.collection("products").document(pid)
    snap = await prod_ref.get()

    if not snap.exists:
        return {
            "found": False,
            "product": product_name,
            "message": f"No price history found for '{product_name}'.",
            "sightings": [],
        }

    # Fetch all sightings
    sightings_ref = prod_ref.collection("sightings")
    docs = sightings_ref.order_by("unit_price", direction=firestore.Query.ASCENDING)
    results = []
    async for doc in docs.stream():
        d = doc.to_dict()
        results.append({
            "store": d.get("store", ""),
            "price": d.get("price", 0),
            "unit_price": d.get("unit_price", 0),
            "unit": d.get("unit", ""),
            "date": d.get("date", "").isoformat() if hasattr(d.get("date", ""), "isoformat") else str(d.get("date", "")),
            "on_sale": d.get("on_sale", False),
        })

    product_data = snap.to_dict() or {}
    cheapest = results[0] if results else None

    return {
        "found": True,
        "product": product_data.get("display_name", product_name),
        "category": product_data.get("category", ""),
        "nutrition_score": product_data.get("nutrition_score", ""),
        "total_sightings": len(results),
        "cheapest": cheapest,
        "all_sightings": results[:10],  # cap at 10 to keep response size reasonable
        "message": (
            f"Found {len(results)} sighting(s) for '{product_name}'. "
            + (f"Cheapest: ${cheapest['price']:.2f} at {cheapest['store']}." if cheapest else "")
        ),
    }


async def get_cheapest_sighting(product_name: str) -> dict:
    """Convenience wrapper — returns just the single cheapest sighting."""
    history = await query_price_history(product_name)
    if history["found"] and history["cheapest"]:
        return {
            "found": True,
            "product": history["product"],
            **history["cheapest"],
        }
    return {
        "found": False,
        "product": product_name,
        "message": f"No price history for '{product_name}'.",
    }
