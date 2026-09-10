"""Tests for the settings store and /api/settings endpoints.

The settings file lives at a controllable path (tests monkeypatch
``backend.settings_store.default_settings_path``); the "missing file == local
default" invariant is covered explicitly.
"""

import json

import pytest

from backend.settings_store import (
    DEFAULT_DATA_MODE,
    AppSettings,
    load_settings,
    save_settings,
)


def _patch_settings_path(monkeypatch, tmp_path, filename="settings.json"):
    """Point default_settings_path at a tmp file and return the path."""
    target = tmp_path / filename

    def _path():
        return str(target)

    monkeypatch.setattr("backend.settings_store.default_settings_path", _path)
    return target


class TestSettingsStore:
    def test_missing_file_is_local_unconfigured(self, tmp_path):
        settings = load_settings(str(tmp_path / "absent.json"))
        assert settings.dataMode == "local"
        assert settings.databaseUrl == ""
        assert settings.configured is False

    def test_save_and_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "settings.json")
        save_settings(
            AppSettings(dataMode="remoto", databaseUrl="postgresql://u:p@host/db", configured=True),
            path=path,
        )
        loaded = load_settings(path)
        assert loaded.dataMode == "remoto"
        assert loaded.databaseUrl == "postgresql://u:p@host/db"
        assert loaded.configured is True

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("{ not json !", encoding="utf-8")
        settings = load_settings(str(path))
        assert settings.dataMode == DEFAULT_DATA_MODE
        assert settings.configured is False

    def test_unknown_datamode_falls_back_to_local(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"dataMode": "marte", "databaseUrl": "x"}), encoding="utf-8")
        settings = load_settings(str(path))
        assert settings.dataMode == "local"
        assert settings.databaseUrl == "x"

    def test_save_overwrites_atomically(self, tmp_path):
        path = tmp_path / "settings.json"
        save_settings(AppSettings(dataMode="local", configured=True), path=str(path))
        save_settings(AppSettings(dataMode="remoto", databaseUrl="postgresql://h/db", configured=True), path=str(path))
        loaded = load_settings(str(path))
        assert loaded.dataMode == "remoto"
        # no leftover temp files
        assert list(tmp_path.glob(".canyp-settings-*.tmp")) == []


class TestSettingsApi:
    def test_get_settings_without_file_returns_local_unconfigured(self, test_client, monkeypatch, tmp_path):
        _patch_settings_path(monkeypatch, tmp_path)
        resp = test_client.get("/api/settings")
        assert resp.status_code == 200
        assert resp.json() == {"dataMode": "local", "databaseUrl": "", "configured": False}

    def test_put_set_remoto_persists_and_marks_configured(self, test_client, monkeypatch, tmp_path):
        target = _patch_settings_path(monkeypatch, tmp_path)
        resp = test_client.put(
            "/api/settings",
            json={"dataMode": "remoto", "databaseUrl": "postgresql://u:p@host/db"},
        )
        assert resp.status_code == 200
        assert resp.json() == {
            "dataMode": "remoto",
            "databaseUrl": "postgresql://u:p@host/db",
            "configured": True,
        }
        # persisted on disk; GET reflects it
        assert json.loads(target.read_text(encoding="utf-8"))["dataMode"] == "remoto"
        assert test_client.get("/api/settings").json()["configured"] is True

    def test_put_remoto_without_url_rejected_422(self, test_client, monkeypatch, tmp_path):
        _patch_settings_path(monkeypatch, tmp_path)
        resp = test_client.put("/api/settings", json={"dataMode": "remoto", "databaseUrl": ""})
        assert resp.status_code == 422

    def test_put_remoto_with_missing_url_rejected_422(self, test_client, monkeypatch, tmp_path):
        _patch_settings_path(monkeypatch, tmp_path)
        resp = test_client.put("/api/settings", json={"dataMode": "remoto"})
        assert resp.status_code == 422

    def test_put_invalid_datamode_rejected_422(self, test_client, monkeypatch, tmp_path):
        _patch_settings_path(monkeypatch, tmp_path)
        resp = test_client.put("/api/settings", json={"dataMode": "orbitar"})
        assert resp.status_code == 422

    def test_put_local_scrubs_remote_url(self, test_client, monkeypatch, tmp_path):
        target = _patch_settings_path(monkeypatch, tmp_path)
        test_client.put("/api/settings", json={"dataMode": "remoto", "databaseUrl": "postgresql://u:p@h/db"})
        resp = test_client.put("/api/settings", json={"dataMode": "local"})
        assert resp.status_code == 200
        assert resp.json()["databaseUrl"] == ""
        assert json.loads(target.read_text(encoding="utf-8"))["databaseUrl"] == ""
        assert resp.json()["configured"] is True


class TestDesktopRunGlue:
    """backend.desktop_run maps persisted settings to DATABASE_URL."""

    def _write_settings(self, monkeypatch, tmp_path, payload):
        target = _patch_settings_path(monkeypatch, tmp_path)
        target.write_text(json.dumps(payload), encoding="utf-8")

    def test_remoto_mode_returns_remote_url(self, monkeypatch, tmp_path):
        self._write_settings(
            monkeypatch,
            tmp_path,
            {"dataMode": "remoto", "databaseUrl": "postgresql://u:p@h/db", "configured": True},
        )
        from backend import desktop_run

        assert desktop_run._remote_database_url_from_settings() == "postgresql://u:p@h/db"

    def test_local_mode_returns_none(self, monkeypatch, tmp_path):
        self._write_settings(
            monkeypatch, tmp_path, {"dataMode": "local", "databaseUrl": "", "configured": True}
        )
        from backend import desktop_run

        assert desktop_run._remote_database_url_from_settings() is None

    def test_missing_file_returns_none(self, monkeypatch, tmp_path):
        _patch_settings_path(monkeypatch, tmp_path)
        from backend import desktop_run

        assert desktop_run._remote_database_url_from_settings() is None