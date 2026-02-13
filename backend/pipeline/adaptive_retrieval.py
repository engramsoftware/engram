"""
Adaptive Retrieval System - Only inject context when the LLM needs it.

Approach:
- Analyze query complexity and knowledge requirements
- Decide whether to retrieve external context
- Avoid context pollution for simple queries
- LEARNS from past outcomes to improve recommendations

This reduces latency and prevents hallucinations from irrelevant context.
"""

import logging
import re
import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)

# Path to retrieval learning data
from config import LEARNING_DIR
LEARNING_DATA_PATH = LEARNING_DIR / "retrieval_learning.json"


class QueryComplexity(str, Enum):
    """Query complexity levels."""
    SIMPLE = "simple"          # Greeting, basic questions
    MODERATE = "moderate"      # Factual questions, basic code
    COMPLEX = "complex"        # Multi-step, debugging, architecture
    SPECIALIZED = "specialized"  # Domain-specific, advanced patterns


class RetrievalDecision(str, Enum):
    """What types of retrieval to perform."""
    NONE = "none"              # No retrieval needed
    MEMORY_ONLY = "memory"     # Just user memories
    GRAPH_ONLY = "graph"       # Just knowledge graph
    SEARCH_ONLY = "search"     # Just vector search
    HYBRID = "hybrid"          # All sources
    WEB = "web"                # External web search


@dataclass
class RetrievalPlan:
    """Plan for what context to retrieve."""
    decision: RetrievalDecision
    complexity: QueryComplexity
    confidence: float
    reasoning: str
    max_results: int = 5
    search_queries: List[str] = None
    
    def __post_init__(self):
        if self.search_queries is None:
            self.search_queries = []


class AdaptiveRetrieval:
    """
    Determines when and what context to retrieve based on query analysis.
    
    Uses heuristics + optional LLM to:
    1. Classify query complexity
    2. Detect knowledge gaps
    3. Choose retrieval strategy
    4. Optimize context size
    """
    
    # Patterns indicating different query types
    SIMPLE_PATTERNS = [
        r"^(hi|hello|hey|thanks|thank you|ok|okay|sure|yes|no)[\s!.?]*$",
        r"^(what is your name|who are you|how are you)",
        r"^(bye|goodbye|see you)",
    ]
    
    CODE_PATTERNS = [
        r"```[\w]*\n",                    # Code blocks
        r"def\s+\w+\s*\(",                # Python functions
        r"function\s+\w+\s*\(",           # JS functions
        r"class\s+\w+",                   # Class definitions
        r"\w+Error|\w+Exception",         # Errors
        r"import\s+\w+|from\s+\w+\s+import",  # Imports
    ]
    
    DEBUGGING_PATTERNS = [
        r"error|exception|bug|issue|problem|broken|doesn't work|not working",
        r"fix|debug|solve|help|stuck|confused",
        r"why (is|does|doesn't|isn't)",
        r"traceback|stack trace",
    ]
    
    ARCHITECTURE_PATTERNS = [
        r"how (should|do|can) I (design|architect|structure|organize)",
        r"best (practice|way|approach|pattern)",
        r"trade-?off|pros? and cons?|comparison|vs\.?|versus",
        r"should I use|which (is|should|would) (be )?(better|best)",
    ]
    
    MEMORY_TRIGGER_PATTERNS = [
        r"(remember|recall|last time|previously|before|earlier)",
        r"(my|our) (preference|project|code|setup|config)",
        r"(as I|like I) (said|mentioned|told)",
        r"(what|how) did (I|we)",
    ]
    
    EXTERNAL_KNOWLEDGE_PATTERNS = [
        r"(latest|newest|recent|current|2024|2025)",
        r"(documentation|docs|api|reference)",
        r"(how to|tutorial|guide|example)",
        r"(library|package|framework|tool) (called|named)",
    ]
    
    COMPLEXITY_PROMPT = """Analyze this query and determine the retrieval strategy.

Query: {query}

Consider:
1. Is this a simple greeting/acknowledgment? (no retrieval needed)
2. Does it reference past conversations or user preferences? (memory needed)
3. Does it involve code, errors, or technical concepts? (graph + search needed)
4. Does it ask about best practices or comparisons? (might need web search)
5. Is the information likely in training data or needs external lookup?

Respond in JSON:
{{
    "complexity": "simple|moderate|complex|specialized",
    "retrieval": "none|memory|graph|search|hybrid|web",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "search_queries": ["optimized", "search", "terms"]
}}"""

    def __init__(self, llm_provider=None):
        """
        Initialize adaptive retrieval.
        
        Args:
            llm_provider: Optional LLM for complex analysis
        """
        self.llm_provider = llm_provider
        self._compile_patterns()
        self._learning_data = self._load_learning_data()
    
    def _load_learning_data(self) -> Dict[str, Any]:
        """Load learning data from past outcomes."""
        try:
            if LEARNING_DATA_PATH.exists():
                with open(LEARNING_DATA_PATH, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.debug(f"Could not load retrieval learning data: {e}")
        
        return {
            "strategy_outcomes": {},  # strategy -> {success: X, failure: Y}
            "technology_strategies": {},  # tech -> best strategy
            "keyword_boosts": {},  # keyword -> strategy that worked
            "total_outcomes": 0
        }
    
    def _save_learning_data(self):
        """Save learning data."""
        try:
            LEARNING_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(LEARNING_DATA_PATH, 'w') as f:
                json.dump(self._learning_data, f, indent=2)
        except Exception as e:
            logger.debug(f"Could not save retrieval learning data: {e}")
    
    def record_outcome(self, query: str, strategy_used: str, successful: bool, technologies: List[str] = None) -> dict:
        """
        Record outcome to improve future recommendations.
        
        Called after a task completes to learn what strategies worked.
        """
        technologies = technologies or []
        
        # Update strategy outcomes
        if strategy_used not in self._learning_data["strategy_outcomes"]:
            self._learning_data["strategy_outcomes"][strategy_used] = {"success": 0, "failure": 0}
        
        if successful:
            self._learning_data["strategy_outcomes"][strategy_used]["success"] += 1
        else:
            self._learning_data["strategy_outcomes"][strategy_used]["failure"] += 1
        
        # Update technology preferences
        for tech in technologies:
            tech_lower = tech.lower()
            if successful:
                if tech_lower not in self._learning_data["technology_strategies"]:
                    self._learning_data["technology_strategies"][tech_lower] = {}
                
                if strategy_used not in self._learning_data["technology_strategies"][tech_lower]:
                    self._learning_data["technology_strategies"][tech_lower][strategy_used] = 0
                self._learning_data["technology_strategies"][tech_lower][strategy_used] += 1
        
        # Extract keywords and boost successful strategies
        if successful:
            keywords = self._extract_search_terms(query)[:5]
            for kw in keywords:
                if kw not in self._learning_data["keyword_boosts"]:
                    self._learning_data["keyword_boosts"][kw] = {}
                if strategy_used not in self._learning_data["keyword_boosts"][kw]:
                    self._learning_data["keyword_boosts"][kw][strategy_used] = 0
                self._learning_data["keyword_boosts"][kw][strategy_used] += 1
        
        self._learning_data["total_outcomes"] += 1
        self._save_learning_data()
    
    def _get_learned_strategy_boost(self, query: str, technologies: List[str] = None) -> Dict[str, float]:
        """
        Get strategy boosts based on past learning.
        
        Returns dict of strategy -> boost value (0.0 to 0.3)
        """
        boosts = {}
        technologies = technologies or []
        
        # Boost from technology preferences
        for tech in technologies:
            tech_lower = tech.lower()
            if tech_lower in self._learning_data["technology_strategies"]:
                for strategy, count in self._learning_data["technology_strategies"][tech_lower].items():
                    if strategy not in boosts:
                        boosts[strategy] = 0
                    boosts[strategy] += min(0.1, count * 0.02)
        
        # Boost from keywords
        keywords = self._extract_search_terms(query)[:5]
        for kw in keywords:
            if kw in self._learning_data["keyword_boosts"]:
                for strategy, count in self._learning_data["keyword_boosts"][kw].items():
                    if strategy not in boosts:
                        boosts[strategy] = 0
                    boosts[strategy] += min(0.1, count * 0.02)
        
        # Normalize boosts to max 0.3
        if boosts:
            max_boost = max(boosts.values())
            if max_boost > 0.3:
                for k in boosts:
                    boosts[k] = (boosts[k] / max_boost) * 0.3
        
        return boosts
    
    def get_learning_stats(self) -> Dict[str, Any]:
        """Get statistics about what the system has learned."""
        stats = {
            "total_outcomes_recorded": self._learning_data["total_outcomes"],
            "strategy_success_rates": {},
            "top_technology_strategies": {},
            "learning_active": self._learning_data["total_outcomes"] > 0
        }
        
        # Calculate success rates
        for strategy, outcomes in self._learning_data["strategy_outcomes"].items():
            total = outcomes["success"] + outcomes["failure"]
            if total > 0:
                stats["strategy_success_rates"][strategy] = {
                    "success_rate": round(outcomes["success"] / total, 2),
                    "total_uses": total
                }
        
        # Get best strategy per technology
        for tech, strategies in self._learning_data["technology_strategies"].items():
            if strategies:
                best = max(strategies.items(), key=lambda x: x[1])
                stats["top_technology_strategies"][tech] = best[0]
        
        return stats
    
    def _compile_patterns(self):
        """Pre-compile regex patterns for efficiency."""
        self._simple_re = [re.compile(p, re.IGNORECASE) for p in self.SIMPLE_PATTERNS]
        self._code_re = [re.compile(p, re.IGNORECASE) for p in self.CODE_PATTERNS]
        self._debug_re = [re.compile(p, re.IGNORECASE) for p in self.DEBUGGING_PATTERNS]
        self._arch_re = [re.compile(p, re.IGNORECASE) for p in self.ARCHITECTURE_PATTERNS]
        self._memory_re = [re.compile(p, re.IGNORECASE) for p in self.MEMORY_TRIGGER_PATTERNS]
        self._external_re = [re.compile(p, re.IGNORECASE) for p in self.EXTERNAL_KNOWLEDGE_PATTERNS]
    
    def analyze_query(self, query: str, context: Dict[str, Any] = None, technologies: List[str] = None) -> RetrievalPlan:
        """
        Analyze query and determine retrieval strategy using heuristics + learning.
        
        Args:
            query: User's query text
            context: Optional context (conversation history, user info)
            technologies: Optional list of technologies for learning-based boosts
            
        Returns:
            RetrievalPlan with retrieval decision
        """
        context = context or {}
        technologies = technologies or []
        
        # Extract technologies from query if not provided
        if not technologies:
            technologies = self._extract_technologies(query)
        
        # Check for simple queries first
        if self._is_simple_query(query):
            return RetrievalPlan(
                decision=RetrievalDecision.NONE,
                complexity=QueryComplexity.SIMPLE,
                confidence=0.95,
                reasoning="Simple greeting or acknowledgment"
            )
        
        # Score different aspects
        code_score = self._score_patterns(query, self._code_re)
        debug_score = self._score_patterns(query, self._debug_re)
        arch_score = self._score_patterns(query, self._arch_re)
        memory_score = self._score_patterns(query, self._memory_re)
        external_score = self._score_patterns(query, self._external_re)
        
        # Determine complexity
        total_score = code_score + debug_score + arch_score
        if total_score >= 3:
            complexity = QueryComplexity.COMPLEX
        elif total_score >= 1:
            complexity = QueryComplexity.MODERATE
        else:
            complexity = QueryComplexity.SIMPLE
        
        # Handle specialized domain queries
        if arch_score >= 2 or external_score >= 2:
            complexity = QueryComplexity.SPECIALIZED
        
        # Determine retrieval strategy (base heuristics)
        decision, reasoning = self._determine_retrieval(
            code_score, debug_score, arch_score, memory_score, external_score
        )
        
        # ADAPTIVE: Apply learning-based adjustments
        learned_boosts = self._get_learned_strategy_boost(query, technologies)
        if learned_boosts:
            best_learned = max(learned_boosts.items(), key=lambda x: x[1])
            if best_learned[1] > 0.15:  # Significant learning signal
                try:
                    learned_decision = RetrievalDecision(best_learned[0])
                    if learned_decision != decision:
                        reasoning = f"Adaptive: {reasoning} → Learned '{best_learned[0]}' works better for similar queries"
                        decision = learned_decision
                except ValueError:
                    pass  # Invalid strategy name, keep original
        
        # Generate optimized search queries
        search_queries = self._extract_search_terms(query)
        
        # Calculate confidence based on pattern match strength + learning
        base_confidence = min(0.9, 0.5 + (total_score * 0.1) + (memory_score * 0.1))
        learning_boost = max(learned_boosts.values()) if learned_boosts else 0
        confidence = min(0.95, base_confidence + learning_boost)
        
        return RetrievalPlan(
            decision=decision,
            complexity=complexity,
            confidence=confidence,
            reasoning=reasoning,
            max_results=self._determine_max_results(complexity),
            search_queries=search_queries
        )
    
    def _extract_technologies(self, query: str) -> List[str]:
        """Extract technology names from query."""
        tech_patterns = [
            'python', 'javascript', 'typescript', 'react', 'vue', 'angular',
            'fastapi', 'flask', 'django', 'express', 'node', 'mongodb', 'postgres',
            'sqlite', 'redis', 'docker', 'kubernetes', 'aws', 'graphql', 'tailwind'
        ]
        found = []
        query_lower = query.lower()
        for tech in tech_patterns:
            if tech in query_lower:
                found.append(tech)
        return found
    
    async def analyze_query_llm(self, query: str) -> RetrievalPlan:
        """
        Use LLM for more sophisticated query analysis.
        
        Falls back to heuristic analysis if LLM unavailable.
        """
        if not self.llm_provider:
            return self.analyze_query(query)
        
        try:
            import json
            
            prompt = self.COMPLEXITY_PROMPT.format(query=query[:1000])
            response = await self.llm_provider.generate(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300
            )
            
            result = json.loads(response.content)
            
            return RetrievalPlan(
                decision=RetrievalDecision(result.get("retrieval", "hybrid")),
                complexity=QueryComplexity(result.get("complexity", "moderate")),
                confidence=float(result.get("confidence", 0.7)),
                reasoning=result.get("reasoning", "LLM analysis"),
                search_queries=result.get("search_queries", [])
            )
            
        except Exception as e:
            logger.debug(f"LLM query analysis failed: {e}, using heuristics")
            return self.analyze_query(query)
    
    def _is_simple_query(self, query: str) -> bool:
        """Check if query is a simple greeting/acknowledgment."""
        query_clean = query.strip().lower()
        
        # Very short queries are often simple
        if len(query_clean) < 15:
            for pattern in self._simple_re:
                if pattern.match(query_clean):
                    return True
        
        return False
    
    def _score_patterns(self, text: str, patterns: List[re.Pattern]) -> int:
        """Count how many patterns match in the text."""
        score = 0
        for pattern in patterns:
            if pattern.search(text):
                score += 1
        return score
    
    def _determine_retrieval(
        self,
        code_score: int,
        debug_score: int,
        arch_score: int,
        memory_score: int,
        external_score: int
    ) -> Tuple[RetrievalDecision, str]:
        """Determine retrieval strategy based on scores."""
        
        # Memory-focused query
        if memory_score >= 2 and code_score < 2:
            return RetrievalDecision.MEMORY_ONLY, "Query references past context or preferences"
        
        # Architecture/best practices - might need web
        if arch_score >= 2 or external_score >= 2:
            return RetrievalDecision.HYBRID, "Architecture or best practices query needs comprehensive context"
        
        # Debugging query - needs graph + search
        if debug_score >= 2:
            return RetrievalDecision.HYBRID, "Debugging query benefits from related context"
        
        # Code query - graph for relationships
        if code_score >= 2:
            return RetrievalDecision.GRAPH_ONLY, "Code query can use knowledge graph relationships"
        
        # Mixed signals - use hybrid
        if code_score + debug_score + arch_score >= 2:
            return RetrievalDecision.HYBRID, "Complex query warrants hybrid retrieval"
        
        # Moderate query - just search
        if code_score + debug_score >= 1:
            return RetrievalDecision.SEARCH_ONLY, "Moderate query uses vector search"
        
        # Default to memory for context
        if memory_score >= 1:
            return RetrievalDecision.MEMORY_ONLY, "Light context from memories"
        
        return RetrievalDecision.NONE, "Simple query doesn't need retrieval"
    
    def _determine_max_results(self, complexity: QueryComplexity) -> int:
        """Determine how many results to retrieve based on complexity."""
        return {
            QueryComplexity.SIMPLE: 0,
            QueryComplexity.MODERATE: 3,
            QueryComplexity.COMPLEX: 5,
            QueryComplexity.SPECIALIZED: 8,
        }.get(complexity, 5)
    
    def _extract_search_terms(self, query: str) -> List[str]:
        """Extract optimized search terms from query."""
        # Remove common words
        stopwords = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'must', 'can', 'this', 'that', 'these',
            'those', 'i', 'you', 'he', 'she', 'it', 'we', 'they', 'what', 'which',
            'who', 'how', 'when', 'where', 'why', 'if', 'then', 'else', 'please',
            'help', 'me', 'my', 'your', 'want', 'need', 'like', 'get', 'make'
        }
        
        # Extract words, preserving technical terms
        words = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', query.lower())
        
        # Filter and dedupe
        terms = []
        seen = set()
        for word in words:
            if word not in stopwords and word not in seen and len(word) > 2:
                terms.append(word)
                seen.add(word)
        
        # Also extract quoted strings
        quoted = re.findall(r'"([^"]+)"', query)
        terms.extend(quoted)
        
        return terms[:10]  # Limit to 10 terms
    
    def should_retrieve(self, plan: RetrievalPlan) -> bool:
        """Quick check if any retrieval should happen."""
        return plan.decision != RetrievalDecision.NONE
    
    def get_retrieval_sources(self, plan: RetrievalPlan) -> Dict[str, bool]:
        """Get which sources to query based on the plan."""
        sources = {
            "memory": False,
            "graph": False,
            "search": False,
            "web": False
        }
        
        if plan.decision == RetrievalDecision.NONE:
            return sources
        elif plan.decision == RetrievalDecision.MEMORY_ONLY:
            sources["memory"] = True
        elif plan.decision == RetrievalDecision.GRAPH_ONLY:
            sources["graph"] = True
        elif plan.decision == RetrievalDecision.SEARCH_ONLY:
            sources["search"] = True
        elif plan.decision == RetrievalDecision.HYBRID:
            sources["memory"] = True
            sources["graph"] = True
            sources["search"] = True
        elif plan.decision == RetrievalDecision.WEB:
            sources["web"] = True
            sources["search"] = True
        
        return sources


# Convenience function
def should_inject_context(query: str) -> Tuple[bool, RetrievalPlan]:
    """
    Quick check if context should be injected for a query.
    
    Returns:
        Tuple of (should_inject, retrieval_plan)
    """
    retrieval = AdaptiveRetrieval()
    plan = retrieval.analyze_query(query)
    return retrieval.should_retrieve(plan), plan
