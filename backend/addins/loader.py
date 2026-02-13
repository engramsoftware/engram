"""
Add-in Loader.
Dynamically loads add-ins from manifest files.
"""

import logging
import importlib.util
import json
from pathlib import Path
from typing import Optional, Dict, Any

from addins.addin_interface import AddinBase, AddinType
from addins.registry import get_registry

logger = logging.getLogger(__name__)


class AddinLoader:
    """
    Loads add-ins from manifest files and Python modules.
    
    Expected add-in structure:
    addins/
    └── my_addin/
        ├── manifest.json
        ├── backend.py
        └── frontend.tsx (optional)
    """
    
    def __init__(self, addins_dir: str = "addins/plugins"):
        """
        Initialize loader with add-ins directory.
        
        Args:
            addins_dir: Path to directory containing add-in folders
        """
        self.addins_dir = Path(addins_dir)
    
    def load_manifest(self, manifest_path: Path) -> Optional[Dict[str, Any]]:
        """
        Load and validate an add-in manifest.
        
        Args:
            manifest_path: Path to manifest.json
            
        Returns:
            Parsed manifest dict or None if invalid
        """
        try:
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
            
            # Validate required fields
            required = ['id', 'name', 'version', 'type', 'entrypoint']
            for field in required:
                if field not in manifest:
                    logger.error(f"Manifest missing required field: {field}")
                    return None
            
            return manifest
            
        except Exception as e:
            logger.error(f"Failed to load manifest {manifest_path}: {e}")
            return None
    
    def load_python_module(
        self,
        module_path: Path,
        class_name: str = "Addin"
    ) -> Optional[type]:
        """
        Dynamically load a Python module and get the add-in class.
        
        Supports packages with relative imports (e.g. from .skill_store import ...).
        If the plugin directory has an __init__.py, uses importlib.import_module
        with dotted path so relative imports resolve correctly.
        
        Args:
            module_path: Path to Python file
            class_name: Name of the add-in class to load
            
        Returns:
            Add-in class or None if loading failed
        """
        try:
            # Check if this is a package (has __init__.py) — use dotted import
            # so relative imports like "from .skill_store import ..." work
            plugin_dir = module_path.parent
            if (plugin_dir / "__init__.py").exists():
                # Build dotted module path relative to cwd (e.g. addins.plugins.skill_voyager.backend)
                try:
                    import sys, os
                    cwd = Path(os.getcwd())
                    abs_path = module_path.resolve()
                    rel = abs_path.relative_to(cwd)
                    dotted = str(rel.with_suffix("")).replace(os.sep, ".")
                    module = importlib.import_module(dotted)
                except Exception as pkg_err:
                    logger.debug(f"Package import failed ({pkg_err}), falling back to file-based load")
                    # Fall through to file-based loading below
                    module = None
            else:
                module = None
            
            # Fallback: file-based loading (works for simple plugins without relative imports)
            if module is None:
                spec = importlib.util.spec_from_file_location(
                    module_path.stem,
                    module_path
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            
            # Get the add-in class
            if hasattr(module, class_name):
                return getattr(module, class_name)
            
            # Try to find any AddinBase subclass
            for name in dir(module):
                obj = getattr(module, name)
                if (isinstance(obj, type) and 
                    issubclass(obj, AddinBase) and 
                    obj is not AddinBase):
                    return obj
            
            logger.error(f"No add-in class found in {module_path}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to load module {module_path}: {e}")
            return None
    
    async def load_addin(self, addin_dir: Path) -> Optional[AddinBase]:
        """
        Load an add-in from its directory.
        
        Args:
            addin_dir: Path to add-in directory
            
        Returns:
            Instantiated add-in or None if loading failed
        """
        manifest_path = addin_dir / "manifest.json"
        
        if not manifest_path.exists():
            logger.error(f"No manifest.json in {addin_dir}")
            return None
        
        # Load manifest
        manifest = self.load_manifest(manifest_path)
        if not manifest:
            return None
        
        # Get backend entrypoint
        entrypoint = manifest.get('entrypoint', {})
        backend_file = entrypoint.get('backend', 'backend.py')
        backend_path = addin_dir / backend_file
        
        if not backend_path.exists():
            logger.error(f"Backend file not found: {backend_path}")
            return None
        
        # Load the Python module
        addin_class = self.load_python_module(backend_path)
        if not addin_class:
            return None
        
        # Instantiate with config from manifest
        config = manifest.get('config', {})
        addin = addin_class(config=config)
        
        # Override metadata from manifest
        addin.name = manifest['id']
        addin.version = manifest['version']
        addin.description = manifest.get('description', '')
        addin.permissions = manifest.get('permissions', [])
        
        return addin
    
    async def load_all_addins(self) -> int:
        """
        Load all add-ins from the add-ins directory.
        
        Returns:
            Number of successfully loaded add-ins
        """
        if not self.addins_dir.exists():
            logger.warning(f"Add-ins directory not found: {self.addins_dir}")
            return 0
        
        registry = get_registry()
        loaded = 0
        
        for addin_dir in self.addins_dir.iterdir():
            if addin_dir.is_dir():
                addin = await self.load_addin(addin_dir)
                if addin:
                    success = await registry.register(addin)
                    if success:
                        loaded += 1
        
        logger.info(f"Loaded {loaded} add-ins")
        return loaded
