"""
Skills System - Reusable solutions with pattern triggers.

Design principles:
- Agents can persist their own code as reusable functions
- Skills are triggered by pattern matching on queries/errors
- Confidence scores evolve based on usage success
"""

import json
import re
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from datetime import datetime
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class SkillCategory(Enum):
    """Categories of skills."""
    ERROR_FIX = "error_fix"
    PATTERN = "pattern"
    REFACTOR = "refactor"
    SETUP = "setup"
    DEBUG = "debug"
    OPTIMIZATION = "optimization"
    SECURITY = "security"


@dataclass
class Skill:
    """A reusable solution that can be triggered by patterns."""
    id: str
    name: str
    description: str
    category: SkillCategory
    
    # Trigger patterns (regex)
    triggers: List[str]
    
    # The solution
    solution_text: str
    code_template: Optional[str] = None
    
    # Metadata
    technologies: List[str] = field(default_factory=list)
    file_patterns: List[str] = field(default_factory=list)  # e.g., "*.py", "*.tsx"
    
    # Confidence and usage tracking
    confidence: float = 0.7
    times_used: int = 0
    times_successful: int = 0
    times_failed: int = 0
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_used: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    
    # Versioning
    version: int = 1
    parent_skill_id: Optional[str] = None  # If evolved from another skill
    
    # User isolation
    user_id: str = "system"
    
    def matches(self, query: str, file_path: Optional[str] = None) -> float:
        """
        Check if this skill matches a query/error.
        Returns match score (0.0 to 1.0).
        """
        query_lower = query.lower()
        max_score = 0.0
        
        for trigger in self.triggers:
            try:
                if re.search(trigger, query, re.IGNORECASE):
                    # Base score for pattern match
                    score = 0.6
                    
                    # Boost if file pattern matches
                    if file_path and self.file_patterns:
                        file_ext = Path(file_path).suffix
                        for pattern in self.file_patterns:
                            if pattern.endswith(file_ext) or pattern == "*":
                                score += 0.2
                                break
                    
                    # Boost based on confidence
                    score += self.confidence * 0.2
                    
                    max_score = max(max_score, min(score, 1.0))
            except re.error:
                # Invalid regex, try literal match
                if trigger.lower() in query_lower:
                    max_score = max(max_score, 0.5)
        
        return max_score
    
    def record_usage(self, successful: bool) -> dict:
        """Record a usage of this skill."""
        self.times_used += 1
        self.last_used = datetime.utcnow()
        
        if successful:
            self.times_successful += 1
            # Increase confidence (with diminishing returns)
            boost = 0.05 * (1 - self.confidence)
            self.confidence = min(0.99, self.confidence + boost)
        else:
            self.times_failed += 1
            # Decrease confidence
            penalty = 0.1 * self.confidence
            self.confidence = max(0.1, self.confidence - penalty)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        d = asdict(self)
        d['category'] = self.category.value
        d['created_at'] = self.created_at.isoformat()
        d['last_used'] = self.last_used.isoformat() if self.last_used else None
        d['last_updated'] = self.last_updated.isoformat() if self.last_updated else None
        return d
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'Skill':
        """Create from dictionary."""
        d = d.copy()
        d['category'] = SkillCategory(d['category'])
        d['created_at'] = datetime.fromisoformat(d['created_at'])
        if d.get('last_used'):
            d['last_used'] = datetime.fromisoformat(d['last_used'])
        if d.get('last_updated'):
            d['last_updated'] = datetime.fromisoformat(d['last_updated'])
        return cls(**d)


class SkillStore:
    """
    Persistent storage for skills.
    Uses file-based storage with optional MongoDB backend.
    """
    
    def __init__(self, storage_path: Optional[str] = None, use_mongodb: bool = True):
        from config import SKILLS_DIR
        self.storage_path = Path(storage_path) if storage_path else SKILLS_DIR
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.use_mongodb = use_mongodb
        self._db = None
        self._skills_cache: Dict[str, Skill] = {}
        self._load_skills()
    
    def _get_db(self):
        """Get MongoDB database connection."""
        if self._db is None and self.use_mongodb:
            try:
                from database import get_database
                self._db = get_database()
            except Exception as e:
                logger.warning(f"MongoDB not available for skills: {e}")
                self.use_mongodb = False
        return self._db
    
    def _load_skills(self):
        """Load skills from storage."""
        # Load from files
        for skill_file in self.storage_path.glob("*.json"):
            try:
                with open(skill_file, 'r') as f:
                    skill = Skill.from_dict(json.load(f))
                    self._skills_cache[skill.id] = skill
            except Exception as e:
                logger.error(f"Failed to load skill {skill_file}: {e}")
        
        # Load built-in skills
        self._load_builtin_skills()
        
        logger.info(f"Loaded {len(self._skills_cache)} skills")
    
    def _load_builtin_skills(self):
        """Load built-in common skills."""
        builtin_skills = [
            Skill(
                id="builtin_cors_fix",
                name="CORS Error Fix",
                description="Fix Cross-Origin Resource Sharing errors in web applications",
                category=SkillCategory.ERROR_FIX,
                triggers=[
                    r"CORS",
                    r"Access-Control-Allow-Origin",
                    r"cross.?origin",
                    r"blocked by CORS policy"
                ],
                solution_text="""CORS errors occur when a web app tries to access resources from a different domain.

Fix options:
1. **Backend**: Add CORS middleware with allowed origins
2. **Proxy**: Use a development proxy to same-origin requests
3. **Headers**: Ensure server returns proper Access-Control-Allow-* headers""",
                code_template="""# FastAPI
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Your frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Express.js
const cors = require('cors');
app.use(cors({ origin: 'http://localhost:3000' }));""",
                technologies=["fastapi", "express", "react", "web"],
                confidence=0.9,
                user_id="system"
            ),
            Skill(
                id="builtin_typeerror_none",
                name="TypeError NoneType Fix",
                description="Fix TypeError when accessing attributes of None",
                category=SkillCategory.ERROR_FIX,
                triggers=[
                    r"TypeError.*NoneType",
                    r"'NoneType' object has no attribute",
                    r"cannot read.*of (null|undefined)"
                ],
                solution_text="""This error means you're trying to access an attribute/method on a None/null value.

Common causes:
1. Function returned None instead of expected value
2. Variable not initialized
3. Failed lookup (dict.get, list index, etc.)

Fix: Add null checks or use Optional chaining""",
                code_template="""# Python - Use Optional and guards
from typing import Optional

def get_user(id: str) -> Optional[User]:
    ...

user = get_user(id)
if user is not None:
    print(user.name)

# Or use getattr with default
name = getattr(user, 'name', 'Unknown')

# JavaScript - Optional chaining
const name = user?.name ?? 'Unknown';""",
                technologies=["python", "javascript", "typescript"],
                confidence=0.85,
                user_id="system"
            ),
            Skill(
                id="builtin_import_error",
                name="Import/Module Error Fix",
                description="Fix import errors and module not found issues",
                category=SkillCategory.ERROR_FIX,
                triggers=[
                    r"ImportError",
                    r"ModuleNotFoundError",
                    r"Cannot find module",
                    r"No module named"
                ],
                solution_text="""Module import errors usually mean:
1. Package not installed
2. Wrong import path
3. Circular import
4. Virtual environment not activated

Steps to fix:
1. Check if package is installed: pip list | grep <package>
2. Install if missing: pip install <package>
3. Check import path matches file structure
4. For circular imports: move import inside function or restructure""",
                code_template="""# Check and install
pip install <package_name>

# Or add to requirements.txt and install
pip install -r requirements.txt

# For path issues, ensure __init__.py exists
# project/
#   __init__.py
#   module/
#     __init__.py
#     file.py

# Fix circular import by moving import inside function
def my_function():
    from other_module import something  # Deferred import
    ...""",
                technologies=["python", "javascript", "node"],
                confidence=0.8,
                user_id="system"
            ),
            Skill(
                id="builtin_async_await",
                name="Async/Await Pattern",
                description="Proper async/await usage patterns",
                category=SkillCategory.PATTERN,
                triggers=[
                    r"async",
                    r"await",
                    r"coroutine",
                    r"Promise",
                    r"was never awaited"
                ],
                solution_text="""Async/await allows non-blocking code execution.

Key rules:
1. async functions return coroutines/promises
2. await can only be used inside async functions
3. Don't forget to await async calls
4. Use asyncio.gather() for parallel execution""",
                code_template="""# Python
import asyncio

async def fetch_data(url: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        return response.json()

# Parallel execution
results = await asyncio.gather(
    fetch_data(url1),
    fetch_data(url2)
)

# JavaScript
async function fetchData(url) {
    const response = await fetch(url);
    return response.json();
}

// Parallel
const [data1, data2] = await Promise.all([
    fetchData(url1),
    fetchData(url2)
]);""",
                technologies=["python", "javascript", "typescript"],
                confidence=0.85,
                user_id="system"
            ),
        ]
        
        for skill in builtin_skills:
            if skill.id not in self._skills_cache:
                self._skills_cache[skill.id] = skill
    
    async def add_skill(self, skill: Skill) -> str:
        """Add a new skill."""
        self._skills_cache[skill.id] = skill
        
        # Save to file
        skill_path = self.storage_path / f"{skill.id}.json"
        with open(skill_path, 'w') as f:
            json.dump(skill.to_dict(), f, indent=2)
        
        # Save to MongoDB if available
        db = self._get_db()
        if db:
            try:
                await db.skills.update_one(
                    {"id": skill.id},
                    {"$set": skill.to_dict()},
                    upsert=True
                )
            except Exception as e:
                logger.warning(f"Failed to save skill to MongoDB: {e}")
        
        logger.info(f"Added skill: {skill.name} ({skill.id})")
        return skill.id
    
    async def find_matching_skills(
        self,
        query: str,
        file_path: Optional[str] = None,
        user_id: Optional[str] = None,
        min_score: float = 0.4,
        limit: int = 5
    ) -> List[tuple[Skill, float]]:
        """
        Find skills that match a query.
        Returns list of (skill, score) tuples sorted by score.
        """
        matches = []
        
        for skill in self._skills_cache.values():
            # Filter by user (include system skills for everyone)
            if user_id and skill.user_id not in [user_id, "system"]:
                continue
            
            score = skill.matches(query, file_path)
            if score >= min_score:
                matches.append((skill, score))
        
        # Sort by score descending
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:limit]
    
    async def get_skill(self, skill_id: str) -> Optional[Skill]:
        """Get a skill by ID."""
        return self._skills_cache.get(skill_id)
    
    async def update_skill_usage(self, skill_id: str, successful: bool) -> dict:
        """Record skill usage and update confidence."""
        skill = self._skills_cache.get(skill_id)
        if skill:
            skill.record_usage(successful)
            
            # Persist update
            skill_path = self.storage_path / f"{skill.id}.json"
            with open(skill_path, 'w') as f:
                json.dump(skill.to_dict(), f, indent=2)
    
    async def evolve_skill(
        self,
        parent_skill_id: str,
        improvements: Dict[str, Any]
    ) -> Optional[Skill]:
        """
        Create an improved version of an existing skill.
        """
        parent = self._skills_cache.get(parent_skill_id)
        if not parent:
            return None
        
        from bson import ObjectId
        
        # Create evolved skill
        evolved = Skill(
            id=str(ObjectId()),
            name=improvements.get('name', parent.name),
            description=improvements.get('description', parent.description),
            category=parent.category,
            triggers=improvements.get('triggers', parent.triggers.copy()),
            solution_text=improvements.get('solution_text', parent.solution_text),
            code_template=improvements.get('code_template', parent.code_template),
            technologies=improvements.get('technologies', parent.technologies.copy()),
            file_patterns=improvements.get('file_patterns', parent.file_patterns.copy()),
            confidence=0.7,  # Reset confidence for new version
            version=parent.version + 1,
            parent_skill_id=parent_skill_id,
            user_id=improvements.get('user_id', parent.user_id)
        )
        
        await self.add_skill(evolved)
        return evolved
    
    def get_all_skills(self, user_id: Optional[str] = None) -> List[Skill]:
        """Get all skills, optionally filtered by user."""
        skills = list(self._skills_cache.values())
        if user_id:
            skills = [s for s in skills if s.user_id in [user_id, "system"]]
        return skills


# Singleton instance
_skill_store: Optional[SkillStore] = None


def get_skill_store() -> SkillStore:
    """Get or create the skill store singleton."""
    global _skill_store
    if _skill_store is None:
        _skill_store = SkillStore()
    return _skill_store
