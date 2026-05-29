"""Tests for storage/database.py CRUD operations."""

from __future__ import annotations

import pytest

from termchat.storage import database
from termchat.storage.models import Chat, Message, Project, ProjectFile


# ── Projects ──────────────────────────────────────────────────────────────────

class TestProjects:
    def test_create_returns_project(self, db):
        p = database.create_project("MyProject", instructions="Do stuff")
        assert isinstance(p, Project)
        assert p.id > 0
        assert p.name == "MyProject"
        assert p.instructions == "Do stuff"
        assert p.created_at is not None

    def test_create_empty_instructions(self, db):
        p = database.create_project("Empty")
        assert p.instructions == ""

    def test_get_project_exists(self, db):
        created = database.create_project("Fetch me")
        fetched = database.get_project(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.name == "Fetch me"

    def test_get_project_not_found(self, db):
        assert database.get_project(9999) is None

    def test_get_project_by_name(self, db):
        database.create_project("FindByName")
        p = database.get_project_by_name("FindByName")
        assert p is not None
        assert p.name == "FindByName"

    def test_get_project_by_name_not_found(self, db):
        assert database.get_project_by_name("Nope") is None

    def test_list_projects_empty(self, db):
        assert database.list_projects() == []

    def test_list_projects_multiple(self, db):
        database.create_project("Alpha")
        database.create_project("Beta")
        projects = database.list_projects()
        assert len(projects) == 2
        names = {p.name for p in projects}
        assert names == {"Alpha", "Beta"}

    def test_update_project_name(self, db):
        p = database.create_project("OldName")
        updated = database.update_project(p.id, name="NewName")
        assert updated is not None
        assert updated.name == "NewName"
        assert updated.instructions == "OldName"[len("OldName"):]  # unchanged

    def test_update_project_instructions(self, db):
        p = database.create_project("P", instructions="old")
        updated = database.update_project(p.id, instructions="new")
        assert updated.instructions == "new"
        assert updated.name == "P"

    def test_update_project_not_found(self, db):
        result = database.update_project(9999, name="Ghost")
        assert result is None

    def test_delete_project_exists(self, db):
        p = database.create_project("ToDelete")
        assert database.delete_project(p.id) is True
        assert database.get_project(p.id) is None

    def test_delete_project_not_found(self, db):
        assert database.delete_project(9999) is False

    def test_duplicate_name_raises(self, db):
        database.create_project("Unique")
        with pytest.raises(Exception):
            database.create_project("Unique")


# ── Project Files ─────────────────────────────────────────────────────────────

class TestProjectFiles:
    def test_add_file(self, db):
        p = database.create_project("Proj")
        f = database.add_project_file(p.id, "main.py", "print('hello')")
        assert isinstance(f, ProjectFile)
        assert f.filename == "main.py"
        assert f.content == "print('hello')"
        assert f.project_id == p.id

    def test_add_file_upserts_on_same_filename(self, db):
        p = database.create_project("Proj")
        database.add_project_file(p.id, "main.py", "v1")
        database.add_project_file(p.id, "main.py", "v2")
        files = database.get_project_files(p.id)
        assert len(files) == 1
        assert files[0].content == "v2"

    def test_get_project_files_empty(self, db):
        p = database.create_project("Proj")
        assert database.get_project_files(p.id) == []

    def test_get_project_files_multiple(self, db):
        p = database.create_project("Proj")
        database.add_project_file(p.id, "a.py", "aaa")
        database.add_project_file(p.id, "b.py", "bbb")
        files = database.get_project_files(p.id)
        assert len(files) == 2
        assert {f.filename for f in files} == {"a.py", "b.py"}

    def test_get_project_files_ordered_by_filename(self, db):
        p = database.create_project("Proj")
        database.add_project_file(p.id, "z.py", "")
        database.add_project_file(p.id, "a.py", "")
        database.add_project_file(p.id, "m.py", "")
        names = [f.filename for f in database.get_project_files(p.id)]
        assert names == sorted(names)

    def test_remove_project_file(self, db):
        p = database.create_project("Proj")
        database.add_project_file(p.id, "del.py", "x")
        assert database.remove_project_file(p.id, "del.py") is True
        assert database.get_project_files(p.id) == []

    def test_remove_project_file_not_found(self, db):
        p = database.create_project("Proj")
        assert database.remove_project_file(p.id, "ghost.py") is False

    def test_files_populated_on_get_project(self, db):
        p = database.create_project("Proj")
        database.add_project_file(p.id, "f.py", "content")
        fetched = database.get_project(p.id)
        assert len(fetched.files) == 1
        assert fetched.files[0].filename == "f.py"

    def test_files_cascade_delete_with_project(self, db):
        p = database.create_project("Proj")
        database.add_project_file(p.id, "f.py", "x")
        database.delete_project(p.id)
        # Files should be gone (CASCADE)
        assert database.get_project_files(p.id) == []


# ── Chats ─────────────────────────────────────────────────────────────────────

class TestChats:
    def test_create_chat_defaults(self, db):
        c = database.create_chat("claude-sonnet-4-6")
        assert isinstance(c, Chat)
        assert c.id > 0
        assert c.model == "claude-sonnet-4-6"
        assert c.provider == "anthropic"
        assert c.project_id is None
        assert c.title is None

    def test_create_chat_with_all_fields(self, db):
        p = database.create_project("P")
        c = database.create_chat("gpt-4", provider="openai", project_id=p.id, title="My Chat")
        assert c.provider == "openai"
        assert c.project_id == p.id
        assert c.title == "My Chat"

    def test_get_chat_exists(self, db):
        created = database.create_chat("model")
        fetched = database.get_chat(created.id)
        assert fetched is not None
        assert fetched.id == created.id

    def test_get_chat_not_found(self, db):
        assert database.get_chat(9999) is None

    def test_list_chats_empty(self, db):
        assert database.list_chats() == []

    def test_list_chats_respects_limit(self, db):
        for _ in range(5):
            database.create_chat("model")
        assert len(database.list_chats(limit=3)) == 3

    def test_list_chats_by_project(self, db):
        p1 = database.create_project("P1")
        p2 = database.create_project("P2")
        database.create_chat("m", project_id=p1.id)
        database.create_chat("m", project_id=p1.id)
        database.create_chat("m", project_id=p2.id)
        assert len(database.list_chats(project_id=p1.id)) == 2
        assert len(database.list_chats(project_id=p2.id)) == 1

    def test_update_chat_title(self, db):
        c = database.create_chat("model")
        database.update_chat_title(c.id, "Great Title")
        assert database.get_chat(c.id).title == "Great Title"

    def test_delete_chat(self, db):
        c = database.create_chat("model")
        assert database.delete_chat(c.id) is True
        assert database.get_chat(c.id) is None

    def test_delete_chat_not_found(self, db):
        assert database.delete_chat(9999) is False

    def test_touch_chat_updates_timestamp(self, db):
        c = database.create_chat("model")
        old_ts = database.get_chat(c.id).updated_at
        database.touch_chat(c.id)
        new_ts = database.get_chat(c.id).updated_at
        # Timestamps can be equal if fast enough; just check no error
        assert new_ts >= old_ts


# ── Messages ──────────────────────────────────────────────────────────────────

class TestMessages:
    def test_add_message_user(self, db):
        c = database.create_chat("model")
        m = database.add_message(c.id, "user", "Hello!")
        assert isinstance(m, Message)
        assert m.role == "user"
        assert m.content == "Hello!"
        assert m.chat_id == c.id
        assert m.input_tokens is None
        assert m.output_tokens is None

    def test_add_message_with_tokens(self, db):
        c = database.create_chat("model")
        m = database.add_message(c.id, "assistant", "Reply", input_tokens=100, output_tokens=50)
        assert m.input_tokens == 100
        assert m.output_tokens == 50

    def test_add_message_invalid_role_raises(self, db):
        c = database.create_chat("model")
        with pytest.raises(Exception):
            database.add_message(c.id, "system", "bad role")

    def test_get_messages_empty(self, db):
        c = database.create_chat("model")
        assert database.get_messages(c.id) == []

    def test_get_messages_ordered(self, db):
        c = database.create_chat("model")
        database.add_message(c.id, "user", "first")
        database.add_message(c.id, "assistant", "second")
        database.add_message(c.id, "user", "third")
        msgs = database.get_messages(c.id)
        assert [m.content for m in msgs] == ["first", "second", "third"]

    def test_messages_cascade_delete_with_chat(self, db):
        c = database.create_chat("model")
        database.add_message(c.id, "user", "hi")
        database.delete_chat(c.id)
        assert database.get_messages(c.id) == []

    def test_delete_messages_before(self, db):
        c = database.create_chat("model")
        m1 = database.add_message(c.id, "user", "one")
        m2 = database.add_message(c.id, "assistant", "two")
        m3 = database.add_message(c.id, "user", "three")
        deleted = database.delete_messages_before(c.id, m3.id)
        assert deleted == 2
        remaining = database.get_messages(c.id)
        assert len(remaining) == 1
        assert remaining[0].id == m3.id

    def test_replace_messages_with_summary(self, db):
        c = database.create_chat("model")
        m1 = database.add_message(c.id, "user", "msg1")
        m2 = database.add_message(c.id, "assistant", "msg2")
        m3 = database.add_message(c.id, "user", "msg3")
        summary = database.replace_messages_with_summary(c.id, m2.id, "Summary text")
        assert summary.role == "summary"
        assert summary.content == "Summary text"
        remaining = database.get_messages(c.id)
        assert len(remaining) == 2
        assert remaining[0].role == "summary"
        assert remaining[1].content == "msg3"

    def test_chat_token_totals_empty(self, db):
        c = database.create_chat("model")
        totals = database.chat_token_totals(c.id)
        assert totals == {"input": 0, "output": 0}

    def test_chat_token_totals(self, db):
        c = database.create_chat("model")
        database.add_message(c.id, "user", "hi", input_tokens=10, output_tokens=0)
        database.add_message(c.id, "assistant", "hello", input_tokens=20, output_tokens=30)
        totals = database.chat_token_totals(c.id)
        assert totals["input"] == 30
        assert totals["output"] == 30

    def test_uninitialised_db_raises(self):
        database._db_path = None
        with pytest.raises(RuntimeError, match="not initialised"):
            database.get_chat(1)
