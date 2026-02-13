"""
Self-reflective response validation — catches hallucinations before the user sees them.

After the LLM generates a response, a cheap validation call checks:
1. Does the response actually answer the user's question?
2. Does it contradict any retrieved context (memories, graph, notes)?
3. Are there factual claims that the context doesn't support?

If validation fails, a correction note is appended to the response.
This runs as a post-stream step using the cheapest available model.
"""

import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Validation prompt — kept short to minimize token cost
VALIDATION_PROMPT = """You are a response validator. Given the user's question, the context that was retrieved, and the assistant's response, check for these issues:

1. CONTRADICTION: Does the response contradict any fact in the retrieved context?
2. UNSUPPORTED CLAIM: Does the response state specific facts not found in the context or general knowledge?
3. MISSED CONTEXT: Did the response ignore relevant information from the context?

Retrieved context:
{context}

User question: {question}

Assistant response: {response}

If there are issues, respond with a brief correction in this format:
ISSUES: [list each issue in one line]
CORRECTION: [what the response should have said differently]

If the response is accurate and complete, respond with exactly: VALID"""

# Minimum response length to bother validating (short responses rarely hallucinate)
MIN_RESPONSE_LENGTH = 200

# Minimum context length — no point validating if there was no context to contradict
MIN_CONTEXT_LENGTH = 50


async def validate_response(
    question: str,
    response: str,
    context: str,
    llm_provider: Any,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Validate an LLM response against retrieved context for hallucinations.

    Uses a cheap/fast model to check if the response contradicts or
    fabricates facts relative to the retrieved context.

    Args:
        question: The user's original question.
        response: The LLM's generated response.
        context: The retrieved context that was injected into the prompt.
        llm_provider: LLM provider instance for making the validation call.
        model: Optional model override (defaults to cheapest available).
        api_key: API key for the provider.
        base_url: Base URL for local providers.

    Returns:
        Dict with keys:
            valid (bool): Whether the response passed validation.
            issues (List[str]): List of issues found (empty if valid).
            correction (str): Suggested correction text (empty if valid).
            skipped (bool): True if validation was skipped (too short, etc).
    """
    result = {
        "valid": True,
        "issues": [],
        "correction": "",
        "skipped": False,
    }

    # Skip validation for short responses or missing context
    if len(response) < MIN_RESPONSE_LENGTH:
        result["skipped"] = True
        return result

    if len(context) < MIN_CONTEXT_LENGTH:
        result["skipped"] = True
        return result

    try:
        prompt = VALIDATION_PROMPT.format(
            context=context[:3000],  # Cap context to keep validation cheap
            question=question[:500],
            response=response[:3000],
        )

        messages = [
            {"role": "system", "content": "You are a concise fact-checker. Be brief."},
            {"role": "user", "content": prompt},
        ]

        # Call LLM for validation (non-streaming, cheap model)
        validation_text = await llm_provider.generate(
            messages=messages,
            model=model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=300,
            temperature=0.0,
        )

        if not validation_text:
            result["skipped"] = True
            return result

        validation_text = validation_text.strip()

        # Parse result
        if validation_text.upper().startswith("VALID"):
            return result

        # Extract issues and correction
        issues = []
        correction = ""
        for line in validation_text.split("\n"):
            line = line.strip()
            if line.upper().startswith("ISSUES:"):
                issues_text = line[7:].strip()
                issues = [i.strip("- ").strip() for i in issues_text.split(",") if i.strip()]
            elif line.startswith("- "):
                issues.append(line[2:].strip())
            elif line.upper().startswith("CORRECTION:"):
                correction = line[11:].strip()

        if issues:
            result["valid"] = False
            result["issues"] = issues
            result["correction"] = correction
            logger.info(
                f"Response validation found {len(issues)} issue(s): "
                f"{issues[:2]}"
            )

        return result

    except Exception as e:
        # Validation failure should never block the response
        logger.debug(f"Response validation skipped due to error: {e}")
        result["skipped"] = True
        return result


def build_correction_note(validation_result: Dict[str, Any]) -> str:
    """
    Build a correction note to append to the response if validation failed.

    Args:
        validation_result: Result dict from validate_response().

    Returns:
        Markdown correction note, or empty string if valid.
    """
    if validation_result["valid"] or validation_result["skipped"]:
        return ""

    issues = validation_result["issues"]
    correction = validation_result["correction"]

    if not issues:
        return ""

    note_parts = ["\n\n---", "*Note: I may have gotten some details wrong above.*"]

    if correction:
        note_parts.append(f"*Correction: {correction}*")

    return "\n".join(note_parts)
