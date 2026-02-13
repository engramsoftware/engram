"""
Session Continuity - Persist task state across restarts.

Enables:
- Saving current task context
- Resuming work after IDE restart
- Progress checkpoints for long tasks
- File working set tracking
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """Status of a task."""
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class CheckpointType(Enum):
    """Types of checkpoints."""
    AUTO = "auto"  # Automatic periodic save
    MILESTONE = "milestone"  # Major progress point
    USER = "user"  # User-requested save
    ERROR = "error"  # Saved due to error


@dataclass
class FileContext:
    """Context about a file being worked on."""
    path: str
    last_modified: datetime
    relevance_score: float = 1.0
    changes_made: List[str] = field(default_factory=list)
    line_ranges_viewed: List[tuple] = field(default_factory=list)


@dataclass 
class Checkpoint:
    """A snapshot of task progress."""
    id: str
    checkpoint_type: CheckpointType
    timestamp: datetime
    description: str
    
    # State at checkpoint
    completed_steps: List[str]
    pending_steps: List[str]
    current_step: Optional[str]
    
    # Context
    key_findings: List[str] = field(default_factory=list)
    decisions_made: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)


@dataclass
class TaskSession:
    """
    A persistent task session that can be resumed.
    """
    id: str
    user_id: str
    
    # Task definition
    task_description: str
    task_goal: str
    
    # Status
    status: TaskStatus = TaskStatus.NOT_STARTED
    progress_percent: float = 0.0
    
    # Plan
    plan_steps: List[str] = field(default_factory=list)
    current_step_index: int = 0
    
    # Working context
    working_files: List[FileContext] = field(default_factory=list)
    relevant_entities: List[str] = field(default_factory=list)  # Functions, classes, etc.
    
    # Accumulated knowledge
    context_summary: str = ""
    key_discoveries: List[str] = field(default_factory=list)
    attempted_solutions: List[Dict[str, Any]] = field(default_factory=list)
    
    # Checkpoints for resumption
    checkpoints: List[Checkpoint] = field(default_factory=list)
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    
    # Metadata
    technologies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    
    def add_checkpoint(
        self,
        description: str,
        checkpoint_type: CheckpointType = CheckpointType.AUTO,
        key_findings: Optional[List[str]] = None,
        blockers: Optional[List[str]] = None
    ) -> Checkpoint:
        """Create a checkpoint of current progress."""
        from bson import ObjectId
        
        completed = self.plan_steps[:self.current_step_index]
        pending = self.plan_steps[self.current_step_index + 1:]
        current = self.plan_steps[self.current_step_index] if self.current_step_index < len(self.plan_steps) else None
        
        checkpoint = Checkpoint(
            id=str(ObjectId()),
            checkpoint_type=checkpoint_type,
            timestamp=datetime.utcnow(),
            description=description,
            completed_steps=completed,
            pending_steps=pending,
            current_step=current,
            key_findings=key_findings or [],
            blockers=blockers or []
        )
        
        self.checkpoints.append(checkpoint)
        self.last_active = datetime.utcnow()
        return checkpoint
    
    def advance_step(self, step_summary: Optional[str] = None):
        """Mark current step complete and advance."""
        if step_summary:
            self.key_discoveries.append(f"Step {self.current_step_index + 1}: {step_summary}")
        
        self.current_step_index += 1
        self.progress_percent = (self.current_step_index / max(len(self.plan_steps), 1)) * 100
        self.last_active = datetime.utcnow()
        
        if self.current_step_index >= len(self.plan_steps):
            self.status = TaskStatus.COMPLETED
            self.completed_at = datetime.utcnow()
    
    def add_working_file(self, path: str, relevance: float = 1.0):
        """Add a file to the working set."""
        # Check if already exists
        for f in self.working_files:
            if f.path == path:
                f.relevance_score = max(f.relevance_score, relevance)
                return
        
        self.working_files.append(FileContext(
            path=path,
            last_modified=datetime.utcnow(),
            relevance_score=relevance
        ))
    
    def record_solution_attempt(
        self,
        description: str,
        code_changes: Optional[str] = None,
        result: str = "unknown"
    ):
        """Record an attempted solution."""
        self.attempted_solutions.append({
            "timestamp": datetime.utcnow().isoformat(),
            "description": description,
            "code_changes": code_changes,
            "result": result
        })
    
    def get_resumption_context(self) -> str:
        """Generate context string for resuming this task."""
        lines = [
            f"## Task: {self.task_description}",
            f"**Goal:** {self.task_goal}",
            f"**Status:** {self.status.value} ({self.progress_percent:.0f}% complete)",
            ""
        ]
        
        if self.plan_steps:
            lines.append("### Progress:")
            for i, step in enumerate(self.plan_steps):
                if i < self.current_step_index:
                    lines.append(f"- [x] {step}")
                elif i == self.current_step_index:
                    lines.append(f"- [ ] **{step}** ← Current")
                else:
                    lines.append(f"- [ ] {step}")
            lines.append("")
        
        if self.key_discoveries:
            lines.append("### Key Discoveries:")
            for discovery in self.key_discoveries[-5:]:  # Last 5
                lines.append(f"- {discovery}")
            lines.append("")
        
        if self.working_files:
            lines.append("### Working Files:")
            for f in sorted(self.working_files, key=lambda x: -x.relevance_score)[:10]:
                lines.append(f"- `{f.path}`")
            lines.append("")
        
        if self.context_summary:
            lines.append(f"### Context Summary:\n{self.context_summary}")
        
        return "\n".join(lines)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "task_description": self.task_description,
            "task_goal": self.task_goal,
            "status": self.status.value,
            "progress_percent": self.progress_percent,
            "plan_steps": self.plan_steps,
            "current_step_index": self.current_step_index,
            "working_files": [
                {
                    "path": f.path,
                    "last_modified": f.last_modified.isoformat(),
                    "relevance_score": f.relevance_score,
                    "changes_made": f.changes_made
                }
                for f in self.working_files
            ],
            "relevant_entities": self.relevant_entities,
            "context_summary": self.context_summary,
            "key_discoveries": self.key_discoveries,
            "attempted_solutions": self.attempted_solutions,
            "checkpoints": [
                {
                    "id": c.id,
                    "checkpoint_type": c.checkpoint_type.value,
                    "timestamp": c.timestamp.isoformat(),
                    "description": c.description,
                    "completed_steps": c.completed_steps,
                    "pending_steps": c.pending_steps,
                    "current_step": c.current_step,
                    "key_findings": c.key_findings,
                    "blockers": c.blockers
                }
                for c in self.checkpoints
            ],
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "technologies": self.technologies,
            "tags": self.tags
        }
    
    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'TaskSession':
        """Create from dictionary."""
        session = cls(
            id=d["id"],
            user_id=d["user_id"],
            task_description=d["task_description"],
            task_goal=d["task_goal"],
            status=TaskStatus(d["status"]),
            progress_percent=d["progress_percent"],
            plan_steps=d["plan_steps"],
            current_step_index=d["current_step_index"],
            relevant_entities=d.get("relevant_entities", []),
            context_summary=d.get("context_summary", ""),
            key_discoveries=d.get("key_discoveries", []),
            attempted_solutions=d.get("attempted_solutions", []),
            technologies=d.get("technologies", []),
            tags=d.get("tags", [])
        )
        
        # Parse working files
        for f in d.get("working_files", []):
            session.working_files.append(FileContext(
                path=f["path"],
                last_modified=datetime.fromisoformat(f["last_modified"]),
                relevance_score=f.get("relevance_score", 1.0),
                changes_made=f.get("changes_made", [])
            ))
        
        # Parse checkpoints
        for c in d.get("checkpoints", []):
            session.checkpoints.append(Checkpoint(
                id=c["id"],
                checkpoint_type=CheckpointType(c["checkpoint_type"]),
                timestamp=datetime.fromisoformat(c["timestamp"]),
                description=c["description"],
                completed_steps=c["completed_steps"],
                pending_steps=c["pending_steps"],
                current_step=c.get("current_step"),
                key_findings=c.get("key_findings", []),
                blockers=c.get("blockers", [])
            ))
        
        # Parse timestamps
        session.created_at = datetime.fromisoformat(d["created_at"])
        session.last_active = datetime.fromisoformat(d["last_active"])
        if d.get("completed_at"):
            session.completed_at = datetime.fromisoformat(d["completed_at"])
        
        return session


class SessionManager:
    """
    Manages task sessions with persistence.
    """
    
    def __init__(self, storage_path: Optional[str] = None, auto_checkpoint_minutes: int = 5):
        from config import SESSIONS_DIR
        self.storage_path = Path(storage_path) if storage_path else SESSIONS_DIR
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._active_sessions: Dict[str, TaskSession] = {}
        self._auto_checkpoint_minutes = auto_checkpoint_minutes
        self._checkpoint_thread = None
        self._running = False
        self._load_active_sessions()
        self._start_auto_checkpoint()
    
    def _load_active_sessions(self):
        """Load sessions that are still in progress."""
        for session_file in self.storage_path.glob("*.json"):
            try:
                with open(session_file, 'r') as f:
                    session = TaskSession.from_dict(json.load(f))
                    
                    # Only load non-completed sessions from last 7 days
                    if (session.status in [TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED] and 
                        datetime.utcnow() - session.last_active < timedelta(days=7)):
                        self._active_sessions[session.id] = session
            except Exception as e:
                logger.error(f"Failed to load session {session_file}: {e}")
        
        logger.info(f"Loaded {len(self._active_sessions)} active sessions")
    
    def _start_auto_checkpoint(self):
        """Start background thread for auto-checkpointing."""
        import threading
        import asyncio
        
        def checkpoint_loop():
            while self._running:
                import time
                time.sleep(self._auto_checkpoint_minutes * 60)
                if not self._running:
                    break
                
                # Checkpoint all active sessions
                for session_id, session in list(self._active_sessions.items()):
                    if session.status == TaskStatus.IN_PROGRESS:
                        try:
                            session.add_checkpoint(
                                f"Auto-checkpoint at {datetime.utcnow().strftime('%H:%M')}",
                                CheckpointType.AUTO
                            )
                            # Save synchronously
                            session_path = self.storage_path / f"{session.id}.json"
                            with open(session_path, 'w') as f:
                                json.dump(session.to_dict(), f, indent=2)
                            logger.debug(f"Auto-checkpointed session {session_id}")
                        except Exception as e:
                            logger.error(f"Auto-checkpoint failed for {session_id}: {e}")
        
        self._running = True
        self._checkpoint_thread = threading.Thread(target=checkpoint_loop, daemon=True)
        self._checkpoint_thread.start()
        logger.info(f"Auto-checkpoint started (every {self._auto_checkpoint_minutes} minutes)")
    
    def stop_auto_checkpoint(self):
        """Stop the auto-checkpoint thread."""
        self._running = False
        if self._checkpoint_thread:
            self._checkpoint_thread.join(timeout=2)
    
    async def create_session(
        self,
        user_id: str,
        task_description: str,
        task_goal: str,
        plan_steps: Optional[List[str]] = None
    ) -> TaskSession:
        """Create a new task session."""
        from bson import ObjectId
        
        session = TaskSession(
            id=str(ObjectId()),
            user_id=user_id,
            task_description=task_description,
            task_goal=task_goal,
            status=TaskStatus.IN_PROGRESS,
            plan_steps=plan_steps or []
        )
        
        self._active_sessions[session.id] = session
        await self._save_session(session)
        
        logger.info(f"Created session {session.id}: {task_description[:50]}")
        return session
    
    async def _save_session(self, session: TaskSession):
        """Persist a session to disk."""
        session_path = self.storage_path / f"{session.id}.json"
        with open(session_path, 'w') as f:
            json.dump(session.to_dict(), f, indent=2)
    
    async def get_session(self, session_id: str) -> Optional[TaskSession]:
        """Get a session by ID."""
        if session_id in self._active_sessions:
            return self._active_sessions[session_id]
        
        # Try loading from disk
        session_path = self.storage_path / f"{session_id}.json"
        if session_path.exists():
            with open(session_path, 'r') as f:
                return TaskSession.from_dict(json.load(f))
        
        return None
    
    async def get_user_sessions(
        self,
        user_id: str,
        include_completed: bool = False,
        limit: int = 10
    ) -> List[TaskSession]:
        """Get sessions for a user."""
        sessions = []
        
        for session in self._active_sessions.values():
            if session.user_id == user_id:
                if include_completed or session.status not in [TaskStatus.COMPLETED, TaskStatus.ABANDONED]:
                    sessions.append(session)
        
        # Sort by last active
        sessions.sort(key=lambda s: s.last_active, reverse=True)
        return sessions[:limit]
    
    async def update_session(self, session: TaskSession):
        """Update and persist a session."""
        session.last_active = datetime.utcnow()
        self._active_sessions[session.id] = session
        await self._save_session(session)
    
    async def checkpoint_session(
        self,
        session_id: str,
        description: str,
        checkpoint_type: CheckpointType = CheckpointType.AUTO,
        key_findings: Optional[List[str]] = None
    ) -> Optional[Checkpoint]:
        """Create a checkpoint for a session."""
        session = self._active_sessions.get(session_id)
        if not session:
            return None
        
        checkpoint = session.add_checkpoint(
            description=description,
            checkpoint_type=checkpoint_type,
            key_findings=key_findings
        )
        
        await self._save_session(session)
        return checkpoint
    
    async def get_resumable_sessions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get sessions that can be resumed with summary info."""
        sessions = await self.get_user_sessions(user_id, include_completed=False)
        
        return [
            {
                "id": s.id,
                "task": s.task_description[:100],
                "progress": f"{s.progress_percent:.0f}%",
                "status": s.status.value,
                "last_active": s.last_active.isoformat(),
                "current_step": s.plan_steps[s.current_step_index] if s.current_step_index < len(s.plan_steps) else None
            }
            for s in sessions
        ]


# Singleton instance
_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Get or create the session manager singleton."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
