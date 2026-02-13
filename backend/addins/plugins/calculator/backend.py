"""
Calculator Add-in.
Type 1: LLM-callable tool for safe math evaluation.

Uses ast.literal_eval for safe expression parsing.
Supports basic arithmetic, powers, and common math functions.
"""

import logging
import math
import ast
import operator
from typing import List, Dict, Any

from addins.addin_interface import ToolAddin, ToolDefinition, ToolResult

logger = logging.getLogger(__name__)

# Safe operators for evaluation
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Safe math functions
SAFE_FUNCTIONS = {
    'abs': abs,
    'round': round,
    'min': min,
    'max': max,
    'sum': sum,
    'sqrt': math.sqrt,
    'sin': math.sin,
    'cos': math.cos,
    'tan': math.tan,
    'log': math.log,
    'log10': math.log10,
    'exp': math.exp,
    'floor': math.floor,
    'ceil': math.ceil,
    'pi': math.pi,
    'e': math.e,
}


class SafeEvaluator(ast.NodeVisitor):
    """
    Safe expression evaluator using AST.
    Only allows basic math operations.
    """
    
    def visit_BinOp(self, node) -> dict:
        left = self.visit(node.left)
        right = self.visit(node.right)
        op = SAFE_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(left, right)
    
    def visit_UnaryOp(self, node) -> dict:
        operand = self.visit(node.operand)
        op = SAFE_OPERATORS.get(type(node.op))
        if op is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        return op(operand)
    
    def visit_Num(self, node) -> dict:
        return node.n
    
    def visit_Constant(self, node) -> dict:
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value}")
    
    def visit_Name(self, node) -> dict:
        if node.id in SAFE_FUNCTIONS:
            return SAFE_FUNCTIONS[node.id]
        raise ValueError(f"Unknown variable: {node.id}")
    
    def visit_Call(self, node) -> dict:
        func = self.visit(node.func)
        args = [self.visit(arg) for arg in node.args]
        if callable(func):
            return func(*args)
        raise ValueError("Invalid function call")
    
    def generic_visit(self, node) -> dict:
        raise ValueError(f"Unsupported expression: {type(node).__name__}")


def safe_eval(expression: str) -> float:
    """
    Safely evaluate a mathematical expression.
    
    Args:
        expression: Math expression string
        
    Returns:
        Evaluation result
    """
    tree = ast.parse(expression, mode='eval')
    evaluator = SafeEvaluator()
    return evaluator.visit(tree.body)


class CalculatorAddin(ToolAddin):
    """
    Calculator tool for safe mathematical evaluation.
    """
    
    name = "calculator"
    version = "1.0.0"
    description = "Evaluate mathematical expressions safely"
    permissions = []
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config)
        self.precision = self.config.get("precision", 10)
    
    async def initialize(self) -> bool:
        """Initialize the calculator add-in."""
        return True
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        pass
    
    def get_tool_definitions(self) -> List[ToolDefinition]:
        """Define the calculate tool."""
        return [
            ToolDefinition(
                name="calculate",
                description="Evaluate a mathematical expression. Supports +, -, *, /, **, sqrt, sin, cos, tan, log, exp, pi, e",
                parameters={
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "Mathematical expression to evaluate (e.g., '2 + 2', 'sqrt(16)', 'sin(pi/2)')"
                        }
                    },
                    "required": ["expression"]
                }
            )
        ]
    
    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> ToolResult:
        """Execute the calculation."""
        if tool_name != "calculate":
            return ToolResult(success=False, error=f"Unknown tool: {tool_name}")
        
        expression = arguments.get("expression", "")
        
        if not expression:
            return ToolResult(success=False, error="Expression is required")
        
        try:
            result = safe_eval(expression)
            
            # Round to configured precision
            if isinstance(result, float):
                result = round(result, self.precision)
            
            return ToolResult(
                success=True,
                result={
                    "expression": expression,
                    "result": result
                }
            )
            
        except Exception as e:
            logger.error(f"Calculation failed: {e}")
            return ToolResult(success=False, error=str(e))


# Export the add-in class
Addin = CalculatorAddin
