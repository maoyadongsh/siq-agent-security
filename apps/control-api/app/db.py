"""数据库引擎与会话。

生产：PostgreSQL + Alembic 迁移（禁止 create_all）。
开发：SQLite 仅显式开关允许，create_all 仅 dev_mode。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory: sessionmaker[Session] | None = None


def init_db(settings: Settings) -> None:
    global _engine, _session_factory
    kwargs: dict = {"pool_pre_ping": True}
    if settings.is_sqlite:
        kwargs["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(settings.database_url, **kwargs)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)


def get_engine():
    assert _engine is not None, "init_db 未调用"
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    assert _session_factory is not None, "init_db 未调用"
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务性会话：提交成功或回滚，不向调用方泄漏。"""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI 依赖：请求级会话，路由自行 commit（同事务审计 + outbox）。"""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
