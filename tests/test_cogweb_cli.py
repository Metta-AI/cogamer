"""Tests for cogweb CLI — argument parsing and command dispatch."""
from __future__ import annotations

import os
from unittest.mock import patch

from cogweb.cli import build_parser, main, _pid_file, _read_pid, _write_pid, _remove_pid, _ensure_built


# --- Argument parsing ---


def test_no_args_prints_help():
    """No subcommand returns 0 (prints help)."""
    assert main([]) == 0


def test_start_default_port():
    parser = build_parser()
    args = parser.parse_args(["start"])
    assert args.command == "start"
    assert args.port == 8787
    assert args.open is False


def test_start_custom_port():
    parser = build_parser()
    args = parser.parse_args(["start", "--port", "9000"])
    assert args.port == 9000


def test_start_with_open():
    parser = build_parser()
    args = parser.parse_args(["start", "--open"])
    assert args.open is True


def test_stop_default_port():
    parser = build_parser()
    args = parser.parse_args(["stop"])
    assert args.command == "stop"
    assert args.port == 8787


def test_restart_custom_port():
    parser = build_parser()
    args = parser.parse_args(["restart", "--port", "9999"])
    assert args.command == "restart"
    assert args.port == 9999


def test_ui_subcommand():
    parser = build_parser()
    args = parser.parse_args(["ui", "--port", "3000"])
    assert args.command == "ui"
    assert args.port == 3000


# --- Auto-build ---


def test_ensure_built_skips_when_dist_exists():
    """If dist/index.html exists, _ensure_built returns True without building."""
    with patch("cogweb.cli._DIST_INDEX") as mock_index:
        mock_index.exists.return_value = True
        assert _ensure_built() is True


def test_ensure_built_falls_back_when_no_app_dir():
    """If app/ doesn't exist, _ensure_built returns True (legacy fallback)."""
    with patch("cogweb.cli._DIST_INDEX") as mock_index, \
         patch("cogweb.cli._APP_DIR") as mock_app:
        mock_index.exists.return_value = False
        mock_app.exists.return_value = False
        assert _ensure_built() is True


# --- PID file management ---


def test_pid_file_path():
    pf = _pid_file(8787)
    assert pf.name == "cogweb-8787.pid"
    assert ".cogweb" in str(pf)


def test_write_read_remove_pid(tmp_path):
    """Write, read, and remove a PID file."""
    with patch("cogweb.cli._PID_DIR", tmp_path):
        # Nothing initially
        assert _read_pid(5555) is None

        # Write our own PID (guaranteed to exist)
        _write_pid(5555, os.getpid())
        assert _read_pid(5555) == os.getpid()

        # Remove
        _remove_pid(5555)
        assert _read_pid(5555) is None


def test_read_pid_stale_process(tmp_path):
    """Stale PID file (dead process) returns None and cleans up."""
    with patch("cogweb.cli._PID_DIR", tmp_path):
        # Write a PID that definitely doesn't exist
        _write_pid(5555, 999999999)
        assert _read_pid(5555) is None
        # PID file should be cleaned up
        assert not _pid_file(5555).exists()


# --- Stop when not running ---


def test_stop_not_running():
    """Stop with no server returns 1."""
    with patch("cogweb.cli._read_pid", return_value=None):
        assert main(["stop", "--port", "7777"]) == 1


# --- Start duplicate detection ---


def test_start_already_running():
    """Start when already running returns 1."""
    with patch("cogweb.cli._read_pid", return_value=12345):
        assert main(["start", "--port", "7777"]) == 1
