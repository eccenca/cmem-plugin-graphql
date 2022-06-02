"""Testing utilities."""
import os

import pytest

# check for cmem environment and skip if not present
from _pytest.mark import MarkDecorator

needs_cmem: MarkDecorator = pytest.mark.skipif(
    "CMEM_BASE_URI" not in os.environ, reason="Needs CMEM configuration"
)
