"""
A/B Testing for Skills - Compare multiple matching skills.

When multiple skills match a problem:
1. Track which skill was used
2. Record outcome for each
3. Build statistical confidence
4. Recommend the better performer
"""

import logging
import random
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import json

logger = logging.getLogger(__name__)


@dataclass
class SkillExperiment:
    """An A/B test experiment between skills."""
    id: str
    query_pattern: str  # What type of query triggered this
    skill_ids: List[str]  # Skills being compared
    
    # Results per skill
    results: Dict[str, Dict[str, int]] = field(default_factory=dict)
    # Format: {skill_id: {"success": N, "failure": N, "total": N}}
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    # Experiment status
    concluded: bool = False
    winner_id: Optional[str] = None
    confidence: float = 0.0
    
    def record_result(self, skill_id: str, success: bool) -> dict:
        """Record a result for a skill in this experiment."""
        if skill_id not in self.results:
            self.results[skill_id] = {"success": 0, "failure": 0, "total": 0}
        
        self.results[skill_id]["total"] += 1
        if success:
            self.results[skill_id]["success"] += 1
        else:
            self.results[skill_id]["failure"] += 1
        
        self.last_updated = datetime.utcnow()
        self._check_conclusion()
    
    def _check_conclusion(self):
        """Check if experiment can be concluded."""
        min_samples = 5  # Minimum samples per skill
        
        # Need enough data
        for skill_id in self.skill_ids:
            if skill_id not in self.results:
                return
            if self.results[skill_id]["total"] < min_samples:
                return
        
        # Calculate success rates
        rates = {}
        for skill_id, data in self.results.items():
            if data["total"] > 0:
                rates[skill_id] = data["success"] / data["total"]
        
        if len(rates) < 2:
            return
        
        # Find best and second best
        sorted_skills = sorted(rates.items(), key=lambda x: -x[1])
        best_id, best_rate = sorted_skills[0]
        second_rate = sorted_skills[1][1] if len(sorted_skills) > 1 else 0
        
        # Conclude if clear winner (>15% difference with enough samples)
        if best_rate - second_rate > 0.15:
            total_samples = sum(d["total"] for d in self.results.values())
            if total_samples >= min_samples * len(self.skill_ids):
                self.concluded = True
                self.winner_id = best_id
                self.confidence = min(0.95, 0.5 + (best_rate - second_rate))
    
    def get_recommendation(self) -> Tuple[str, float]:
        """Get recommended skill and confidence."""
        if self.concluded and self.winner_id:
            return self.winner_id, self.confidence
        
        # Return skill with best current rate, lower confidence
        best_id = None
        best_rate = -1
        
        for skill_id, data in self.results.items():
            if data["total"] > 0:
                rate = data["success"] / data["total"]
                if rate > best_rate:
                    best_rate = rate
                    best_id = skill_id
        
        if best_id:
            return best_id, 0.5  # Lower confidence during experiment
        
        # No data yet, random selection
        return random.choice(self.skill_ids), 0.3


class SkillABTester:
    """Manages A/B testing of skills."""
    
    def __init__(self, storage_path: Optional[str] = None):
        from config import EXPERIMENTS_DIR
        self.storage_path = Path(storage_path) if storage_path else EXPERIMENTS_DIR
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._experiments: Dict[str, SkillExperiment] = {}
        self._load_experiments()
    
    def _load_experiments(self):
        """Load experiments from storage."""
        exp_file = self.storage_path / "experiments.json"
        if exp_file.exists():
            try:
                with open(exp_file, 'r') as f:
                    data = json.load(f)
                    for exp_data in data.get("experiments", []):
                        exp = SkillExperiment(
                            id=exp_data["id"],
                            query_pattern=exp_data["query_pattern"],
                            skill_ids=exp_data["skill_ids"],
                            results=exp_data.get("results", {}),
                            created_at=datetime.fromisoformat(exp_data["created_at"]),
                            last_updated=datetime.fromisoformat(exp_data["last_updated"]),
                            concluded=exp_data.get("concluded", False),
                            winner_id=exp_data.get("winner_id"),
                            confidence=exp_data.get("confidence", 0)
                        )
                        self._experiments[exp.id] = exp
            except Exception as e:
                logger.error(f"Failed to load experiments: {e}")
    
    def _save_experiments(self):
        """Save experiments to storage."""
        exp_file = self.storage_path / "experiments.json"
        data = {
            "experiments": [
                {
                    "id": exp.id,
                    "query_pattern": exp.query_pattern,
                    "skill_ids": exp.skill_ids,
                    "results": exp.results,
                    "created_at": exp.created_at.isoformat(),
                    "last_updated": exp.last_updated.isoformat(),
                    "concluded": exp.concluded,
                    "winner_id": exp.winner_id,
                    "confidence": exp.confidence
                }
                for exp in self._experiments.values()
            ]
        }
        with open(exp_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _get_query_pattern(self, query: str) -> str:
        """Extract a pattern from query for matching experiments."""
        # Normalize and extract key terms
        import re
        words = re.findall(r'\b\w{4,}\b', query.lower())
        # Keep top distinctive words
        key_words = sorted(set(words))[:5]
        return "|".join(key_words)
    
    def select_skill(
        self,
        matching_skills: List[Tuple[Any, float]],  # (Skill, score) pairs
        query: str
    ) -> Tuple[Any, str, bool]:
        """
        Select which skill to use from multiple matches.
        
        Returns: (selected_skill, experiment_id, is_experiment)
        """
        if len(matching_skills) <= 1:
            skill = matching_skills[0][0] if matching_skills else None
            return skill, "", False
        
        # Get skill IDs
        skill_ids = [s[0].id for s in matching_skills]
        skill_map = {s[0].id: s[0] for s in matching_skills}
        
        query_pattern = self._get_query_pattern(query)
        
        # Find existing experiment for similar queries
        experiment = None
        for exp in self._experiments.values():
            if exp.query_pattern == query_pattern and set(exp.skill_ids) == set(skill_ids):
                experiment = exp
                break
        
        # Create new experiment if none exists
        if not experiment:
            from bson import ObjectId
            experiment = SkillExperiment(
                id=str(ObjectId()),
                query_pattern=query_pattern,
                skill_ids=skill_ids
            )
            self._experiments[experiment.id] = experiment
            self._save_experiments()
        
        # If experiment concluded, return winner
        if experiment.concluded and experiment.winner_id:
            return skill_map.get(experiment.winner_id, matching_skills[0][0]), experiment.id, False
        
        # During experiment: weighted random based on current performance
        weights = []
        for skill_id in skill_ids:
            if skill_id in experiment.results and experiment.results[skill_id]["total"] > 0:
                rate = experiment.results[skill_id]["success"] / experiment.results[skill_id]["total"]
                weights.append(0.3 + rate * 0.7)  # Base weight + performance
            else:
                weights.append(0.5)  # Unknown, give fair chance
        
        # Normalize weights
        total = sum(weights)
        weights = [w / total for w in weights]
        
        # Weighted random selection
        selected_id = random.choices(skill_ids, weights=weights, k=1)[0]
        
        return skill_map[selected_id], experiment.id, True
    
    def record_outcome(self, experiment_id: str, skill_id: str, success: bool) -> dict:
        """Record the outcome of using a skill in an experiment."""
        if experiment_id not in self._experiments:
            return
        
        experiment = self._experiments[experiment_id]
        experiment.record_result(skill_id, success)
        self._save_experiments()
        
        if experiment.concluded:
            logger.info(
                f"Experiment {experiment_id} concluded: "
                f"winner={experiment.winner_id}, confidence={experiment.confidence:.2f}"
            )
    
    def get_experiment_stats(self) -> Dict[str, Any]:
        """Get statistics on all experiments."""
        total = len(self._experiments)
        concluded = sum(1 for e in self._experiments.values() if e.concluded)
        
        return {
            "total_experiments": total,
            "concluded": concluded,
            "active": total - concluded,
            "experiments": [
                {
                    "id": exp.id,
                    "skills": len(exp.skill_ids),
                    "total_trials": sum(d["total"] for d in exp.results.values()),
                    "concluded": exp.concluded,
                    "winner": exp.winner_id
                }
                for exp in list(self._experiments.values())[-10:]
            ]
        }


# Singleton
_ab_tester: Optional[SkillABTester] = None


def get_skill_ab_tester() -> SkillABTester:
    """Get or create A/B tester singleton."""
    global _ab_tester
    if _ab_tester is None:
        _ab_tester = SkillABTester()
    return _ab_tester
