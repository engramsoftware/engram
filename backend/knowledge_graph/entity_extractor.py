"""
Hybrid entity extraction using GLiNER + spaCy + LLM fallback.

This module extracts entities and relationships from text using:
1. GLiNER for custom entity types (technology, frameworks, tools, etc.)
2. spaCy for standard NER and relationship parsing (subject-verb-object)
3. coreferee for pronoun resolution
4. LLM fallback for ambiguous or complex relationships

Uses a hybrid approach for cost-effective entity extraction.
"""

import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

# ============================================================
# GLiNER imports with graceful fallback
# ============================================================
GLINER_AVAILABLE = False
gliner_model = None

try:
    from gliner import GLiNER
    GLINER_AVAILABLE = True
    logger.info("GLiNER available for entity extraction")
except ImportError:
    logger.warning("GLiNER not available - custom entity extraction disabled")

# ============================================================
# spaCy imports with graceful fallback
# ============================================================
SPACY_AVAILABLE = False
nlp = None

try:
    import spacy
    SPACY_AVAILABLE = True
    logger.info("spaCy available for entity extraction")
except ImportError:
    logger.warning("spaCy not available - relationship extraction disabled")


@dataclass
class Entity:
    """
    An entity extracted from text.
    
    Attributes:
        text: The entity text/mention
        type: Entity type (technology, person, organization, etc.)
        confidence: Extraction confidence (0.0-1.0)
        source: Extraction source (gliner, spacy, llm)
    """
    text: str
    type: str
    confidence: float = 0.8
    source: str = "unknown"


@dataclass
class Relationship:
    """
    A relationship between two entities.
    
    Attributes:
        subject: Subject entity text
        predicate: Relationship type/verb
        object: Object entity text
        confidence: Extraction confidence (0.0-1.0)
        source: Extraction source (spacy, llm)
    """
    subject: str
    predicate: str
    object: str
    confidence: float = 0.8
    source: str = "unknown"


class EntityExtractor:
    """
    Hybrid entity and relationship extractor.
    
    Uses a multi-stage pipeline:
    1. GLiNER for custom entity types
    2. spaCy for standard NER and dependency parsing
    3. coreferee for pronoun resolution
    4. LLM fallback for complex cases
    
    Attributes:
        gliner_model: GLiNER model instance
        nlp: spaCy language model with coreferee
        llm_provider: LLM provider for fallback extractions
    """
    
    # Entity labels for GLiNER
    # These are custom types relevant to technical conversations
    GLINER_LABELS = [
        "technology",
        "framework",
        "programming_language",
        "tool",
        "error_type",
        "project",
        "concept",
        "decision",
        "approach",
        "person",
        "organization"
    ]
    
    def __init__(
        self,
        gliner_model_name: str = "urchade/gliner_mediumv2.1",
        spacy_model_name: str = "en_core_web_sm",
        use_llm_fallback: bool = True
    ):
        """
        Initialize the entity extractor.
        
        Args:
            gliner_model_name: GLiNER model to use
            spacy_model_name: spaCy model to use
            use_llm_fallback: Whether to use LLM for ambiguous cases
        """
        self.gliner_model = None
        self.nlp = None
        self.use_llm_fallback = use_llm_fallback
        self._initialized = False
        
        # Initialize models
        self._init_gliner(gliner_model_name)
        self._init_spacy(spacy_model_name)
        
        if self.gliner_model or self.nlp:
            self._initialized = True
            logger.info("EntityExtractor initialized")
    
    def _init_gliner(self, model_name: str) -> None:
        """Initialize GLiNER model."""
        if not GLINER_AVAILABLE:
            logger.info("GLiNER not available, skipping")
            return
        
        try:
            global gliner_model
            if gliner_model is None:
                logger.info(f"Loading GLiNER model: {model_name}")
                from gliner import GLiNER
                gliner_model = GLiNER.from_pretrained(model_name)
                logger.info("GLiNER model loaded")
            
            self.gliner_model = gliner_model
            
        except Exception as e:
            logger.error(f"Failed to load GLiNER: {e}")
            self.gliner_model = None
    
    def _init_spacy(self, model_name: str) -> None:
        """Initialize spaCy model with coreferee."""
        if not SPACY_AVAILABLE:
            logger.info("spaCy not available, skipping")
            return
        
        try:
            global nlp
            if nlp is None:
                logger.info(f"Loading spaCy model: {model_name}")
                import spacy
                nlp = spacy.load(model_name)
                
                # Try to add coreferee if available
                try:
                    import coreferee
                    nlp.add_pipe('coreferee')
                    logger.info("spaCy loaded with coreferee")
                except ImportError:
                    logger.warning("coreferee not available - pronoun resolution disabled")
                except Exception as e:
                    logger.warning(f"Failed to add coreferee: {e}")
            
            self.nlp = nlp
            
        except OSError as e:
            logger.error(f"spaCy model not found. Run: python -m spacy download {model_name}")
            self.nlp = None
        except Exception as e:
            logger.error(f"Failed to load spaCy: {e}")
            self.nlp = None
    
    @property
    def is_available(self) -> bool:
        """Check if at least one extraction method is available."""
        return self._initialized and (self.gliner_model is not None or self.nlp is not None)
    
    @staticmethod
    def _strip_code_blocks(text: str) -> str:
        """Remove fenced code blocks and inline code from text.

        Prevents code snippets from being fed to GLiNER/spaCy which
        would extract garbage entities like variable names, imports,
        and syntax fragments.

        Args:
            text: Raw text that may contain markdown code blocks.

        Returns:
            Text with code blocks replaced by empty strings.
        """
        # Remove fenced code blocks (```...```)
        text = re.sub(r'```[\s\S]*?```', '', text)
        # Remove inline code (`...`)
        text = re.sub(r'`[^`]+`', '', text)
        # Remove lines that look like code (indented 4+ spaces or start with common code patterns)
        lines = []
        for line in text.split('\n'):
            stripped = line.strip()
            # Skip lines that look like code
            if (stripped.startswith(('import ', 'from ', 'def ', 'class ', 'if ', 'for ',
                                     'return ', 'async ', 'await ', 'try:', 'except',
                                     '#!', '#!/', '{', '}', '//', '/*'))
                or stripped.endswith(('{', '}', ');', '};'))
                or (len(line) > 0 and len(line) - len(line.lstrip()) >= 4 and any(
                    c in stripped for c in ['=', '()', '->', '=>', '++', '--']))):
                continue
            lines.append(line)
        return '\n'.join(lines)

    def extract_entities(self, text: str) -> List[Entity]:
        """
        Extract entities from text using GLiNER + spaCy.
        
        Args:
            text: Input text to extract entities from
            
        Returns:
            List of Entity objects
        """
        if not self.is_available or not text.strip():
            return []

        # Strip code blocks to prevent garbage entity extraction
        text = self._strip_code_blocks(text)
        if not text.strip():
            return []
        
        entities = []
        
        # 1. GLiNER for custom entity types
        if self.gliner_model:
            try:
                gliner_entities = self.gliner_model.predict_entities(
                    text,
                    self.GLINER_LABELS,
                    threshold=0.5
                )
                
                for ent in gliner_entities:
                    entities.append(Entity(
                        text=ent["text"],
                        type=ent["label"],
                        confidence=ent.get("score", 0.8),
                        source="gliner"
                    ))
                    
                logger.debug(f"GLiNER extracted {len(gliner_entities)} entities")
                
            except Exception as e:
                logger.error(f"GLiNER extraction failed: {e}")
        
        # 2. spaCy for standard NER
        if self.nlp:
            try:
                doc = self.nlp(text)
                
                for ent in doc.ents:
                    entities.append(Entity(
                        text=ent.text,
                        type=ent.label_.lower(),
                        confidence=0.7,  # spaCy doesn't provide scores
                        source="spacy"
                    ))
                
                logger.debug(f"spaCy extracted {len(doc.ents)} entities")
                
            except Exception as e:
                logger.error(f"spaCy extraction failed: {e}")
        
        # Deduplicate entities by text (keep highest confidence)
        entities = self._deduplicate_entities(entities)
        
        return entities
    
    def extract_relationships(self, text: str) -> List[Relationship]:
        """
        Extract relationships from text using spaCy dependency parsing.

        Extracts subject-verb-object triples from text.

        Args:
            text: Input text to extract relationships from

        Returns:
            List of Relationship objects
        """
        if not self.nlp or not text.strip():
            return []

        # Strip code blocks to prevent garbage relationships
        text = self._strip_code_blocks(text)
        if not text.strip():
            return []

        # Import filter function
        from knowledge_graph.graph_store import is_valid_entity

        relationships = []

        try:
            doc = self.nlp(text)

            # Extract subject-verb-object triples using dependency parsing
            for sent in doc.sents:
                # Find verbs
                for token in sent:
                    if token.pos_ != "VERB":
                        continue

                    # Find subject - prefer noun phrases
                    subject = None
                    for child in token.children:
                        if child.dep_ in ["nsubj", "nsubjpass"]:
                            # Try to get the full noun phrase
                            if child.subtree:
                                subj_span = doc[child.left_edge.i:child.right_edge.i + 1]
                                subject = subj_span.text.strip()
                            else:
                                subject = child.text
                            break

                    # Find object - prefer noun phrases
                    obj = None
                    for child in token.children:
                        if child.dep_ in ["dobj", "attr", "oprd", "pobj"]:
                            # Try to get the full noun phrase
                            if child.subtree:
                                obj_span = doc[child.left_edge.i:child.right_edge.i + 1]
                                obj = obj_span.text.strip()
                            else:
                                obj = child.text
                            break

                    # Clean up extracted spans — strip markdown artifacts
                    if subject:
                        subject = subject.lstrip('-*#> \t').strip()
                    if obj:
                        obj = obj.lstrip('-*#> \t').strip()

                    # Validate: both must be real entities, not sentence fragments
                    if not subject or not obj:
                        continue
                    if not is_valid_entity(subject) or not is_valid_entity(obj):
                        continue
                    # Skip if either contains markdown noise (* for bold/italic)
                    if '*' in subject or '*' in obj:
                        continue
                    # Skip overly long spans (sentence fragments captured by subtree)
                    if len(subject) > 50 or len(obj) > 50:
                        continue
                    # Skip if subject == object
                    if subject.lower() == obj.lower():
                        continue

                    relationships.append(Relationship(
                        subject=subject,
                        predicate=token.lemma_,  # Use lemma for normalized verb
                        object=obj,
                        confidence=0.7,
                        source="spacy"
                    ))

            logger.debug(f"Extracted {len(relationships)} valid relationships")

        except Exception as e:
            logger.error(f"Relationship extraction failed: {e}")

        return relationships
    
    def extract_entities_and_relations(
        self,
        text: str
    ) -> Tuple[List[Entity], List[Relationship]]:
        """
        Extract both entities and relationships from text.
        
        This is the main entry point for entity extraction.
        
        Args:
            text: Input text to process
            
        Returns:
            Tuple of (entities, relationships)
        """
        entities = self.extract_entities(text)
        relationships = self.extract_relationships(text)
        
        return entities, relationships

    async def resolve_pronouns_with_llm(
        self,
        text: str,
        entities: List[Entity],
        provider=None,
        model: Optional[str] = None,
    ) -> str:
        """Resolve pronouns in text to actual entity names using an LLM.

        Replaces coreferee (incompatible with pydantic v2) with a cheap
        LLM call that rewrites pronouns like "he", "it", "they" to the
        entity names they refer to.

        Args:
            text: The original text containing pronouns.
            entities: Entities already extracted from the text.
            provider: An LLM provider instance (must have .generate()).
            model: Model name to use for the LLM call.

        Returns:
            Text with pronouns replaced by entity names, or original
            text if resolution fails or no pronouns are detected.
        """
        if not provider or not entities:
            return text

        # Quick check: skip if no common pronouns found
        _PRONOUNS = {"he", "she", "it", "they", "him", "her", "them",
                      "his", "its", "their", "this", "that", "these", "those"}
        words = set(text.lower().split())
        if not words & _PRONOUNS:
            return text

        entity_names = ", ".join(e.text for e in entities[:15])
        prompt = (
            "Rewrite the following text, replacing pronouns (he, she, it, they, "
            "this, that, etc.) with the actual entity names they refer to. "
            "Keep the text otherwise identical. Only replace pronouns where "
            "the referent is clear.\n\n"
            f"Known entities: {entity_names}\n\n"
            f"Text:\n{text}\n\n"
            "Rewritten text:"
        )

        try:
            response = await provider.generate(
                messages=[{"role": "user", "content": prompt}],
                model=model or "gpt-4o-mini",
                temperature=0.1,
                max_tokens=len(text) + 200,
            )
            resolved = response.content.strip()
            # Sanity check: result shouldn't be wildly different length
            if resolved and 0.5 < len(resolved) / max(len(text), 1) < 2.0:
                logger.debug(f"LLM pronoun resolution: {len(text)} → {len(resolved)} chars")
                return resolved
            else:
                logger.debug("LLM pronoun resolution result too different, keeping original")
                return text
        except Exception as e:
            logger.debug(f"LLM pronoun resolution failed: {e}")
            return text
    
    def _deduplicate_entities(self, entities: List[Entity]) -> List[Entity]:
        """
        Deduplicate entities by text, keeping the one with highest confidence.
        Also filters out noisy/useless entities.

        Args:
            entities: List of entities to deduplicate

        Returns:
            Deduplicated and filtered list of entities
        """
        if not entities:
            return []

        # Import filter function
        from knowledge_graph.graph_store import is_valid_entity

        # Group by normalized text
        entity_map: Dict[str, Entity] = {}

        for entity in entities:
            # Skip noisy entities
            if not is_valid_entity(entity.text):
                continue

            key = entity.text.lower().strip()

            # Keep entity with highest confidence
            if key not in entity_map or entity.confidence > entity_map[key].confidence:
                entity_map[key] = entity

        return list(entity_map.values())


# ============================================================
# Module-level singleton for lazy loading
# ============================================================
_entity_extractor: Optional[EntityExtractor] = None


def get_entity_extractor() -> EntityExtractor:
    """
    Get or create the singleton EntityExtractor instance.
    
    Models are loaded lazily on first access to avoid startup delays.
    
    Returns:
        EntityExtractor singleton instance
    """
    global _entity_extractor
    if _entity_extractor is None:
        _entity_extractor = EntityExtractor()
    return _entity_extractor


def load_gliner_model() -> None:
    """
    Preload GLiNER model at startup (optional).
    
    Call this in the FastAPI lifespan event to avoid
    first-request latency.
    """
    extractor = get_entity_extractor()
    if extractor.gliner_model:
        logger.info("GLiNER model preloaded")


def load_spacy_model() -> None:
    """
    Preload spaCy model at startup (optional).
    
    Call this in the FastAPI lifespan event to avoid
    first-request latency.
    """
    extractor = get_entity_extractor()
    if extractor.nlp:
        logger.info("spaCy model preloaded")
