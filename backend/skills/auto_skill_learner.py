"""
Automatic Skill Learner - Silent skill generation from repeated successes.

Based on cutting-edge research (EXIF framework):
- Retrospective skill generation from successful outcomes
- Closed-loop feedback - outcomes automatically feed into skill creation
- Self-evolving without human intervention
- Similarity detection for repeated patterns

This runs automatically when outcomes are recorded - no explicit user action needed.
"""

import logging
import re
import asyncio
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import hashlib

logger = logging.getLogger(__name__)


@dataclass
class PatternCluster:
    """A cluster of similar successful outcomes."""
    pattern_hash: str
    keywords: List[str]
    outcomes: List[Dict[str, Any]]
    technologies: List[str]
    first_seen: datetime
    last_seen: datetime
    success_count: int = 0
    failure_count: int = 0
    skill_generated: bool = False
    skill_id: Optional[str] = None


class AutoSkillLearner:
    """
    Automatically learns and creates skills from repeated successful outcomes.
    
    Key design principles:
    1. SILENT - No user intervention required
    2. SAFE - Only creates skills after multiple successes (threshold: 3)
    3. SMART - Uses similarity detection to cluster related outcomes
    4. ADAPTIVE - Adjusts thresholds based on overall success rate
    """
    
    # Thresholds (can be tuned)
    MIN_SUCCESSES_FOR_SKILL = 3  # Need N successes before auto-creating
    MIN_SUCCESS_RATE = 0.7  # 70% success rate required
    SIMILARITY_THRESHOLD = 0.4  # How similar outcomes must be to cluster
    MAX_SKILL_GENERATION_PER_HOUR = 5  # Rate limit
    
    def __init__(self):
        self._pattern_clusters: Dict[str, PatternCluster] = {}
        self._skills_generated_timestamps: List[datetime] = []
        self._running = False
        self._lock = asyncio.Lock()
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from text."""
        # Common stop words to ignore
        stop_words = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'must', 'to', 'of', 'in', 'for', 'on',
            'with', 'at', 'by', 'from', 'as', 'into', 'through', 'and', 'but',
            'or', 'not', 'this', 'that', 'it', 'its', 'i', 'you', 'we', 'they',
            'how', 'what', 'when', 'where', 'why', 'which', 'who', 'fix', 'error',
            'problem', 'issue', 'solution', 'using', 'use', 'used', 'add', 'added'
        }
        
        # Extract words (3+ chars)
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        keywords = [w for w in words if w not in stop_words]
        
        # Also extract technical identifiers (camelCase, PascalCase)
        identifiers = re.findall(r'\b[A-Z][a-z]+[A-Z]\w*\b', text)
        keywords.extend([i.lower() for i in identifiers])
        
        # Extract error types
        error_types = re.findall(r'\b\w*(?:Error|Exception|Warning|Failure)\b', text)
        keywords.extend([e.lower() for e in error_types])
        
        return list(set(keywords))
    
    def _compute_pattern_hash(self, keywords: List[str], technologies: List[str]) -> str:
        """Compute a hash for pattern clustering."""
        # Sort and combine for consistent hashing
        combined = sorted(set(keywords[:10])) + sorted(set(technologies))
        text = "|".join(combined)
        return hashlib.md5(text.encode()).hexdigest()[:12]
    
    def _calculate_similarity(self, kw1: List[str], kw2: List[str]) -> float:
        """Calculate Jaccard similarity between keyword sets."""
        set1, set2 = set(kw1), set(kw2)
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0
    
    def _find_matching_cluster(
        self,
        keywords: List[str],
        technologies: List[str]
    ) -> Optional[str]:
        """Find existing cluster that matches these keywords."""
        for pattern_hash, cluster in self._pattern_clusters.items():
            similarity = self._calculate_similarity(keywords, cluster.keywords)
            tech_overlap = len(set(technologies) & set(cluster.technologies))
            
            # Match if keywords similar OR same technologies with some keyword overlap
            if similarity >= self.SIMILARITY_THRESHOLD:
                return pattern_hash
            if tech_overlap > 0 and similarity >= 0.2:
                return pattern_hash
        
        return None
    
    def _can_generate_skill(self) -> bool:
        """Check rate limiting for skill generation."""
        now = datetime.utcnow()
        hour_ago = now - timedelta(hours=1)
        
        # Clean old timestamps
        self._skills_generated_timestamps = [
            ts for ts in self._skills_generated_timestamps if ts > hour_ago
        ]
        
        return len(self._skills_generated_timestamps) < self.MAX_SKILL_GENERATION_PER_HOUR
    
    async def process_outcome(
        self,
        task_description: str,
        solution_applied: str,
        outcome_type: str,  # "success", "partial_success", "failure"
        technologies: List[str],
        code: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Process an outcome and potentially auto-generate a skill.
        
        This is the main entry point - called automatically when outcomes are recorded.
        Returns skill info if one was auto-generated, None otherwise.
        """
        async with self._lock:
            # Extract keywords from task and solution
            all_text = f"{task_description} {solution_applied}"
            keywords = self._extract_keywords(all_text)
            
            if len(keywords) < 3:
                return None  # Not enough signal
            
            # Find or create pattern cluster
            cluster_hash = self._find_matching_cluster(keywords, technologies)
            
            if cluster_hash is None:
                # Create new cluster
                cluster_hash = self._compute_pattern_hash(keywords, technologies)
                self._pattern_clusters[cluster_hash] = PatternCluster(
                    pattern_hash=cluster_hash,
                    keywords=keywords,
                    outcomes=[],
                    technologies=list(technologies),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow()
                )
            
            cluster = self._pattern_clusters[cluster_hash]
            
            # Update cluster
            cluster.last_seen = datetime.utcnow()
            cluster.keywords = list(set(cluster.keywords + keywords))[:20]  # Keep top 20
            cluster.technologies = list(set(cluster.technologies + technologies))
            
            # Record outcome
            outcome_record = {
                "task": task_description,
                "solution": solution_applied,
                "code": code,
                "outcome": outcome_type,
                "timestamp": datetime.utcnow().isoformat()
            }
            cluster.outcomes.append(outcome_record)
            
            # Keep only last 10 outcomes per cluster
            if len(cluster.outcomes) > 10:
                cluster.outcomes = cluster.outcomes[-10:]
            
            # Update counts
            if outcome_type == "success":
                cluster.success_count += 1
            elif outcome_type == "failure":
                cluster.failure_count += 1
            
            # Check if we should auto-generate a skill
            skill_result = await self._maybe_generate_skill(cluster)
            
            return skill_result
    
    async def _maybe_generate_skill(self, cluster: PatternCluster) -> Optional[Dict[str, Any]]:
        """
        Check if cluster meets criteria and generate skill if so.
        """
        # Already generated?
        if cluster.skill_generated:
            return None
        
        # Enough successes?
        if cluster.success_count < self.MIN_SUCCESSES_FOR_SKILL:
            return None
        
        # Good success rate?
        total = cluster.success_count + cluster.failure_count
        if total > 0:
            success_rate = cluster.success_count / total
            if success_rate < self.MIN_SUCCESS_RATE:
                logger.debug(f"Cluster {cluster.pattern_hash} success rate too low: {success_rate:.2f}")
                return None
        
        # Rate limiting
        if not self._can_generate_skill():
            logger.debug("Rate limit reached for skill generation")
            return None
        
        # Generate the skill!
        try:
            skill_info = await self._generate_skill_from_cluster(cluster)
            if skill_info:
                cluster.skill_generated = True
                cluster.skill_id = skill_info.get("skill_id")
                self._skills_generated_timestamps.append(datetime.utcnow())
                
                logger.info(
                    f"AUTO-GENERATED skill '{skill_info.get('name')}' from "
                    f"{cluster.success_count} successes (pattern: {cluster.pattern_hash})"
                )
                
                return skill_info
        except Exception as e:
            logger.error(f"Auto skill generation failed: {e}")
        
        return None
    
    async def _generate_skill_from_cluster(self, cluster: PatternCluster) -> Optional[Dict[str, Any]]:
        """Generate a skill from a pattern cluster."""
        
        # Get the best outcome (most recent success with code)
        best_outcome = None
        for outcome in reversed(cluster.outcomes):
            if outcome["outcome"] == "success":
                best_outcome = outcome
                if outcome.get("code"):
                    break  # Prefer outcomes with code
        
        if not best_outcome:
            return None
        
        # Try LLM generation first
        try:
            from skills.skill_generator import get_skill_generator
            generator = get_skill_generator()
            
            candidate = await generator.generate_skill_from_outcome(
                problem=best_outcome["task"],
                solution=best_outcome["solution"],
                code=best_outcome.get("code"),
                technologies=cluster.technologies
            )
            
            if candidate:
                # Save the skill
                from skills.skill_system import get_skill_store, Skill, SkillCategory
                from bson import ObjectId
                
                skill_store = get_skill_store()
                
                skill = Skill(
                    id=str(ObjectId()),
                    name=candidate.name,
                    description=candidate.description,
                    category=SkillCategory.ERROR_FIX,
                    triggers=candidate.triggers,
                    solution_text=candidate.solution_text,
                    code_template=candidate.code_template,
                    technologies=candidate.technologies,
                    confidence=min(0.8, candidate.confidence + 0.1),  # Boost for auto-generated
                    user_id="auto_learner"
                )
                
                await skill_store.add_skill(skill)
                
                return {
                    "skill_id": skill.id,
                    "name": skill.name,
                    "triggers": skill.triggers,
                    "confidence": skill.confidence,
                    "source": "llm_generated",
                    "based_on_successes": cluster.success_count
                }
        
        except Exception as e:
            logger.warning(f"LLM skill generation failed, using heuristic: {e}")
        
        # Fallback: heuristic generation
        return await self._generate_skill_heuristically(cluster, best_outcome)
    
    async def _generate_skill_heuristically(
        self,
        cluster: PatternCluster,
        best_outcome: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Generate skill using heuristics when LLM unavailable."""
        
        # Build triggers from keywords
        triggers = []
        for kw in cluster.keywords[:5]:
            if len(kw) >= 4:
                triggers.append(re.escape(kw))
        
        if not triggers:
            return None
        
        # Generate name
        name_parts = [kw.title() for kw in cluster.keywords[:3] if len(kw) >= 4]
        name = " ".join(name_parts) + " Fix" if name_parts else "Auto-learned Pattern"
        
        try:
            from skills.skill_system import get_skill_store, Skill, SkillCategory
            from bson import ObjectId
            
            skill_store = get_skill_store()
            
            skill = Skill(
                id=str(ObjectId()),
                name=name[:50],
                description=f"Auto-learned from {cluster.success_count} successful outcomes",
                category=SkillCategory.PATTERN,
                triggers=triggers,
                solution_text=best_outcome["solution"],
                code_template=best_outcome.get("code"),
                technologies=cluster.technologies,
                confidence=0.6,  # Lower confidence for heuristic
                user_id="auto_learner"
            )
            
            await skill_store.add_skill(skill)
            
            return {
                "skill_id": skill.id,
                "name": skill.name,
                "triggers": triggers,
                "confidence": 0.6,
                "source": "heuristic_generated",
                "based_on_successes": cluster.success_count
            }
        
        except Exception as e:
            logger.error(f"Heuristic skill generation failed: {e}")
            return None
    
    def get_learning_status(self) -> Dict[str, Any]:
        """Get current learning status."""
        total_clusters = len(self._pattern_clusters)
        skills_generated = sum(1 for c in self._pattern_clusters.values() if c.skill_generated)
        pending = sum(
            1 for c in self._pattern_clusters.values() 
            if not c.skill_generated and c.success_count >= 2
        )
        
        return {
            "total_pattern_clusters": total_clusters,
            "skills_auto_generated": skills_generated,
            "pending_skill_candidates": pending,
            "generation_rate_limit": f"{len(self._skills_generated_timestamps)}/{self.MAX_SKILL_GENERATION_PER_HOUR} per hour",
            "thresholds": {
                "min_successes": self.MIN_SUCCESSES_FOR_SKILL,
                "min_success_rate": self.MIN_SUCCESS_RATE,
                "similarity_threshold": self.SIMILARITY_THRESHOLD
            }
        }


# Singleton
_auto_learner: Optional[AutoSkillLearner] = None


def get_auto_skill_learner() -> AutoSkillLearner:
    """Get or create the auto skill learner singleton."""
    global _auto_learner
    if _auto_learner is None:
        _auto_learner = AutoSkillLearner()
    return _auto_learner
