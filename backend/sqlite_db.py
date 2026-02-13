"""
SQLite adapter that mimics the Motor/MongoDB async API.

Replaces MongoDB with a zero-install SQLite backend. All existing routers
continue calling db.collection.find(), db.collection.insert_one(), etc.
without any code changes.

Architecture:
  - Each MongoDB "collection" becomes a SQLite table with:
    - _id TEXT PRIMARY KEY (auto-generated UUID if not provided)
    - data JSON (the full document as JSON)
    - Plus indexed columns extracted from the JSON for fast queries
  - Query operators ($set, $in, $gt, etc.) are translated to SQL WHERE clauses
  - Cursors support .sort(), .limit(), .skip(), async iteration

Usage:
    db = get_database()
    doc = await db.users.find_one({"email": "test@example.com"})
    await db.messages.insert_one({"content": "hello", "userId": "123"})
"""

import json
import logging
import uuid
import re
import aiosqlite
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# ============================================================
# ObjectId replacement — generates MongoDB-style hex IDs
# ============================================================

class ObjectId:
    """MongoDB ObjectId replacement using UUID hex strings.

    Generates 24-character hex strings that look like MongoDB ObjectIds.
    Accepts existing ID strings for lookups.
    """

    def __init__(self, oid: Optional[str] = None):
        if oid:
            self._id = str(oid)
        else:
            self._id = uuid.uuid4().hex[:24]

    def __str__(self) -> str:
        return self._id

    def __repr__(self) -> str:
        return f"ObjectId('{self._id}')"

    def __eq__(self, other) -> bool:
        if isinstance(other, ObjectId):
            return self._id == other._id
        if isinstance(other, str):
            return self._id == other
        return False

    def __hash__(self) -> int:
        return hash(self._id)


# ============================================================
# Query translator — MongoDB query operators → SQL
# ============================================================

def _serialize_value(val: Any) -> Any:
    """Serialize a Python value for JSON storage."""
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, ObjectId):
        return str(val)
    if isinstance(val, list):
        return [_serialize_value(v) for v in val]
    if isinstance(val, dict):
        return {k: _serialize_value(v) for k, v in val.items()}
    return val


def _deserialize_doc(doc_json: str) -> Dict[str, Any]:
    """Deserialize a JSON document, converting ISO dates back to datetime."""
    doc = json.loads(doc_json)
    # Convert known date fields back to datetime objects
    for key in ("createdAt", "updatedAt", "invalidatedAt", "timestamp",
                "scheduledAt", "sentAt", "lastLogin", "lastChecked",
                "fetchedAt", "expiresAt"):
        if key in doc and doc[key] and isinstance(doc[key], str):
            try:
                doc[key] = datetime.fromisoformat(doc[key])
            except (ValueError, TypeError):
                pass
    return doc


def _build_where(query: Dict[str, Any]) -> Tuple[str, List[Any]]:
    """Translate a MongoDB query dict to SQL WHERE clause + params.

    Supports: exact match, $gt, $gte, $lt, $lte, $ne, $in, $nin,
    $exists, $regex, $or, $and, $text, nested dot notation.

    Args:
        query: MongoDB-style query dict.

    Returns:
        (where_clause, params) — clause does NOT include 'WHERE' keyword.
    """
    if not query:
        return "1=1", []

    conditions = []
    params = []

    for key, value in query.items():
        if key == "$or":
            or_parts = []
            for sub_query in value:
                sub_where, sub_params = _build_where(sub_query)
                or_parts.append(f"({sub_where})")
                params.extend(sub_params)
            conditions.append(f"({' OR '.join(or_parts)})")

        elif key == "$and":
            for sub_query in value:
                sub_where, sub_params = _build_where(sub_query)
                conditions.append(f"({sub_where})")
                params.extend(sub_params)

        elif key == "$text":
            # MongoDB text search — translate to LIKE on the data column
            search_val = value.get("$search", "") if isinstance(value, dict) else str(value)
            conditions.append("data LIKE ?")
            params.append(f"%{search_val}%")

        elif key == "_id":
            if isinstance(value, dict):
                # Operator on _id
                for op, op_val in value.items():
                    if op == "$in":
                        placeholders = ",".join("?" for _ in op_val)
                        conditions.append(f"_id IN ({placeholders})")
                        params.extend(str(v) for v in op_val)
                    elif op == "$ne":
                        conditions.append("_id != ?")
                        params.append(str(op_val))
            else:
                conditions.append("_id = ?")
                params.append(str(value))

        elif isinstance(value, dict) and any(k.startswith("$") for k in value):
            # Operator query on a field
            for op, op_val in value.items():
                json_path = _json_extract(key)
                if op == "$gt":
                    conditions.append(f"{json_path} > ?")
                    params.append(_serialize_value(op_val))
                elif op == "$gte":
                    conditions.append(f"{json_path} >= ?")
                    params.append(_serialize_value(op_val))
                elif op == "$lt":
                    conditions.append(f"{json_path} < ?")
                    params.append(_serialize_value(op_val))
                elif op == "$lte":
                    conditions.append(f"{json_path} <= ?")
                    params.append(_serialize_value(op_val))
                elif op == "$ne":
                    if op_val is None:
                        conditions.append(f"{json_path} IS NOT NULL")
                    else:
                        conditions.append(f"{json_path} != ?")
                        params.append(_serialize_value(op_val))
                elif op == "$in":
                    if op_val:
                        placeholders = ",".join("?" for _ in op_val)
                        conditions.append(f"{json_path} IN ({placeholders})")
                        params.extend(_serialize_value(v) for v in op_val)
                    else:
                        conditions.append("0")  # Empty $in matches nothing
                elif op == "$nin":
                    if op_val:
                        placeholders = ",".join("?" for _ in op_val)
                        conditions.append(f"{json_path} NOT IN ({placeholders})")
                        params.extend(_serialize_value(v) for v in op_val)
                elif op == "$exists":
                    if op_val:
                        conditions.append(f"{json_path} IS NOT NULL")
                    else:
                        conditions.append(f"{json_path} IS NULL")
                elif op == "$regex":
                    # SQLite doesn't have native regex, use LIKE for simple patterns
                    pattern = str(op_val)
                    # Convert basic regex to LIKE pattern
                    like_pattern = pattern.replace(".*", "%").replace(".", "_")
                    if not like_pattern.startswith("%"):
                        like_pattern = "%" + like_pattern
                    if not like_pattern.endswith("%"):
                        like_pattern = like_pattern + "%"
                    conditions.append(f"{json_path} LIKE ?")
                    params.append(like_pattern)
                elif op == "$search":
                    # Text search on specific field
                    conditions.append(f"{json_path} LIKE ?")
                    params.append(f"%{op_val}%")

        elif value is None:
            json_path = _json_extract(key)
            conditions.append(f"({json_path} IS NULL OR {json_path} = 'null')")

        else:
            # Exact match
            json_path = _json_extract(key)
            if isinstance(value, bool):
                conditions.append(f"{json_path} = ?")
                params.append(1 if value else 0)
            else:
                conditions.append(f"{json_path} = ?")
                params.append(_serialize_value(value))

    return " AND ".join(conditions) if conditions else "1=1", params


def _json_extract(field: str) -> str:
    """Build a SQLite json_extract expression for a field path.

    Handles dot notation: 'user.name' → json_extract(data, '$.user.name')
    Sanitizes field name to prevent SQL injection via crafted field paths.
    """
    # Only allow alphanumeric, dots, underscores, and hyphens in field paths
    sanitized = re.sub(r"[^a-zA-Z0-9._\-]", "", field)
    return f"json_extract(data, '$.{sanitized}')"


def _build_sort(sort_spec) -> str:
    """Translate MongoDB sort spec to SQL ORDER BY.

    Accepts:
      - String: "field" (ascending)
      - Tuple: ("field", 1) or ("field", -1)
      - List of tuples: [("field1", 1), ("field2", -1)]
    """
    if not sort_spec:
        return ""

    if isinstance(sort_spec, str):
        return f"ORDER BY {_json_extract(sort_spec)} ASC"

    if isinstance(sort_spec, tuple) and len(sort_spec) == 2:
        field, direction = sort_spec
        d = "DESC" if direction == -1 else "ASC"
        return f"ORDER BY {_json_extract(field)} {d}"

    if isinstance(sort_spec, list):
        parts = []
        for field, direction in sort_spec:
            d = "DESC" if direction == -1 else "ASC"
            parts.append(f"{_json_extract(field)} {d}")
        return "ORDER BY " + ", ".join(parts)

    return ""


def _apply_update(doc: Dict, update: Dict) -> Dict:
    """Apply MongoDB update operators to a document in-memory.

    Supports: $set, $unset, $push, $pull, $inc, $addToSet.
    If no operators are present, treats the update as a replacement.
    """
    has_operators = any(k.startswith("$") for k in update)

    if not has_operators:
        # Full replacement (preserve _id)
        _id = doc.get("_id")
        doc = dict(update)
        if _id:
            doc["_id"] = _id
        return doc

    for op, fields in update.items():
        if op == "$set":
            for k, v in fields.items():
                _set_nested(doc, k, _serialize_value(v))
        elif op == "$unset":
            for k in fields:
                parts = k.split(".")
                target = doc
                for p in parts[:-1]:
                    target = target.get(p, {})
                target.pop(parts[-1], None)
        elif op == "$push":
            for k, v in fields.items():
                arr = doc.get(k, [])
                if not isinstance(arr, list):
                    arr = []
                if isinstance(v, dict) and "$each" in v:
                    arr.extend(_serialize_value(item) for item in v["$each"])
                else:
                    arr.append(_serialize_value(v))
                doc[k] = arr
        elif op == "$pull":
            for k, v in fields.items():
                arr = doc.get(k, [])
                if isinstance(arr, list):
                    doc[k] = [item for item in arr if item != _serialize_value(v)]
        elif op == "$inc":
            for k, v in fields.items():
                doc[k] = doc.get(k, 0) + v
        elif op == "$addToSet":
            for k, v in fields.items():
                arr = doc.get(k, [])
                if not isinstance(arr, list):
                    arr = []
                sv = _serialize_value(v)
                if sv not in arr:
                    arr.append(sv)
                doc[k] = arr

    return doc


def _set_nested(doc: Dict, key: str, value: Any) -> None:
    """Set a nested field using dot notation: 'a.b.c' → doc['a']['b']['c'] = value."""
    parts = key.split(".")
    target = doc
    for p in parts[:-1]:
        if p not in target or not isinstance(target[p], dict):
            target[p] = {}
        target = target[p]
    target[parts[-1]] = value


# ============================================================
# Cursor — async iterator over query results
# ============================================================

class SQLiteCursor:
    """Async cursor that mimics Motor's cursor with sort/limit/skip.

    Lazily executes the query on first iteration or when to_list() is called.
    """

    def __init__(self, collection: "SQLiteCollection", query: Dict,
                 projection: Optional[Dict] = None):
        self._collection = collection
        self._query = query
        self._projection = projection
        self._sort_spec = None
        self._limit_val = 0
        self._skip_val = 0
        self._results: Optional[List[Dict]] = None

    def sort(self, key_or_list, direction=None) -> "SQLiteCursor":
        """Set sort order. Accepts MongoDB-style sort specs."""
        if direction is not None:
            self._sort_spec = [(key_or_list, direction)]
        elif isinstance(key_or_list, str):
            self._sort_spec = [(key_or_list, 1)]
        elif isinstance(key_or_list, list):
            self._sort_spec = key_or_list
        return self

    def limit(self, count: int) -> "SQLiteCursor":
        """Limit the number of results."""
        self._limit_val = count
        return self

    def skip(self, count: int) -> "SQLiteCursor":
        """Skip the first N results."""
        self._skip_val = count
        return self

    async def _execute(self) -> List[Dict]:
        """Execute the query and return results."""
        if self._results is not None:
            return self._results

        await self._collection._ensure_table()
        where, params = _build_where(self._query)
        order = ""
        if self._sort_spec:
            order = _build_sort(self._sort_spec)

        sql = f"SELECT _id, data FROM [{self._collection.name}] WHERE {where} {order}"
        if self._limit_val > 0:
            sql += f" LIMIT {self._limit_val}"
            if self._skip_val > 0:
                sql += f" OFFSET {self._skip_val}"
        elif self._skip_val > 0:
            sql += f" LIMIT -1 OFFSET {self._skip_val}"

        results = []
        async with self._collection._db._get_conn() as conn:
            async with conn.execute(sql, params) as cursor:
                async for row in cursor:
                    doc = _deserialize_doc(row[1])
                    doc["_id"] = row[0]
                    if self._projection:
                        doc = _apply_projection(doc, self._projection)
                    results.append(doc)

        self._results = results
        return results

    async def to_list(self, length: Optional[int] = None) -> List[Dict]:
        """Execute and return results as a list."""
        results = await self._execute()
        if length:
            return results[:length]
        return results

    def __aiter__(self):
        self._iter_index = 0
        self._results = None  # Reset for re-iteration
        return self

    async def __anext__(self) -> Dict:
        results = await self._execute()
        if self._iter_index >= len(results):
            raise StopAsyncIteration
        doc = results[self._iter_index]
        self._iter_index += 1
        return doc


def _apply_projection(doc: Dict, projection: Dict) -> Dict:
    """Apply MongoDB-style field projection to a document."""
    if not projection:
        return doc

    # Check if it's inclusion or exclusion
    has_include = any(v == 1 for v in projection.values() if not isinstance(v, dict))
    has_exclude = any(v == 0 for v in projection.values() if not isinstance(v, dict))

    if has_include:
        result = {"_id": doc.get("_id")}
        for field, val in projection.items():
            if val == 1 and field in doc:
                result[field] = doc[field]
            elif val == 0 and field == "_id":
                result.pop("_id", None)
        return result
    elif has_exclude:
        result = dict(doc)
        for field, val in projection.items():
            if val == 0:
                result.pop(field, None)
        return result

    return doc


# ============================================================
# Collection — mimics Motor's AsyncIOMotorCollection
# ============================================================

class SQLiteCollection:
    """Async SQLite collection that mimics Motor's MongoDB collection API.

    Each collection is a SQLite table with columns:
      - _id TEXT PRIMARY KEY
      - data TEXT (JSON document)
    """

    def __init__(self, db: "SQLiteDatabase", name: str):
        self._db = db
        self.name = name

    async def _ensure_table(self) -> None:
        """Create the table if it doesn't exist."""
        async with self._db._get_conn() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS [{self.name}] (
                    _id TEXT PRIMARY KEY,
                    data TEXT NOT NULL
                )
            """)
            await conn.commit()

    async def insert_one(self, document: Dict) -> "InsertOneResult":
        """Insert a single document."""
        await self._ensure_table()
        doc = dict(document)
        _id = doc.pop("_id", None)
        if _id is None:
            _id = ObjectId()
        _id = str(_id)
        doc_serialized = json.dumps(_serialize_value(doc), default=str)

        async with self._db._get_conn() as conn:
            await conn.execute(
                f"INSERT INTO [{self.name}] (_id, data) VALUES (?, ?)",
                (_id, doc_serialized),
            )
            await conn.commit()

        return InsertOneResult(_id)

    async def insert_many(self, documents: List[Dict]) -> "InsertManyResult":
        """Insert multiple documents."""
        await self._ensure_table()
        ids = []
        async with self._db._get_conn() as conn:
            for doc in documents:
                doc = dict(doc)
                _id = doc.pop("_id", None)
                if _id is None:
                    _id = ObjectId()
                _id = str(_id)
                doc_serialized = json.dumps(_serialize_value(doc), default=str)
                await conn.execute(
                    f"INSERT INTO [{self.name}] (_id, data) VALUES (?, ?)",
                    (_id, doc_serialized),
                )
                ids.append(_id)
            await conn.commit()
        return InsertManyResult(ids)

    async def find_one(self, query: Optional[Dict] = None,
                       projection: Optional[Dict] = None,
                       sort: Optional[list] = None) -> Optional[Dict]:
        """Find a single document matching the query.

        Args:
            query: MongoDB-style query dict.
            projection: Field inclusion/exclusion.
            sort: Optional sort spec for picking which doc to return.
        """
        await self._ensure_table()
        query = query or {}

        where, params = _build_where(query)
        order = _build_sort(sort) if sort else ""
        sql = f"SELECT _id, data FROM [{self.name}] WHERE {where} {order} LIMIT 1"

        async with self._db._get_conn() as conn:
            async with conn.execute(sql, params) as cursor:
                row = await cursor.fetchone()
                if row:
                    doc = _deserialize_doc(row[1])
                    doc["_id"] = row[0]
                    if projection:
                        doc = _apply_projection(doc, projection)
                    return doc
        return None

    def find(self, query: Optional[Dict] = None,
             projection: Optional[Dict] = None) -> SQLiteCursor:
        """Return a cursor for documents matching the query."""
        return SQLiteCursor(self, query or {}, projection)

    async def update_one(self, query: Dict, update: Dict,
                         upsert: bool = False) -> "UpdateResult":
        """Update a single document."""
        await self._ensure_table()
        doc = await self.find_one(query)

        if doc is None:
            if upsert:
                # Create new document from query + update
                new_doc = dict(query)
                new_doc = _apply_update(new_doc, update)
                new_doc.pop("_id", None)
                result = await self.insert_one(new_doc)
                return UpdateResult(0, 1, result.inserted_id)
            return UpdateResult(0, 0)

        _id = doc.pop("_id")
        updated = _apply_update(doc, update)
        doc_serialized = json.dumps(_serialize_value(updated), default=str)

        async with self._db._get_conn() as conn:
            await conn.execute(
                f"UPDATE [{self.name}] SET data = ? WHERE _id = ?",
                (doc_serialized, _id),
            )
            await conn.commit()

        return UpdateResult(1, 1)

    async def update_many(self, query: Dict, update: Dict) -> "UpdateResult":
        """Update all documents matching the query."""
        await self._ensure_table()
        cursor = self.find(query)
        docs = await cursor.to_list()
        modified = 0

        async with self._db._get_conn() as conn:
            for doc in docs:
                _id = doc.pop("_id")
                updated = _apply_update(doc, update)
                doc_serialized = json.dumps(_serialize_value(updated), default=str)
                await conn.execute(
                    f"UPDATE [{self.name}] SET data = ? WHERE _id = ?",
                    (doc_serialized, _id),
                )
                modified += 1
            await conn.commit()

        return UpdateResult(len(docs), modified)

    async def delete_one(self, query: Dict) -> "DeleteResult":
        """Delete a single document."""
        await self._ensure_table()
        doc = await self.find_one(query)
        if doc is None:
            return DeleteResult(0)

        _id = doc["_id"]
        async with self._db._get_conn() as conn:
            await conn.execute(f"DELETE FROM [{self.name}] WHERE _id = ?", (_id,))
            await conn.commit()

        return DeleteResult(1)

    async def delete_many(self, query: Dict) -> "DeleteResult":
        """Delete all documents matching the query."""
        await self._ensure_table()
        where, params = _build_where(query)

        async with self._db._get_conn() as conn:
            cursor = await conn.execute(
                f"DELETE FROM [{self.name}] WHERE {where}", params
            )
            await conn.commit()
            return DeleteResult(cursor.rowcount)

    async def find_one_and_update(self, query: Dict, update: Dict,
                                  return_document: bool = False,
                                  upsert: bool = False) -> Optional[Dict]:
        """Find a document, update it, and return it.

        Args:
            return_document: If True, return the updated document.
                           If False, return the original (pre-update).
        """
        await self._ensure_table()
        doc = await self.find_one(query)

        if doc is None:
            if upsert:
                new_doc = dict(query)
                new_doc = _apply_update(new_doc, update)
                new_doc.pop("_id", None)
                result = await self.insert_one(new_doc)
                if return_document:
                    return await self.find_one({"_id": result.inserted_id})
            return None

        original = dict(doc)
        _id = doc.pop("_id")
        updated = _apply_update(doc, update)
        doc_serialized = json.dumps(_serialize_value(updated), default=str)

        async with self._db._get_conn() as conn:
            await conn.execute(
                f"UPDATE [{self.name}] SET data = ? WHERE _id = ?",
                (doc_serialized, _id),
            )
            await conn.commit()

        if return_document:
            updated["_id"] = _id
            return updated
        return original

    async def find_one_and_delete(self, query: Dict) -> Optional[Dict]:
        """Find a document, delete it, and return it."""
        await self._ensure_table()
        doc = await self.find_one(query)
        if doc is None:
            return None

        _id = doc["_id"]
        async with self._db._get_conn() as conn:
            await conn.execute(f"DELETE FROM [{self.name}] WHERE _id = ?", (_id,))
            await conn.commit()

        return doc

    async def count_documents(self, query: Optional[Dict] = None) -> int:
        """Count documents matching the query."""
        await self._ensure_table()
        query = query or {}
        where, params = _build_where(query)
        sql = f"SELECT COUNT(*) FROM [{self.name}] WHERE {where}"

        async with self._db._get_conn() as conn:
            async with conn.execute(sql, params) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def distinct(self, field: str, query: Optional[Dict] = None) -> List:
        """Get distinct values for a field."""
        await self._ensure_table()
        query = query or {}
        where, params = _build_where(query)
        json_path = _json_extract(field)
        sql = f"SELECT DISTINCT {json_path} FROM [{self.name}] WHERE {where}"

        results = []
        async with self._db._get_conn() as conn:
            async with conn.execute(sql, params) as cursor:
                async for row in cursor:
                    if row[0] is not None:
                        results.append(row[0])
        return results

    async def aggregate(self, pipeline: List[Dict]) -> List[Dict]:
        """Basic aggregation support.

        Supports a subset of MongoDB aggregation: $match, $group, $sort,
        $limit, $project, $unwind. Complex pipelines may need extension.
        """
        await self._ensure_table()
        # For simple pipelines, execute step by step in Python
        # Start with all documents
        docs = await self.find({}).to_list()

        for stage in pipeline:
            if "$match" in stage:
                # Filter in Python using the query logic
                filtered = []
                for doc in docs:
                    if _doc_matches(doc, stage["$match"]):
                        filtered.append(doc)
                docs = filtered

            elif "$sort" in stage:
                sort_spec = stage["$sort"]
                for field, direction in reversed(list(sort_spec.items())):
                    docs.sort(
                        key=lambda d: d.get(field, ""),
                        reverse=(direction == -1),
                    )

            elif "$limit" in stage:
                docs = docs[:stage["$limit"]]

            elif "$skip" in stage:
                docs = docs[stage["$skip"]:]

            elif "$project" in stage:
                projected = []
                for doc in docs:
                    projected.append(_apply_projection(doc, stage["$project"]))
                docs = projected

            elif "$unwind" in stage:
                field = stage["$unwind"]
                if isinstance(field, str) and field.startswith("$"):
                    field = field[1:]
                unwound = []
                for doc in docs:
                    arr = doc.get(field, [])
                    if isinstance(arr, list):
                        for item in arr:
                            new_doc = dict(doc)
                            new_doc[field] = item
                            unwound.append(new_doc)
                    else:
                        unwound.append(doc)
                docs = unwound

            elif "$group" in stage:
                groups: Dict[Any, Dict] = {}
                group_spec = stage["$group"]
                id_spec = group_spec["_id"]

                for doc in docs:
                    # Compute group key
                    if isinstance(id_spec, str) and id_spec.startswith("$"):
                        key = doc.get(id_spec[1:])
                    elif isinstance(id_spec, dict):
                        key = tuple(
                            doc.get(v[1:]) if isinstance(v, str) and v.startswith("$") else v
                            for v in id_spec.values()
                        )
                    else:
                        key = id_spec

                    if key not in groups:
                        groups[key] = {"_id": key}

                    # Apply accumulators
                    for out_field, acc in group_spec.items():
                        if out_field == "_id":
                            continue
                        if isinstance(acc, dict):
                            if "$sum" in acc:
                                val = acc["$sum"]
                                if val == 1:
                                    groups[key][out_field] = groups[key].get(out_field, 0) + 1
                                elif isinstance(val, str) and val.startswith("$"):
                                    groups[key][out_field] = groups[key].get(out_field, 0) + doc.get(val[1:], 0)
                            elif "$push" in acc:
                                val = acc["$push"]
                                if out_field not in groups[key]:
                                    groups[key][out_field] = []
                                if isinstance(val, str) and val.startswith("$"):
                                    groups[key][out_field].append(doc.get(val[1:]))
                                else:
                                    groups[key][out_field].append(val)
                            elif "$first" in acc:
                                val = acc["$first"]
                                if out_field not in groups[key]:
                                    if isinstance(val, str) and val.startswith("$"):
                                        groups[key][out_field] = doc.get(val[1:])
                                    else:
                                        groups[key][out_field] = val

                docs = list(groups.values())

        return docs

    async def create_indexes(self, indexes) -> None:
        """No-op for compatibility — SQLite uses json_extract for queries."""
        pass

    async def create_index(self, keys, **kwargs) -> None:
        """No-op for compatibility."""
        pass


def _doc_matches(doc: Dict, query: Dict) -> bool:
    """Check if a document matches a MongoDB query (in-memory)."""
    for key, value in query.items():
        if key == "$or":
            if not any(_doc_matches(doc, sub) for sub in value):
                return False
        elif key == "$and":
            if not all(_doc_matches(doc, sub) for sub in value):
                return False
        elif isinstance(value, dict) and any(k.startswith("$") for k in value):
            doc_val = doc.get(key)
            for op, op_val in value.items():
                if op == "$gt" and not (doc_val is not None and doc_val > op_val):
                    return False
                elif op == "$gte" and not (doc_val is not None and doc_val >= op_val):
                    return False
                elif op == "$lt" and not (doc_val is not None and doc_val < op_val):
                    return False
                elif op == "$lte" and not (doc_val is not None and doc_val <= op_val):
                    return False
                elif op == "$ne" and doc_val == op_val:
                    return False
                elif op == "$in" and doc_val not in op_val:
                    return False
                elif op == "$exists" and (op_val and key not in doc) or (not op_val and key in doc):
                    return False
        elif value is None:
            if doc.get(key) is not None:
                return False
        elif doc.get(key) != value:
            return False
    return True


# ============================================================
# Result types — mimic Motor/PyMongo result objects
# ============================================================

class InsertOneResult:
    def __init__(self, inserted_id: str):
        self.inserted_id = inserted_id


class InsertManyResult:
    def __init__(self, inserted_ids: List[str]):
        self.inserted_ids = inserted_ids


class UpdateResult:
    def __init__(self, matched_count: int, modified_count: int,
                 upserted_id: Optional[str] = None):
        self.matched_count = matched_count
        self.modified_count = modified_count
        self.upserted_id = upserted_id


class DeleteResult:
    def __init__(self, deleted_count: int):
        self.deleted_count = deleted_count


# ============================================================
# Database — mimics Motor's AsyncIOMotorDatabase
# ============================================================

class SQLiteDatabase:
    """Async SQLite database that mimics Motor's MongoDB database API.

    Collections are accessed as attributes: db.users, db.messages, etc.
    Each collection becomes a table in the SQLite database.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        self._collections: Dict[str, SQLiteCollection] = {}

    async def connect(self) -> None:
        """Open the SQLite connection."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(
            self._db_path,
            timeout=30.0,
        )
        # Enable WAL mode for better concurrent read/write performance
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        logger.info(f"SQLite database connected: {self._db_path}")

    async def close(self) -> None:
        """Close the SQLite connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("SQLite database closed")

    def _get_conn(self):
        """Get the connection (context manager compatible)."""
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")
        return _ConnContext(self._conn)

    async def command(self, cmd: str) -> Dict:
        """Mimic MongoDB admin commands (ping, etc.)."""
        if cmd == "ping":
            # Verify connection is alive
            async with self._get_conn() as conn:
                await conn.execute("SELECT 1")
            return {"ok": 1}
        return {"ok": 1}

    def __getattr__(self, name: str) -> SQLiteCollection:
        """Access collections as attributes: db.users, db.messages, etc."""
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._collections:
            self._collections[name] = SQLiteCollection(self, name)
        return self._collections[name]

    def __getitem__(self, name: str) -> SQLiteCollection:
        """Access collections as items: db['users']."""
        if name not in self._collections:
            self._collections[name] = SQLiteCollection(self, name)
        return self._collections[name]


class _ConnContext:
    """Async context manager wrapper for the shared connection."""

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn

    async def __aenter__(self) -> aiosqlite.Connection:
        return self._conn

    async def __aexit__(self, *args):
        pass  # Connection stays open — managed by SQLiteDatabase


# ============================================================
# Global database instance — drop-in replacement for database.py
# ============================================================

_database: Optional[SQLiteDatabase] = None


async def connect_to_database() -> None:
    """Initialize the SQLite database connection.

    Drop-in replacement for connect_to_mongodb().
    """
    global _database
    from config import get_settings
    settings = get_settings()

    # Database file lives in the data directory
    db_path = str(Path(settings.data_dir) / "app.db") if hasattr(settings, "data_dir") else str(
        Path(__file__).parent.parent / "data" / "app.db"
    )

    _database = SQLiteDatabase(db_path)
    await _database.connect()
    logger.info(f"SQLite database ready at {db_path}")


async def close_database_connection() -> None:
    """Close the database connection. Drop-in for close_mongodb_connection()."""
    global _database
    if _database:
        await _database.close()


def get_database() -> SQLiteDatabase:
    """Get the database instance. Drop-in for the MongoDB version."""
    if _database is None:
        raise RuntimeError("Database not initialized. Call connect_to_database() first.")
    return _database
