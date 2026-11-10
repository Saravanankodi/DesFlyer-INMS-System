"""Vercel serverless entry point for the INMS Flask application.

Vercel's Python runtime imports this module and looks for a WSGI callable
named ``app``.  The real application lives in ``app.py`` at the project root;
this file only makes sure that directory is importable.

Nothing here changes the application behaviour - every route, template,
validation rule and Firebase call is exactly the same as in local development.
"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Re-exported for Vercel: `app` is the WSGI application.
from app import app  # noqa: E402,F401
