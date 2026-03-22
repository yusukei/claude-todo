"""Tests for CLI init-admin command."""

from unittest.mock import AsyncMock, patch

import pytest

from app.cli import create_admin_user
from app.models.user import AuthType, User


class TestCreateAdminUser:
    """Test core create_admin_user logic (DB already connected via conftest)."""

    async def test_creates_admin_user(self):
        await create_admin_user("newadmin@test.com", "securepass", "New Admin")

        user = await User.find_one(User.email == "newadmin@test.com")
        assert user is not None
        assert user.name == "New Admin"
        assert user.auth_type == AuthType.admin
        assert user.is_admin is True
        assert user.is_active is True
        assert user.password_hash is not None

    async def test_password_is_hashed(self):
        await create_admin_user("admin@test.com", "mypassword", "Admin")

        user = await User.find_one(User.email == "admin@test.com")
        assert user.password_hash != "mypassword"
        assert user.password_hash.startswith("$2b$")

    async def test_skips_existing_user(self, capsys):
        await create_admin_user("dup@test.com", "password1", "First")
        await create_admin_user("dup@test.com", "password2", "Second")

        captured = capsys.readouterr()
        assert "already exists" in captured.out

        users = await User.find(User.email == "dup@test.com").to_list()
        assert len(users) == 1
        assert users[0].name == "First"


class TestCliMain:
    """Test CLI argument parsing and validation."""

    def test_init_admin_with_args(self):
        from app.cli import main

        mock_init = AsyncMock()
        with patch("sys.argv", ["cli", "init-admin", "--email", "cli@test.com", "--password", "longpassword", "--name", "CLI Admin"]), \
             patch("app.cli._init_admin", mock_init):
            main()

        mock_init.assert_called_once_with("cli@test.com", "longpassword", "CLI Admin")

    def test_init_admin_short_password(self, capsys):
        from app.cli import main

        with patch("sys.argv", ["cli", "init-admin", "--email", "x@test.com", "--password", "12345"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

        captured = capsys.readouterr()
        assert "at least 6 characters" in captured.err

    def test_no_command_shows_help(self):
        from app.cli import main

        with patch("sys.argv", ["cli"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 1

    def test_init_admin_from_env(self):
        from app.cli import main

        mock_init = AsyncMock()
        with patch("sys.argv", ["cli", "init-admin"]), \
             patch("app.cli.settings") as mock_settings, \
             patch("app.cli._init_admin", mock_init):
            mock_settings.INIT_ADMIN_EMAIL = "env@test.com"
            mock_settings.INIT_ADMIN_PASSWORD = "envpassword"
            main()

        mock_init.assert_called_once_with("env@test.com", "envpassword", "Admin")
