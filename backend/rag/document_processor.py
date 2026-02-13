"""
Document processing for RAG: parse, chunk, and embed uploaded files.

Supports PDF, TXT, MD, and DOCX files. Chunks are stored in a dedicated
ChromaDB collection ('user_documents') separate from chat message embeddings.

Chunking strategy:
  - Split by paragraphs first, then by sentence boundaries if too long.
  - Target ~500 chars per chunk with 50-char overlap for context continuity.
  - Each chunk gets metadata: user_id, document_id, filename, chunk_index.
"""

import logging
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================
# Optional PDF/DOCX parsers — graceful fallback if not installed
# ============================================================
PYPDF_AVAILABLE = False
try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    logger.info("pypdf not installed — PDF upload disabled. pip install pypdf")

DOCX_AVAILABLE = False
try:
    import docx as python_docx
    DOCX_AVAILABLE = True
except ImportError:
    logger.info("python-docx not installed — DOCX upload disabled. pip install python-docx")

# ============================================================
# ChromaDB collection for user documents (separate from messages)
# ============================================================
CHROMADB_AVAILABLE = False
try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    logger.warning("ChromaDB not available — RAG disabled")

# Singleton collection reference
_doc_collection = None
_chroma_client = None

# Chunking parameters
CHUNK_SIZE = 500       # target characters per chunk
CHUNK_OVERLAP = 50     # overlap between consecutive chunks
MIN_CHUNK_SIZE = 50    # discard chunks shorter than this


def _get_doc_collection():
    """Get or create the ChromaDB collection for user documents.

    Returns:
        ChromaDB collection, or None if unavailable.
    """
    global _doc_collection, _chroma_client

    if not CHROMADB_AVAILABLE:
        return None

    if _doc_collection is not None:
        return _doc_collection

    try:
        from config import CHROMA_DOCUMENTS_DIR
        persist_path = CHROMA_DOCUMENTS_DIR
        persist_path.mkdir(parents=True, exist_ok=True)

        _chroma_client = chromadb.PersistentClient(
            path=str(persist_path),
            settings=Settings(anonymized_telemetry=False),
        )
        _doc_collection = _chroma_client.get_or_create_collection(
            name="user_documents",
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            f"RAG document collection ready — {_doc_collection.count()} chunks stored"
        )
        return _doc_collection
    except Exception as e:
        logger.error(f"Failed to init RAG document collection: {e}")
        return None


# ============================================================
# File parsing
# ============================================================

def parse_txt(file_bytes: bytes) -> str:
    """Parse plain text / markdown file.

    Args:
        file_bytes: Raw file content.

    Returns:
        Decoded text string.
    """
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="replace")


def parse_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF file.

    Args:
        file_bytes: Raw PDF bytes.

    Returns:
        Concatenated text from all pages.

    Raises:
        ImportError: If pypdf is not installed.
    """
    if not PYPDF_AVAILABLE:
        raise ImportError("pypdf not installed. Run: pip install pypdf")

    import io
    reader = PdfReader(io.BytesIO(file_bytes))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)


def parse_docx(file_bytes: bytes) -> str:
    """Extract text from a DOCX file.

    Args:
        file_bytes: Raw DOCX bytes.

    Returns:
        Concatenated paragraph text.

    Raises:
        ImportError: If python-docx is not installed.
    """
    if not DOCX_AVAILABLE:
        raise ImportError("python-docx not installed. Run: pip install python-docx")

    import io
    doc = python_docx.Document(io.BytesIO(file_bytes))
    return "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())


def parse_file(filename: str, file_bytes: bytes) -> str:
    """Route file to the correct parser based on extension.

    Args:
        filename: Original filename with extension.
        file_bytes: Raw file content.

    Returns:
        Extracted text.

    Raises:
        ValueError: If file type is unsupported.
    """
    ext = Path(filename).suffix.lower()

    if ext in (".txt", ".md", ".markdown", ".rst", ".csv", ".log", ".json", ".yaml", ".yml"):
        return parse_txt(file_bytes)
    elif ext == ".pdf":
        return parse_pdf(file_bytes)
    elif ext in (".docx",):
        return parse_docx(file_bytes)
    else:
        raise ValueError(
            f"Unsupported file type: {ext}. "
            "Supported: .txt, .md, .pdf, .docx, .csv, .json, .yaml"
        )


# ============================================================
# Chunking
# ============================================================

def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> List[str]:
    """Split text into overlapping chunks using recursive character text splitting.

    This implements the same strategy as LangChain's RecursiveCharacterTextSplitter,
    which is the industry standard for RAG chunking:

      1. Try splitting by the most semantically meaningful separator first
         (double newline > single newline > sentence boundary > word > char).
      2. Merge small segments up to chunk_size with overlap for context continuity.
      3. Recursively split any segments that still exceed chunk_size.

    This preserves document structure (headings, paragraphs, lists) as much as
    possible while ensuring no chunk exceeds the target size.

    Args:
        text: Full document text.
        chunk_size: Target characters per chunk.
        overlap: Characters of overlap between chunks.

    Returns:
        List of text chunks.
    """
    if not text or not text.strip():
        return []

    # Separators ordered from most to least semantically meaningful
    # (same hierarchy as LangChain RecursiveCharacterTextSplitter)
    SEPARATORS = [
        "\n\n",                    # paragraph breaks
        "\n",                      # line breaks
        r"(?<=[.!?])\s+",         # sentence boundaries (regex)
        r"(?<=[;:])\s+",          # clause boundaries (regex)
        " ",                       # words
        "",                        # characters (last resort)
    ]

    def _split_by_separator(text: str, separator: str) -> List[str]:
        """Split text by a separator, handling both literal and regex patterns."""
        if not separator:
            return list(text)  # character-level split
        if separator in ("\n\n", "\n", " "):
            return text.split(separator)
        # Regex separator
        return re.split(separator, text)

    def _recursive_split(text: str, separators: List[str]) -> List[str]:
        """Recursively split text using progressively finer separators."""
        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        # Find the best separator that actually splits this text
        best_sep = separators[-1]  # fallback to finest separator
        for sep in separators:
            if not sep:
                best_sep = sep
                break
            # Check if separator exists in text
            if sep in ("\n\n", "\n", " "):
                if sep in text:
                    best_sep = sep
                    break
            else:
                if re.search(sep, text):
                    best_sep = sep
                    break

        # Split by the chosen separator
        parts = _split_by_separator(text, best_sep)

        # Determine which separators to use for further recursion
        remaining_seps = separators[separators.index(best_sep) + 1:] if best_sep in separators else separators[-1:]
        if not remaining_seps:
            remaining_seps = [""]

        # Merge small parts and recursively split large ones
        result: List[str] = []
        current = ""

        for part in parts:
            part = part.strip()
            if not part:
                continue

            if len(part) > chunk_size:
                # This part is still too big — flush current, then recurse
                if current.strip():
                    result.append(current.strip())
                    current = ""
                result.extend(_recursive_split(part, remaining_seps))
            elif current and len(current) + len(part) + 1 > chunk_size:
                # Adding this part would exceed chunk_size — flush current
                result.append(current.strip())
                # Keep overlap from end of previous chunk for context continuity
                if overlap > 0 and len(current) > overlap:
                    current = current[-overlap:].strip() + " " + part
                else:
                    current = part
            else:
                # Accumulate into current chunk
                joiner = best_sep if best_sep in ("\n\n", "\n") else " "
                current = (current + joiner + part).strip() if current else part

        if current.strip():
            result.append(current.strip())

        return result

    chunks = _recursive_split(text.strip(), SEPARATORS)

    # Filter out tiny chunks that won't embed well
    chunks = [c for c in chunks if len(c) >= MIN_CHUNK_SIZE]

    return chunks


# ============================================================
# Embedding into ChromaDB
# ============================================================

def embed_chunks(
    chunks: List[str],
    user_id: str,
    document_id: str,
    filename: str,
) -> int:
    """Embed text chunks into the RAG ChromaDB collection.

    Args:
        chunks: List of text chunks to embed.
        user_id: Owner's user ID.
        document_id: MongoDB document ID for linking.
        filename: Original filename for metadata.

    Returns:
        Number of chunks successfully embedded.
    """
    collection = _get_doc_collection()
    if collection is None:
        logger.warning("RAG collection unavailable — skipping embedding")
        return 0

    ids = []
    documents = []
    metadatas = []

    for i, chunk in enumerate(chunks):
        chunk_id = f"{document_id}_chunk_{i}"
        ids.append(chunk_id)
        documents.append(chunk)
        metadatas.append({
            "user_id": user_id,
            "document_id": document_id,
            "filename": filename,
            "chunk_index": i,
            "total_chunks": len(chunks),
        })

    try:
        # Upsert in batches of 100 (ChromaDB limit)
        batch_size = 100
        embedded = 0
        for start in range(0, len(ids), batch_size):
            end = start + batch_size
            collection.upsert(
                ids=ids[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )
            embedded += len(ids[start:end])

        logger.info(
            f"Embedded {embedded} chunks for document '{filename}' (user={user_id})"
        )
        return embedded
    except Exception as e:
        logger.error(f"Failed to embed chunks for '{filename}': {e}")
        return 0


# ============================================================
# Smart retrieval — only returns docs when query is relevant
# ============================================================

# Cosine distance threshold: lower = more similar.
# ChromaDB returns distances in [0, 2] for cosine; 0 = identical.
# 0.8 is a reasonable cutoff — only inject docs that are genuinely related.
RELEVANCE_THRESHOLD = 0.8


def search_documents(
    query: str,
    user_id: str,
    top_k: int = 3,
    threshold: float = RELEVANCE_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Search user's uploaded documents for chunks relevant to a query.

    Only returns results whose cosine distance is below the threshold,
    preventing irrelevant documents from polluting every conversation.

    Args:
        query: The user's message / search query.
        user_id: Filter to this user's documents.
        top_k: Maximum chunks to return.
        threshold: Max cosine distance to include (lower = stricter).

    Returns:
        List of dicts with 'content', 'filename', 'distance', 'document_id'.
        Empty list if nothing is relevant or collection unavailable.
    """
    collection = _get_doc_collection()
    if collection is None or collection.count() == 0:
        return []

    if not query or not query.strip():
        return []

    try:
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
            where={"user_id": user_id},
            include=["documents", "metadatas", "distances"],
        )

        if not results or not results["ids"] or not results["ids"][0]:
            return []

        output = []
        for i, doc_id in enumerate(results["ids"][0]):
            distance = results["distances"][0][i] if results["distances"] else 1.0

            # Smart gate: skip chunks that aren't relevant enough
            if distance > threshold:
                continue

            output.append({
                "id": doc_id,
                "content": results["documents"][0][i] if results["documents"] else "",
                "distance": distance,
                "filename": results["metadatas"][0][i].get("filename", ""),
                "document_id": results["metadatas"][0][i].get("document_id", ""),
                "chunk_index": results["metadatas"][0][i].get("chunk_index", 0),
            })

        if output:
            logger.info(
                f"RAG: {len(output)} relevant chunks found "
                f"(best distance={output[0]['distance']:.3f}, threshold={threshold})"
            )
        else:
            logger.debug(f"RAG: no chunks below threshold {threshold} for query")

        return output

    except Exception as e:
        logger.error(f"RAG search failed: {e}")
        return []


def delete_document_chunks(document_id: str) -> bool:
    """Delete all chunks for a document from ChromaDB.

    Args:
        document_id: The MongoDB document ID whose chunks to remove.

    Returns:
        True if successful, False otherwise.
    """
    collection = _get_doc_collection()
    if collection is None:
        return False

    try:
        collection.delete(where={"document_id": document_id})
        logger.info(f"Deleted RAG chunks for document {document_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete RAG chunks for {document_id}: {e}")
        return False
