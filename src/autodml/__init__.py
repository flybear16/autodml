"""autodml - Auto Modeling Definition Language.

Build MDL semantic layer models from Python code,
YAML files, or a live database connection.
"""

__version__ = "0.1.1"

from .model import (
    Calculation,
    Column,
    Manifest,
    Metric,
    Model,
    Relationship,
    View,
)
from .errors import ValidationError

__all__ = [
    "Calculation",
    "Column",
    "Manifest",
    "Metric",
    "Model",
    "Relationship",
    "View",
    "ValidationError",
    "__version__",
]
