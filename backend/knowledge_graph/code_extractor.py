"""
Code Entity Extractor - Parse code into structured entities for the knowledge graph.

Extracts:
- Functions and methods (with signatures)
- Classes (with inheritance)
- Imports and dependencies
- Error patterns and exceptions
- Variables and constants

Uses AST parsing for Python, regex patterns for other languages,
with LLM fallback for complex cases.
"""

import logging
import re
import ast
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CodeEntityType(str, Enum):
    """Types of code entities we extract."""
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    IMPORT = "import"
    VARIABLE = "variable"
    CONSTANT = "constant"
    ERROR = "error"
    EXCEPTION = "exception"
    DECORATOR = "decorator"
    TYPE_HINT = "type_hint"
    COMMENT = "comment"
    TODO = "todo"


@dataclass
class CodeEntity:
    """Represents an extracted code entity."""
    entity_type: CodeEntityType
    name: str
    signature: str = ""
    docstring: str = ""
    line_number: int = 0
    parent: str = ""  # Parent class/module
    dependencies: List[str] = field(default_factory=list)
    properties: Dict[str, Any] = field(default_factory=dict)
    
    def to_graph_node(self) -> Dict[str, Any]:
        """Convert to knowledge graph node format."""
        return {
            "name": self.name,
            "node_type": self.entity_type.value,
            "properties": {
                "signature": self.signature,
                "docstring": self.docstring[:500] if self.docstring else "",
                "line_number": self.line_number,
                "parent": self.parent,
                **self.properties
            }
        }


class CodeExtractor:
    """
    Extracts structured entities from code for knowledge graph integration.
    
    Supports:
    - Python (via AST)
    - JavaScript/TypeScript (via regex)
    - Generic code (via LLM)
    """
    
    # Language detection patterns
    LANGUAGE_PATTERNS = {
        "python": [r"^import\s+", r"^from\s+.*\s+import", r"^def\s+", r"^class\s+.*:", r"^\s*@\w+"],
        "javascript": [r"^const\s+", r"^let\s+", r"^var\s+", r"^function\s+", r"^class\s+.*{", r"^import\s+.*from"],
        "typescript": [r"^interface\s+", r"^type\s+\w+\s*=", r":\s*\w+\[\]", r"<\w+>"],
    }
    
    # Error pattern detection
    ERROR_PATTERNS = [
        r"(\w+Error):\s*(.+)",
        r"(\w+Exception):\s*(.+)",
        r"Traceback\s*\(most recent call last\)",
        r"File \"(.+)\", line (\d+)",
        r"TypeError|ValueError|KeyError|AttributeError|ImportError|RuntimeError",
    ]
    
    def __init__(self, llm_provider=None):
        """
        Initialize extractor.
        
        Args:
            llm_provider: Optional LLM for complex extraction
        """
        self.llm_provider = llm_provider
    
    def detect_language(self, code: str) -> str:
        """Detect programming language from code snippet."""
        code_lines = code.strip().split('\n')[:20]
        
        scores = {lang: 0 for lang in self.LANGUAGE_PATTERNS}
        
        for line in code_lines:
            for lang, patterns in self.LANGUAGE_PATTERNS.items():
                for pattern in patterns:
                    if re.search(pattern, line, re.MULTILINE):
                        scores[lang] += 1
        
        if max(scores.values()) > 0:
            return max(scores, key=scores.get)
        
        return "unknown"
    
    def extract_entities(self, code: str, language: str = None) -> List[CodeEntity]:
        """
        Extract all code entities from a code snippet.
        
        Args:
            code: Source code string
            language: Programming language (auto-detected if None)
            
        Returns:
            List of extracted CodeEntity objects
        """
        if not code or not code.strip():
            return []
        
        if language is None:
            language = self.detect_language(code)
        
        entities = []
        
        # Always try to extract errors first
        entities.extend(self._extract_errors(code))
        
        if language == "python":
            entities.extend(self._extract_python_ast(code))
        elif language in ("javascript", "typescript"):
            entities.extend(self._extract_js_regex(code))
        else:
            entities.extend(self._extract_generic(code))
        
        # Extract TODOs and FIXMEs
        entities.extend(self._extract_todos(code))
        
        return entities
    
    def _extract_python_ast(self, code: str) -> List[CodeEntity]:
        """Extract entities from Python code using AST."""
        entities = []
        
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            logger.debug(f"Python AST parse failed: {e}")
            return self._extract_generic(code)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                # Extract function/method
                is_method = self._is_method(node, tree)
                parent = self._get_parent_class(node, tree)
                
                # Build signature
                args = []
                for arg in node.args.args:
                    arg_str = arg.arg
                    if arg.annotation:
                        arg_str += f": {ast.unparse(arg.annotation)}"
                    args.append(arg_str)
                
                returns = ""
                if node.returns:
                    returns = f" -> {ast.unparse(node.returns)}"
                
                signature = f"def {node.name}({', '.join(args)}){returns}"
                
                entities.append(CodeEntity(
                    entity_type=CodeEntityType.METHOD if is_method else CodeEntityType.FUNCTION,
                    name=node.name,
                    signature=signature,
                    docstring=ast.get_docstring(node) or "",
                    line_number=node.lineno,
                    parent=parent,
                    dependencies=self._extract_function_deps(node),
                    properties={
                        "is_async": isinstance(node, ast.AsyncFunctionDef),
                        "decorators": [ast.unparse(d) for d in node.decorator_list]
                    }
                ))
            
            elif isinstance(node, ast.ClassDef):
                # Extract class
                bases = [ast.unparse(b) for b in node.bases]
                
                entities.append(CodeEntity(
                    entity_type=CodeEntityType.CLASS,
                    name=node.name,
                    signature=f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}",
                    docstring=ast.get_docstring(node) or "",
                    line_number=node.lineno,
                    dependencies=bases,
                    properties={
                        "decorators": [ast.unparse(d) for d in node.decorator_list],
                        "method_count": len([n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))])
                    }
                ))
            
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    entities.append(CodeEntity(
                        entity_type=CodeEntityType.IMPORT,
                        name=alias.name,
                        signature=f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""),
                        line_number=node.lineno
                    ))
            
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    entities.append(CodeEntity(
                        entity_type=CodeEntityType.IMPORT,
                        name=f"{module}.{alias.name}" if module else alias.name,
                        signature=f"from {module} import {alias.name}",
                        line_number=node.lineno,
                        parent=module
                    ))
        
        return entities
    
    def _extract_js_regex(self, code: str) -> List[CodeEntity]:
        """Extract entities from JavaScript/TypeScript using regex."""
        entities = []
        lines = code.split('\n')
        
        # Function patterns
        func_patterns = [
            r"(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)",
            r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?\(([^)]*)\)\s*=>",
            r"(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?function\s*\(([^)]*)\)",
        ]
        
        for i, line in enumerate(lines, 1):
            for pattern in func_patterns:
                match = re.search(pattern, line)
                if match:
                    name = match.group(1)
                    params = match.group(2) if len(match.groups()) > 1 else ""
                    entities.append(CodeEntity(
                        entity_type=CodeEntityType.FUNCTION,
                        name=name,
                        signature=f"function {name}({params})",
                        line_number=i,
                        properties={"is_async": "async" in line}
                    ))
        
        # Class pattern
        class_pattern = r"class\s+(\w+)(?:\s+extends\s+(\w+))?"
        for i, line in enumerate(lines, 1):
            match = re.search(class_pattern, line)
            if match:
                name = match.group(1)
                base = match.group(2)
                entities.append(CodeEntity(
                    entity_type=CodeEntityType.CLASS,
                    name=name,
                    signature=f"class {name}" + (f" extends {base}" if base else ""),
                    line_number=i,
                    dependencies=[base] if base else []
                ))
        
        # Import pattern
        import_patterns = [
            r"import\s+{([^}]+)}\s+from\s+['\"]([^'\"]+)['\"]",
            r"import\s+(\w+)\s+from\s+['\"]([^'\"]+)['\"]",
            r"const\s+(\w+)\s*=\s*require\(['\"]([^'\"]+)['\"]\)",
        ]
        
        for i, line in enumerate(lines, 1):
            for pattern in import_patterns:
                match = re.search(pattern, line)
                if match:
                    entities.append(CodeEntity(
                        entity_type=CodeEntityType.IMPORT,
                        name=match.group(2),
                        signature=line.strip(),
                        line_number=i
                    ))
        
        return entities
    
    def _extract_generic(self, code: str) -> List[CodeEntity]:
        """Generic extraction using common patterns."""
        entities = []
        lines = code.split('\n')
        
        # Generic function pattern
        func_pattern = r"(?:def|function|func|fn)\s+(\w+)"
        for i, line in enumerate(lines, 1):
            match = re.search(func_pattern, line)
            if match:
                entities.append(CodeEntity(
                    entity_type=CodeEntityType.FUNCTION,
                    name=match.group(1),
                    signature=line.strip()[:100],
                    line_number=i
                ))
        
        return entities
    
    def _extract_errors(self, text: str) -> List[CodeEntity]:
        """Extract error patterns from text/code."""
        entities = []
        
        for pattern in self.ERROR_PATTERNS:
            matches = re.finditer(pattern, text)
            for match in matches:
                error_type = match.group(1) if match.lastindex and match.lastindex >= 1 else match.group(0)
                error_msg = match.group(2) if match.lastindex and match.lastindex >= 2 else ""
                
                entities.append(CodeEntity(
                    entity_type=CodeEntityType.ERROR,
                    name=error_type,
                    signature=error_msg[:200] if error_msg else error_type,
                    properties={"full_match": match.group(0)[:500]}
                ))
        
        return entities
    
    def _extract_todos(self, code: str) -> List[CodeEntity]:
        """Extract TODO/FIXME comments."""
        entities = []
        lines = code.split('\n')
        
        todo_pattern = r"(?:#|//|/\*)\s*(TODO|FIXME|XXX|HACK|NOTE)[\s:]*(.+)"
        
        for i, line in enumerate(lines, 1):
            match = re.search(todo_pattern, line, re.IGNORECASE)
            if match:
                entities.append(CodeEntity(
                    entity_type=CodeEntityType.TODO,
                    name=match.group(1).upper(),
                    signature=match.group(2).strip()[:200],
                    line_number=i
                ))
        
        return entities
    
    def _is_method(self, node: ast.FunctionDef, tree: ast.Module) -> bool:
        """Check if a function is a method (inside a class)."""
        for parent in ast.walk(tree):
            if isinstance(parent, ast.ClassDef):
                for child in parent.body:
                    if child is node:
                        return True
        return False
    
    def _get_parent_class(self, node: ast.FunctionDef, tree: ast.Module) -> str:
        """Get the parent class name for a method."""
        for parent in ast.walk(tree):
            if isinstance(parent, ast.ClassDef):
                for child in parent.body:
                    if child is node:
                        return parent.name
        return ""
    
    def _extract_function_deps(self, node: ast.FunctionDef) -> List[str]:
        """Extract function dependencies (called functions)."""
        deps = []
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    deps.append(child.func.id)
                elif isinstance(child.func, ast.Attribute):
                    deps.append(child.func.attr)
        return list(set(deps))
    
    async def extract_with_llm(self, code: str) -> List[CodeEntity]:
        """
        Use LLM for complex code entity extraction.
        Fallback when AST/regex parsing fails.
        """
        if not self.llm_provider:
            return []
        
        prompt = f"""Analyze this code and extract all entities in JSON format.

Code:
```
{code[:2000]}
```

Return JSON array with entities:
[
  {{
    "type": "function|class|method|import|error|variable",
    "name": "entity_name",
    "signature": "full signature or definition",
    "description": "what it does",
    "dependencies": ["list", "of", "deps"]
  }}
]

Only return the JSON array, no other text."""

        try:
            response = await self.llm_provider.generate(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000
            )
            
            import json
            results = json.loads(response.content)
            
            entities = []
            for r in results:
                entity_type = CodeEntityType(r.get("type", "function"))
                entities.append(CodeEntity(
                    entity_type=entity_type,
                    name=r.get("name", "unknown"),
                    signature=r.get("signature", ""),
                    docstring=r.get("description", ""),
                    dependencies=r.get("dependencies", [])
                ))
            
            return entities
            
        except Exception as e:
            logger.error(f"LLM code extraction failed: {e}")
            return []


def extract_code_blocks(text: str) -> List[Tuple[str, str]]:
    """
    Extract code blocks from markdown-style text.
    
    Returns:
        List of (language, code) tuples
    """
    pattern = r"```(\w*)\n(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    return [(lang or "unknown", code.strip()) for lang, code in matches]


def summarize_code(code: str, max_length: int = 200) -> str:
    """
    Create a compressed summary of code for memory storage.
    
    Stores compressed summaries rather than raw code for efficient retrieval.
    """
    extractor = CodeExtractor()
    entities = extractor.extract_entities(code)
    
    if not entities:
        return code[:max_length]
    
    # Build summary from entities
    parts = []
    
    classes = [e for e in entities if e.entity_type == CodeEntityType.CLASS]
    functions = [e for e in entities if e.entity_type in (CodeEntityType.FUNCTION, CodeEntityType.METHOD)]
    imports = [e for e in entities if e.entity_type == CodeEntityType.IMPORT]
    
    if classes:
        parts.append(f"Classes: {', '.join(c.name for c in classes[:3])}")
    
    if functions:
        parts.append(f"Functions: {', '.join(f.name for f in functions[:5])}")
    
    if imports:
        parts.append(f"Imports: {', '.join(i.name.split('.')[-1] for i in imports[:5])}")
    
    summary = "; ".join(parts)
    
    if len(summary) > max_length:
        return summary[:max_length-3] + "..."
    
    return summary
