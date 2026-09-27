"""Check durable, per-line community notes."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

import main
from models import Base


class CommentTests(unittest.TestCase):
    def test_comment_persists_only_on_its_line(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine(f"sqlite:///{Path(directory) / 'test.db'}")
            Base.metadata.create_all(engine)
            session_factory = sessionmaker(bind=engine)
            request = Request({"type": "http", "client": ("test-client", 1234), "headers": []})
            main._comment_times.clear()
            with patch.object(main, "SessionLocal", session_factory):
                posted = main.add_route_comment(
                    "bata-libertad",
                    main.CommentInput(author="Local Rider", body="Jeep passed beside Ayala this morning."),
                    request,
                )
                self.assertEqual(posted["author"], "Local Rider")
                self.assertEqual(len(main.route_comments("bata-libertad")["comments"]), 1)
                self.assertEqual(main.route_comments("granada-burgos")["comments"], [])
                with self.assertRaises(HTTPException) as error:
                    main.route_comments("unknown-line")
                self.assertEqual(error.exception.status_code, 404)
            engine.dispose()
