"""Make `import llm...` work the same way it does when the app runs from backend/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
