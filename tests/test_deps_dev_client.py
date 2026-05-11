"""Unit tests for DepsDevClient — all HTTP calls are mocked."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest.mock import patch

import pytest

from nfr_review.deps_dev_client import DepsDevClient


@pytest.fixture()
def client() -> DepsDevClient:
    return DepsDevClient(timeout=5)


# ── helpers ──────────────────────────────────────────────────────────────


def _mock_response(body: bytes, status: int = 200) -> io.BytesIO:
    """Return a file-like object that ``urlopen`` context-manager yields."""
    resp = io.BytesIO(body)
    resp.status = status
    resp.headers = {}
    return resp


# ── get_package_versions ─────────────────────────────────────────────────


class TestGetPackageVersions:
    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_success(self, mock_urlopen, client):
        payload = {
            "packageKey": {"system": "PYPI", "name": "requests"},
            "versions": [
                {
                    "versionKey": {"version": "2.31.0"},
                    "publishedAt": "2023-05-22T00:00:00Z",
                },
            ],
        }
        mock_urlopen.return_value.__enter__ = lambda s: _mock_response(
            json.dumps(payload).encode()
        )
        mock_urlopen.return_value.__exit__ = lambda s, *a: None

        result = client.get_package_versions("pypi", "requests")
        assert result is not None
        assert result["versions"][0]["versionKey"]["version"] == "2.31.0"

    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_http_404_returns_none(self, mock_urlopen, client):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.deps.dev/v3alpha/systems/pypi/packages/nonexistent",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=io.BytesIO(b""),
        )
        assert client.get_package_versions("pypi", "nonexistent") is None

    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_http_500_returns_none(self, mock_urlopen, client):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.deps.dev/v3alpha/systems/pypi/packages/requests",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=io.BytesIO(b""),
        )
        assert client.get_package_versions("pypi", "requests") is None

    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_url_error_returns_none(self, mock_urlopen, client):
        mock_urlopen.side_effect = urllib.error.URLError("timed out")
        assert client.get_package_versions("pypi", "requests") is None

    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_malformed_json_returns_none(self, mock_urlopen, client):
        mock_urlopen.return_value.__enter__ = lambda s: _mock_response(
            b"not valid json {{{",
        )
        mock_urlopen.return_value.__exit__ = lambda s, *a: None
        assert client.get_package_versions("pypi", "requests") is None

    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_empty_body_returns_none(self, mock_urlopen, client):
        mock_urlopen.return_value.__enter__ = lambda s: _mock_response(b"")
        mock_urlopen.return_value.__exit__ = lambda s, *a: None
        assert client.get_package_versions("pypi", "requests") is None


# ── get_version_info ─────────────────────────────────────────────────────


class TestGetVersionInfo:
    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_success(self, mock_urlopen, client):
        payload = {
            "versionKey": {
                "system": "PYPI",
                "name": "requests",
                "version": "2.31.0",
            },
            "publishedAt": "2023-05-22T00:00:00Z",
        }
        mock_urlopen.return_value.__enter__ = lambda s: _mock_response(
            json.dumps(payload).encode()
        )
        mock_urlopen.return_value.__exit__ = lambda s, *a: None

        result = client.get_version_info("pypi", "requests", "2.31.0")
        assert result is not None
        assert result["versionKey"]["version"] == "2.31.0"

    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_http_error_returns_none(self, mock_urlopen, client):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=io.BytesIO(b""),
        )
        assert client.get_version_info("pypi", "foo", "1.0") is None


# ── get_dependencies ─────────────────────────────────────────────────────


class TestGetDependencies:
    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_success(self, mock_urlopen, client):
        payload = {
            "nodes": [
                {"versionKey": {"system": "PYPI", "name": "urllib3"}},
                {"versionKey": {"system": "PYPI", "name": "certifi"}},
            ],
        }
        mock_urlopen.return_value.__enter__ = lambda s: _mock_response(
            json.dumps(payload).encode()
        )
        mock_urlopen.return_value.__exit__ = lambda s, *a: None

        result = client.get_dependencies("pypi", "requests", "2.31.0")
        assert result is not None
        assert len(result) == 2
        assert result[0]["versionKey"]["name"] == "urllib3"

    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_http_error_returns_none(self, mock_urlopen, client):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="",
            code=500,
            msg="Server Error",
            hdrs={},
            fp=io.BytesIO(b""),
        )
        assert client.get_dependencies("pypi", "requests", "2.31.0") is None

    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_timeout_returns_none(self, mock_urlopen, client):
        mock_urlopen.side_effect = urllib.error.URLError("timed out")
        assert client.get_dependencies("pypi", "requests", "2.31.0") is None

    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_missing_nodes_key_returns_empty(self, mock_urlopen, client):
        mock_urlopen.return_value.__enter__ = lambda s: _mock_response(
            json.dumps({"edges": []}).encode()
        )
        mock_urlopen.return_value.__exit__ = lambda s, *a: None
        result = client.get_dependencies("pypi", "requests", "2.31.0")
        assert result == []


# ── URL encoding ─────────────────────────────────────────────────────────


class TestUrlEncoding:
    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_scoped_npm_package_encoded(self, mock_urlopen, client):
        payload = {"packageKey": {"name": "@scope/pkg"}, "versions": []}
        mock_urlopen.return_value.__enter__ = lambda s: _mock_response(
            json.dumps(payload).encode()
        )
        mock_urlopen.return_value.__exit__ = lambda s, *a: None

        client.get_package_versions("npm", "@scope/pkg")
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        url = req.full_url if hasattr(req, "full_url") else str(req)
        assert "%40scope%2Fpkg" in url

    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_version_with_plus_encoded(self, mock_urlopen, client):
        payload = {"versionKey": {"version": "1.0+build"}}
        mock_urlopen.return_value.__enter__ = lambda s: _mock_response(
            json.dumps(payload).encode()
        )
        mock_urlopen.return_value.__exit__ = lambda s, *a: None

        client.get_version_info("npm", "pkg", "1.0+build")
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        url = req.full_url if hasattr(req, "full_url") else str(req)
        assert "1.0%2Bbuild" in url


# ── logging on failure ───────────────────────────────────────────────────


class TestLogging:
    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_warning_logged_on_http_error(self, mock_urlopen, client, caplog):
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="",
            code=503,
            msg="Unavailable",
            hdrs={},
            fp=io.BytesIO(b""),
        )
        with caplog.at_level("DEBUG", logger="nfr_review.deps_dev_client"):
            client.get_package_versions("pypi", "requests")
        assert "deps.dev lookup failed" in caplog.text
        assert "503" in caplog.text

    @patch("nfr_review.deps_dev_client.urllib.request.urlopen")
    def test_warning_logged_on_timeout(self, mock_urlopen, client, caplog):
        mock_urlopen.side_effect = urllib.error.URLError("timed out")
        with caplog.at_level("DEBUG", logger="nfr_review.deps_dev_client"):
            client.get_package_versions("pypi", "requests")
        assert "deps.dev lookup failed" in caplog.text
        assert "timed out" in caplog.text
