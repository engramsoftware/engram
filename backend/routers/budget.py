"""
Budget tracking router.

Handles expense CRUD, receipt parsing, and spending summaries.
Expenses are stored in MongoDB with category, amount, date, and optional receipt image.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List
from bson import ObjectId

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field

from database import get_database
from routers.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Models ────────────────────────────────────────────────────

class ExpenseCreate(BaseModel):
    """Create a new expense entry. Category is freeform — the LLM auto-categorizes."""
    amount: float = Field(..., gt=0, description="Expense amount")
    category: str = Field(default="uncategorized", description="Freeform category (LLM assigns)")
    description: str = Field(default="", description="What was purchased")
    date: Optional[str] = Field(default=None, description="Date (ISO format, defaults to now)")
    store: Optional[str] = Field(default=None, description="Store or vendor name")


class ExpenseResponse(BaseModel):
    """Expense entry response."""
    id: str
    amount: float
    category: str
    description: str
    date: str
    store: Optional[str]
    created_at: str


class BudgetGoal(BaseModel):
    """Monthly budget goal."""
    category: str = Field(default="total", description="Category or 'total'")
    amount: float = Field(..., gt=0, description="Budget limit")


# ── Routes ────────────────────────────────────────────────────

@router.post("", response_model=ExpenseResponse)
async def add_expense(
    data: ExpenseCreate,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Add a new expense entry."""
    db = get_database()
    user_id = current_user["id"]
    now = datetime.utcnow()

    expense_date = data.date or now.isoformat()

    doc = {
        "userId": user_id,
        "amount": data.amount,
        "category": data.category.lower(),
        "description": data.description,
        "date": expense_date,
        "store": data.store,
        "createdAt": now.isoformat(),
    }
    result = await db.expenses.insert_one(doc)

    logger.info(f"Expense added: ${data.amount:.2f} ({data.category}) for user {user_id}")

    return ExpenseResponse(
        id=str(result.inserted_id),
        amount=data.amount,
        category=data.category.lower(),
        description=data.description,
        date=expense_date,
        store=data.store,
        created_at=now.isoformat(),
    )


@router.get("", response_model=List[ExpenseResponse])
async def list_expenses(
    days: int = Query(default=30, ge=1, le=365, description="Lookback days"),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    current_user: dict = Depends(get_current_user),
) -> list:
    """List recent expenses."""
    db = get_database()
    user_id = current_user["id"]
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    query = {"userId": user_id, "date": {"$gte": cutoff}}
    if category:
        query["category"] = category.lower()

    cursor = db.expenses.find(query).sort("date", -1).limit(100)

    expenses = []
    async for doc in cursor:
        # SQLite may return datetime objects — ensure strings for Pydantic
        raw_date = doc.get("date", "")
        raw_created = doc.get("createdAt", "")
        expenses.append(ExpenseResponse(
            id=str(doc["_id"]),
            amount=doc["amount"],
            category=doc["category"],
            description=doc.get("description", ""),
            date=raw_date.isoformat() if hasattr(raw_date, "isoformat") else str(raw_date),
            store=doc.get("store"),
            created_at=raw_created.isoformat() if hasattr(raw_created, "isoformat") else str(raw_created),
        ))
    return expenses


@router.get("/summary")
async def spending_summary(
    days: int = Query(default=30, ge=1, le=365, description="Lookback days"),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Get spending summary grouped by category."""
    db = get_database()
    user_id = current_user["id"]
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    cursor = db.expenses.find({
        "userId": user_id,
        "date": {"$gte": cutoff},
    })

    by_category = {}
    total = 0.0
    count = 0

    async for doc in cursor:
        cat = doc.get("category", "other")
        amt = doc.get("amount", 0)
        by_category[cat] = by_category.get(cat, 0) + amt
        total += amt
        count += 1

    # Load budget goals
    goals_doc = await db.budget_goals.find_one({"userId": user_id})
    goals = goals_doc.get("goals", {}) if goals_doc else {}

    # Build category breakdown with budget comparison
    categories = []
    for cat, spent in sorted(by_category.items(), key=lambda x: -x[1]):
        entry = {"category": cat, "spent": round(spent, 2)}
        if cat in goals:
            entry["budget"] = goals[cat]
            entry["remaining"] = round(goals[cat] - spent, 2)
            entry["percent_used"] = round((spent / goals[cat]) * 100, 1) if goals[cat] > 0 else 0
        categories.append(entry)

    return {
        "period_days": days,
        "total_spent": round(total, 2),
        "total_budget": goals.get("total"),
        "expense_count": count,
        "categories": categories,
    }


@router.post("/goal")
async def set_budget_goal(
    data: BudgetGoal,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Set a monthly budget goal for a category or total."""
    db = get_database()
    user_id = current_user["id"]

    await db.budget_goals.update_one(
        {"userId": user_id},
        {"$set": {f"goals.{data.category}": data.amount, "updatedAt": datetime.utcnow().isoformat()}},
        upsert=True,
    )

    return {"status": "ok", "category": data.category, "budget": data.amount}


@router.delete("/{expense_id}")
async def delete_expense(
    expense_id: str,
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Delete an expense entry."""
    db = get_database()
    user_id = current_user["id"]

    result = await db.expenses.delete_one({
        "_id": ObjectId(expense_id),
        "userId": user_id,
    })
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Expense not found")

    return {"status": "deleted"}


# ── Receipt Parsing Helper ────────────────────────────────────

async def parse_receipt_text(text: str) -> dict:
    """
    Parse receipt text (from OCR or LLM vision) into structured expense data.

    Extracts store name, date, line items, and total from receipt text.
    Uses simple pattern matching — the LLM does the heavy lifting via
    the Budget Assistant persona when an image is uploaded.

    Args:
        text: Raw receipt text from OCR or LLM description.

    Returns:
        Dict with store, date, items (list), total.
    """
    import re

    result = {"store": None, "date": None, "items": [], "total": None}

    # Try to find total
    total_match = re.search(r'(?:total|amount due|grand total)[:\s]*\$?([\d,]+\.?\d*)', text, re.IGNORECASE)
    if total_match:
        result["total"] = float(total_match.group(1).replace(",", ""))

    # Try to find date
    date_match = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', text)
    if date_match:
        result["date"] = date_match.group(1)

    # First non-empty line is often the store name
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    if lines:
        result["store"] = lines[0]

    return result
