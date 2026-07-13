"""Database primitives shared by every application component."""

from course_platform.db.base import Base
from course_platform.db.session import create_engine, create_session_factory, session_scope

__all__ = ["Base", "create_engine", "create_session_factory", "session_scope"]
