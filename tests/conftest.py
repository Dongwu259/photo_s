"""Shared pytest configuration for the PhotoS test suite.

Puts the repository root on sys.path once, so tests can import photo_s
without each file repeating a module-level sys.path.insert/append (those
pollute every other session that imports the test package).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
