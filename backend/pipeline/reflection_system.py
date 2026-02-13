"""
Reflection/Self-Improvement System - Learn from outcomes.

Enables:
- Evaluating solution success after completion
- Updating skill confidence based on outcomes
- Learning patterns from failures
- Continuous improvement of retrieval strategies
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class OutcomeType(Enum):
    """Types of task outcomes."""
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILURE = "failure"
    UNKNOWN = "unknown"


class FeedbackSource(Enum):
    """Sources of feedback."""
    USER_EXPLICIT = "user_explicit"  # User said it worked/didn't work
    USER_IMPLICIT = "user_implicit"  # User continued without issues
    AUTOMATED = "automated"  # Code ran/compiled successfully
    INFERRED = "inferred"  # Inferred from context


@dataclass
class Outcome:
    """Recorded outcome of a task or solution."""
    id: str
    timestamp: datetime
    
    # What was attempted
    task_description: str
    solution_applied: str
    skills_used: List[str] = field(default_factory=list)
    
    # Result
    outcome_type: OutcomeType = OutcomeType.UNKNOWN
    feedback_source: FeedbackSource = FeedbackSource.INFERRED
    
    # Details
    error_if_failed: Optional[str] = None
    success_indicators: List[str] = field(default_factory=list)
    
    # Context
    technologies: List[str] = field(default_factory=list)
    file_paths: List[str] = field(default_factory=list)
    
    # Learning
    lessons_learned: List[str] = field(default_factory=list)
    should_create_skill: bool = False


@dataclass
class ReflectionInsight:
    """An insight gained from reflection."""
    id: str
    created_at: datetime
    
    insight_type: str  # "pattern", "anti_pattern", "improvement", "correlation"
    description: str
    confidence: float
    
    # Evidence
    supporting_outcomes: List[str] = field(default_factory=list)
    
    # Actions
    suggested_actions: List[str] = field(default_factory=list)
    applied: bool = False


class ReflectionSystem:
    """
    Reflects on outcomes to improve future performance.
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        from config import REFLECTIONS_DIR
        self.storage_path = Path(storage_path) if storage_path else REFLECTIONS_DIR
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self._outcomes: List[Outcome] = []
        self._insights: List[ReflectionInsight] = []
        self._load_history()
    
    def _load_history(self):
        """Load outcome history."""
        outcomes_file = self.storage_path / "outcomes.json"
        if outcomes_file.exists():
            try:
                with open(outcomes_file, 'r') as f:
                    data = json.load(f)
                    for o in data.get("outcomes", [])[-100:]:  # Keep last 100
                        self._outcomes.append(self._outcome_from_dict(o))
                    for i in data.get("insights", [])[-50:]:
                        self._insights.append(self._insight_from_dict(i))
            except Exception as e:
                logger.error(f"Failed to load reflection history: {e}")
        
        logger.info(f"Loaded {len(self._outcomes)} outcomes, {len(self._insights)} insights")
    
    def _save_history(self):
        """Save outcome history."""
        outcomes_file = self.storage_path / "outcomes.json"
        with open(outcomes_file, 'w') as f:
            json.dump({
                "outcomes": [self._outcome_to_dict(o) for o in self._outcomes[-100:]],
                "insights": [self._insight_to_dict(i) for i in self._insights[-50:]]
            }, f, indent=2)
    
    def _outcome_to_dict(self, o: Outcome) -> Dict:
        return {
            "id": o.id,
            "timestamp": o.timestamp.isoformat(),
            "task_description": o.task_description,
            "solution_applied": o.solution_applied,
            "skills_used": o.skills_used,
            "outcome_type": o.outcome_type.value,
            "feedback_source": o.feedback_source.value,
            "error_if_failed": o.error_if_failed,
            "success_indicators": o.success_indicators,
            "technologies": o.technologies,
            "file_paths": o.file_paths,
            "lessons_learned": o.lessons_learned,
            "should_create_skill": o.should_create_skill
        }
    
    def _outcome_from_dict(self, d: Dict) -> Outcome:
        return Outcome(
            id=d["id"],
            timestamp=datetime.fromisoformat(d["timestamp"]),
            task_description=d["task_description"],
            solution_applied=d["solution_applied"],
            skills_used=d.get("skills_used", []),
            outcome_type=OutcomeType(d.get("outcome_type", "unknown")),
            feedback_source=FeedbackSource(d.get("feedback_source", "inferred")),
            error_if_failed=d.get("error_if_failed"),
            success_indicators=d.get("success_indicators", []),
            technologies=d.get("technologies", []),
            file_paths=d.get("file_paths", []),
            lessons_learned=d.get("lessons_learned", []),
            should_create_skill=d.get("should_create_skill", False)
        )
    
    def _insight_to_dict(self, i: ReflectionInsight) -> Dict:
        return {
            "id": i.id,
            "created_at": i.created_at.isoformat(),
            "insight_type": i.insight_type,
            "description": i.description,
            "confidence": i.confidence,
            "supporting_outcomes": i.supporting_outcomes,
            "suggested_actions": i.suggested_actions,
            "applied": i.applied
        }
    
    def _insight_from_dict(self, d: Dict) -> ReflectionInsight:
        return ReflectionInsight(
            id=d["id"],
            created_at=datetime.fromisoformat(d["created_at"]),
            insight_type=d["insight_type"],
            description=d["description"],
            confidence=d["confidence"],
            supporting_outcomes=d.get("supporting_outcomes", []),
            suggested_actions=d.get("suggested_actions", []),
            applied=d.get("applied", False)
        )
    
    async def record_outcome(
        self,
        task_description: str,
        solution_applied: str,
        outcome_type: OutcomeType,
        feedback_source: FeedbackSource = FeedbackSource.INFERRED,
        skills_used: Optional[List[str]] = None,
        error_if_failed: Optional[str] = None,
        technologies: Optional[List[str]] = None,
        file_paths: Optional[List[str]] = None
    ) -> Outcome:
        """Record an outcome for reflection."""
        from bson import ObjectId
        
        outcome = Outcome(
            id=str(ObjectId()),
            timestamp=datetime.utcnow(),
            task_description=task_description,
            solution_applied=solution_applied,
            skills_used=skills_used or [],
            outcome_type=outcome_type,
            feedback_source=feedback_source,
            error_if_failed=error_if_failed,
            technologies=technologies or [],
            file_paths=file_paths or []
        )
        
        self._outcomes.append(outcome)
        
        # Update skill confidence if skills were used
        if skills_used:
            await self._update_skill_confidence(
                skills_used, 
                outcome_type == OutcomeType.SUCCESS
            )
        
        # Check if this should become a skill
        if outcome_type == OutcomeType.SUCCESS:
            outcome.should_create_skill = await self._should_create_skill(outcome)
        
        # AUTO SKILL LEARNING - silently process outcome for pattern detection
        await self._auto_learn_from_outcome(outcome)
        
        self._save_history()
        logger.info(f"Recorded outcome: {outcome_type.value} for {task_description[:50]}")
        
        return outcome
    
    async def _auto_learn_from_outcome(self, outcome: Outcome):
        """Silently feed outcome to auto skill learner for pattern detection."""
        try:
            from skills.auto_skill_learner import get_auto_skill_learner
            learner = get_auto_skill_learner()
            
            result = await learner.process_outcome(
                task_description=outcome.task_description,
                solution_applied=outcome.solution_applied,
                outcome_type=outcome.outcome_type.value,
                technologies=outcome.technologies,
                code=None  # Could extract from solution if present
            )
            
            if result:
                logger.info(f"AUTO-LEARNED: Created skill '{result.get('name')}' from pattern")
                outcome.lessons_learned.append(f"Auto-generated skill: {result.get('name')}")
        except Exception as e:
            # Silent failure - don't interrupt normal flow
            logger.debug(f"Auto skill learning skipped: {e}")
    
    async def _update_skill_confidence(self, skill_ids: List[str], successful: bool):
        """Update confidence for used skills."""
        try:
            from skills.skill_system import get_skill_store
            skill_store = get_skill_store()
            
            for skill_id in skill_ids:
                await skill_store.update_skill_usage(skill_id, successful)
        except Exception as e:
            logger.warning(f"Failed to update skill confidence: {e}")
    
    async def _should_create_skill(self, outcome: Outcome) -> bool:
        """Determine if a successful outcome should become a skill."""
        # Check if similar solutions have succeeded multiple times
        similar_count = 0
        for o in self._outcomes[-50:]:
            if (o.outcome_type == OutcomeType.SUCCESS and
                self._solutions_similar(o.solution_applied, outcome.solution_applied)):
                similar_count += 1
        
        # If we've done similar things 2+ times successfully, suggest skill
        return similar_count >= 2
    
    def _solutions_similar(self, sol1: str, sol2: str) -> bool:
        """Check if two solutions are similar."""
        # Simple word overlap check
        words1 = set(sol1.lower().split())
        words2 = set(sol2.lower().split())
        
        if not words1 or not words2:
            return False
        
        overlap = len(words1 & words2) / min(len(words1), len(words2))
        return overlap > 0.5
    
    async def reflect_on_recent(self, hours: int = 24) -> List[ReflectionInsight]:
        """
        Analyze recent outcomes and generate insights.
        """
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        recent = [o for o in self._outcomes if o.timestamp > cutoff]
        
        if len(recent) < 3:
            return []  # Need enough data
        
        insights = []
        
        # Analyze success rate by technology
        tech_outcomes = {}
        for o in recent:
            for tech in o.technologies:
                if tech not in tech_outcomes:
                    tech_outcomes[tech] = {"success": 0, "fail": 0}
                if o.outcome_type == OutcomeType.SUCCESS:
                    tech_outcomes[tech]["success"] += 1
                elif o.outcome_type == OutcomeType.FAILURE:
                    tech_outcomes[tech]["fail"] += 1
        
        # Generate insights for problematic technologies
        for tech, counts in tech_outcomes.items():
            total = counts["success"] + counts["fail"]
            if total >= 2 and counts["fail"] / total > 0.5:
                from bson import ObjectId
                insight = ReflectionInsight(
                    id=str(ObjectId()),
                    created_at=datetime.utcnow(),
                    insight_type="pattern",
                    description=f"High failure rate ({counts['fail']}/{total}) for {tech}-related tasks",
                    confidence=0.7,
                    supporting_outcomes=[o.id for o in recent if tech in o.technologies],
                    suggested_actions=[
                        f"Review {tech} documentation more carefully",
                        f"Consider searching for {tech} best practices before implementing"
                    ]
                )
                insights.append(insight)
        
        # Look for repeated failures with same error
        error_counts = {}
        for o in recent:
            if o.error_if_failed:
                error_key = o.error_if_failed[:100]
                if error_key not in error_counts:
                    error_counts[error_key] = []
                error_counts[error_key].append(o.id)
        
        for error, outcome_ids in error_counts.items():
            if len(outcome_ids) >= 2:
                from bson import ObjectId
                insight = ReflectionInsight(
                    id=str(ObjectId()),
                    created_at=datetime.utcnow(),
                    insight_type="anti_pattern",
                    description=f"Recurring error: {error[:80]}...",
                    confidence=0.8,
                    supporting_outcomes=outcome_ids,
                    suggested_actions=[
                        "Create a skill to handle this error pattern",
                        "Search knowledge graph for existing solutions"
                    ]
                )
                insights.append(insight)
        
        # Check for skills that need improvement
        skills_failing = {}
        for o in recent:
            if o.outcome_type == OutcomeType.FAILURE and o.skills_used:
                for skill_id in o.skills_used:
                    if skill_id not in skills_failing:
                        skills_failing[skill_id] = 0
                    skills_failing[skill_id] += 1
        
        for skill_id, fail_count in skills_failing.items():
            if fail_count >= 2:
                from bson import ObjectId
                insight = ReflectionInsight(
                    id=str(ObjectId()),
                    created_at=datetime.utcnow(),
                    insight_type="improvement",
                    description=f"Skill {skill_id} failed {fail_count} times recently",
                    confidence=0.75,
                    suggested_actions=[
                        f"Review and update skill {skill_id}",
                        "Consider creating an evolved version of this skill"
                    ]
                )
                insights.append(insight)
        
        # Save new insights
        self._insights.extend(insights)
        self._save_history()
        
        return insights
    
    async def get_relevant_insights(
        self,
        query: str,
        technologies: Optional[List[str]] = None
    ) -> List[ReflectionInsight]:
        """Get insights relevant to a query."""
        relevant = []
        query_lower = query.lower()
        
        for insight in self._insights[-20:]:
            # Check text relevance
            if any(word in insight.description.lower() for word in query_lower.split()):
                relevant.append(insight)
                continue
            
            # Check technology relevance
            if technologies:
                for tech in technologies:
                    if tech.lower() in insight.description.lower():
                        relevant.append(insight)
                        break
        
        return relevant
    
    async def record_user_feedback(
        self,
        outcome_id: str,
        was_helpful: bool,
        feedback_text: Optional[str] = None
    ) -> dict:
        """Record explicit user feedback on an outcome."""
        for outcome in self._outcomes:
            if outcome.id == outcome_id:
                outcome.feedback_source = FeedbackSource.USER_EXPLICIT
                outcome.outcome_type = OutcomeType.SUCCESS if was_helpful else OutcomeType.FAILURE
                
                if feedback_text:
                    outcome.lessons_learned.append(feedback_text)
                
                # Update skills based on explicit feedback
                if outcome.skills_used:
                    await self._update_skill_confidence(outcome.skills_used, was_helpful)
                
                self._save_history()
                break
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get reflection statistics."""
        if not self._outcomes:
            return {"total_outcomes": 0}
        
        success_count = sum(1 for o in self._outcomes if o.outcome_type == OutcomeType.SUCCESS)
        failure_count = sum(1 for o in self._outcomes if o.outcome_type == OutcomeType.FAILURE)
        
        # Technology breakdown
        tech_stats = {}
        for o in self._outcomes:
            for tech in o.technologies:
                if tech not in tech_stats:
                    tech_stats[tech] = {"success": 0, "failure": 0}
                if o.outcome_type == OutcomeType.SUCCESS:
                    tech_stats[tech]["success"] += 1
                elif o.outcome_type == OutcomeType.FAILURE:
                    tech_stats[tech]["failure"] += 1
        
        return {
            "total_outcomes": len(self._outcomes),
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": success_count / len(self._outcomes) if self._outcomes else 0,
            "insights_generated": len(self._insights),
            "technology_stats": tech_stats,
            "skills_suggested": sum(1 for o in self._outcomes if o.should_create_skill)
        }


# Singleton instance
_reflection_system: Optional[ReflectionSystem] = None


def get_reflection_system() -> ReflectionSystem:
    """Get or create the reflection system singleton."""
    global _reflection_system
    if _reflection_system is None:
        _reflection_system = ReflectionSystem()
    return _reflection_system
