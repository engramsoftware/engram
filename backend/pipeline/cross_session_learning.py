"""
Cross-Session Learning - Link related sessions automatically.

Enables:
1. Detecting similar sessions across time
2. Linking related sessions for context
3. Learning from past session outcomes
4. Suggesting relevant past sessions when starting new ones
"""

import logging
import re
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import json

logger = logging.getLogger(__name__)


@dataclass
class SessionLink:
    """A link between two sessions."""
    from_session_id: str
    to_session_id: str
    link_type: str  # "similar_task", "continuation", "related_tech", "same_files"
    similarity_score: float
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SessionCluster:
    """A cluster of related sessions."""
    id: str
    name: str
    session_ids: List[str]
    technologies: List[str]
    common_patterns: List[str]
    success_rate: float
    created_at: datetime = field(default_factory=datetime.utcnow)


class CrossSessionLearner:
    """
    Learns patterns across sessions and links related ones.
    """
    
    def __init__(self, storage_path: Optional[str] = None):
        from config import SESSION_LINKS_DIR
        self.storage_path = Path(storage_path) if storage_path else SESSION_LINKS_DIR
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._links: List[SessionLink] = []
        self._clusters: Dict[str, SessionCluster] = {}
        self._load_data()
    
    def _load_data(self):
        """Load links and clusters from storage."""
        links_file = self.storage_path / "links.json"
        if links_file.exists():
            try:
                with open(links_file, 'r') as f:
                    data = json.load(f)
                    for link_data in data.get("links", []):
                        self._links.append(SessionLink(
                            from_session_id=link_data["from_session_id"],
                            to_session_id=link_data["to_session_id"],
                            link_type=link_data["link_type"],
                            similarity_score=link_data["similarity_score"],
                            created_at=datetime.fromisoformat(link_data["created_at"])
                        ))
                    for cluster_data in data.get("clusters", {}).values():
                        cluster = SessionCluster(
                            id=cluster_data["id"],
                            name=cluster_data["name"],
                            session_ids=cluster_data["session_ids"],
                            technologies=cluster_data["technologies"],
                            common_patterns=cluster_data["common_patterns"],
                            success_rate=cluster_data["success_rate"],
                            created_at=datetime.fromisoformat(cluster_data["created_at"])
                        )
                        self._clusters[cluster.id] = cluster
            except Exception as e:
                logger.error(f"Failed to load session links: {e}")
    
    def _save_data(self):
        """Save links and clusters to storage."""
        links_file = self.storage_path / "links.json"
        data = {
            "links": [
                {
                    "from_session_id": link.from_session_id,
                    "to_session_id": link.to_session_id,
                    "link_type": link.link_type,
                    "similarity_score": link.similarity_score,
                    "created_at": link.created_at.isoformat()
                }
                for link in self._links[-500:]  # Keep last 500 links
            ],
            "clusters": {
                cid: {
                    "id": cluster.id,
                    "name": cluster.name,
                    "session_ids": cluster.session_ids,
                    "technologies": cluster.technologies,
                    "common_patterns": cluster.common_patterns,
                    "success_rate": cluster.success_rate,
                    "created_at": cluster.created_at.isoformat()
                }
                for cid, cluster in self._clusters.items()
            }
        }
        with open(links_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract significant keywords from text."""
        # Remove common words
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                      'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                      'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                      'can', 'need', 'dare', 'ought', 'used', 'to', 'of', 'in',
                      'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'through',
                      'during', 'before', 'after', 'above', 'below', 'between',
                      'under', 'again', 'further', 'then', 'once', 'here', 'there',
                      'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more',
                      'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only',
                      'own', 'same', 'so', 'than', 'too', 'very', 'just', 'and', 'but',
                      'if', 'or', 'because', 'until', 'while', 'this', 'that', 'these',
                      'those', 'it', 'its', 'i', 'me', 'my', 'we', 'our', 'you', 'your'}
        
        words = re.findall(r'\b[a-z]{3,}\b', text.lower())
        keywords = [w for w in words if w not in stop_words]
        
        # Also extract camelCase and PascalCase identifiers
        identifiers = re.findall(r'\b[A-Z][a-z]+[A-Z]\w*\b', text)
        keywords.extend([i.lower() for i in identifiers])
        
        return list(set(keywords))
    
    def _calculate_similarity(
        self,
        session1_desc: str,
        session1_tech: List[str],
        session1_files: List[str],
        session2_desc: str,
        session2_tech: List[str],
        session2_files: List[str]
    ) -> Tuple[float, str]:
        """
        Calculate similarity between two sessions.
        Returns (score, link_type).
        """
        # Keyword overlap
        kw1 = set(self._extract_keywords(session1_desc))
        kw2 = set(self._extract_keywords(session2_desc))
        
        if kw1 and kw2:
            keyword_sim = len(kw1 & kw2) / max(len(kw1 | kw2), 1)
        else:
            keyword_sim = 0
        
        # Technology overlap
        tech1 = set(t.lower() for t in session1_tech)
        tech2 = set(t.lower() for t in session2_tech)
        
        if tech1 and tech2:
            tech_sim = len(tech1 & tech2) / max(len(tech1 | tech2), 1)
        else:
            tech_sim = 0
        
        # File overlap
        files1 = set(Path(f).name for f in session1_files)
        files2 = set(Path(f).name for f in session2_files)
        
        if files1 and files2:
            file_sim = len(files1 & files2) / max(len(files1 | files2), 1)
        else:
            file_sim = 0
        
        # Determine link type based on strongest similarity
        if file_sim > 0.5:
            return file_sim, "same_files"
        elif tech_sim > 0.7:
            return tech_sim, "related_tech"
        elif keyword_sim > 0.4:
            return keyword_sim, "similar_task"
        
        # Combined score
        score = keyword_sim * 0.5 + tech_sim * 0.3 + file_sim * 0.2
        return score, "similar_task"
    
    async def find_related_sessions(
        self,
        task_description: str,
        technologies: Optional[List[str]] = None,
        files: Optional[List[str]] = None,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Find sessions related to a new task.
        Used when starting a new session to provide context.
        """
        try:
            from pipeline.session_continuity import get_session_manager
            session_mgr = get_session_manager()
        except:
            return []
        
        # Get all sessions
        all_sessions = []
        for session_file in session_mgr.storage_path.glob("*.json"):
            try:
                with open(session_file, 'r') as f:
                    session_data = json.load(f)
                    all_sessions.append(session_data)
            except:
                continue
        
        if not all_sessions:
            return []
        
        # Score each session
        scored = []
        for session in all_sessions:
            session_files = [f.get("path", "") for f in session.get("working_files", [])]
            score, link_type = self._calculate_similarity(
                task_description,
                technologies or [],
                files or [],
                session.get("task_description", ""),
                session.get("technologies", []),
                session_files
            )
            
            if score > 0.2:
                scored.append({
                    "session_id": session["id"],
                    "task": session.get("task_description", "")[:100],
                    "similarity": round(score, 2),
                    "link_type": link_type,
                    "status": session.get("status", "unknown"),
                    "discoveries": session.get("key_discoveries", [])[:3]
                })
        
        # Sort by similarity
        scored.sort(key=lambda x: -x["similarity"])
        return scored[:limit]
    
    async def link_sessions(
        self,
        session1_id: str,
        session2_id: str,
        link_type: str = "related",
        similarity: float = 0.5
    ) -> dict:
        """Manually link two sessions."""
        link = SessionLink(
            from_session_id=session1_id,
            to_session_id=session2_id,
            link_type=link_type,
            similarity_score=similarity
        )
        self._links.append(link)
        self._save_data()
    
    async def auto_link_session(self, session_id: str) -> dict:
        """
        Automatically find and create links for a session.
        Called when a session is updated or completed.
        """
        try:
            from pipeline.session_continuity import get_session_manager
            session_mgr = get_session_manager()
            session = await session_mgr.get_session(session_id)
            
            if not session:
                return
            
            # Find related sessions
            files = [f.path for f in session.working_files]
            related = await self.find_related_sessions(
                session.task_description,
                session.technologies,
                files,
                limit=3
            )
            
            # Create links for highly similar sessions
            for rel in related:
                if rel["similarity"] > 0.4 and rel["session_id"] != session_id:
                    # Check if link already exists
                    exists = any(
                        (link.from_session_id == session_id and link.to_session_id == rel["session_id"]) or
                        (link.from_session_id == rel["session_id"] and link.to_session_id == session_id)
                        for link in self._links
                    )
                    
                    if not exists:
                        await self.link_sessions(
                            session_id,
                            rel["session_id"],
                            rel["link_type"],
                            rel["similarity"]
                        )
                        logger.info(f"Auto-linked sessions {session_id} <-> {rel['session_id']}")
        
        except Exception as e:
            logger.error(f"Auto-link failed: {e}")
    
    def get_session_links(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all links for a session."""
        links = []
        for link in self._links:
            if link.from_session_id == session_id:
                links.append({
                    "linked_session_id": link.to_session_id,
                    "link_type": link.link_type,
                    "similarity": link.similarity_score,
                    "direction": "outgoing"
                })
            elif link.to_session_id == session_id:
                links.append({
                    "linked_session_id": link.from_session_id,
                    "link_type": link.link_type,
                    "similarity": link.similarity_score,
                    "direction": "incoming"
                })
        return links
    
    async def get_learning_summary(self) -> Dict[str, Any]:
        """Get summary of cross-session learning."""
        return {
            "total_links": len(self._links),
            "total_clusters": len(self._clusters),
            "link_types": {
                link_type: sum(1 for l in self._links if l.link_type == link_type)
                for link_type in set(l.link_type for l in self._links)
            } if self._links else {},
            "avg_similarity": sum(l.similarity_score for l in self._links) / len(self._links) if self._links else 0
        }


# Singleton
_cross_session_learner: Optional[CrossSessionLearner] = None


def get_cross_session_learner() -> CrossSessionLearner:
    """Get or create cross-session learner singleton."""
    global _cross_session_learner
    if _cross_session_learner is None:
        _cross_session_learner = CrossSessionLearner()
    return _cross_session_learner
