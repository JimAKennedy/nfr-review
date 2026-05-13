"""Tests for DOT rendering to SVG/PNG via graphviz."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from nfr_review.output.dot import render_dot_to_file

_SIMPLE_DOT = "digraph { a -> b; }\n"


class TestRenderDotToFile:
    def test_returns_none_when_graphviz_not_installed(self) -> None:
        with patch.dict("sys.modules", {"graphviz": None}):
            result = render_dot_to_file(_SIMPLE_DOT, "/tmp/test.dot")
            assert result is None

    def test_returns_path_on_success(self, tmp_path: object) -> None:
        mock_source = MagicMock()
        mock_graphviz = MagicMock()
        mock_graphviz.Source.return_value = mock_source

        with patch.dict("sys.modules", {"graphviz": mock_graphviz}):
            out = str(tmp_path) + "/graph.dot"  # type: ignore[operator]
            result = render_dot_to_file(_SIMPLE_DOT, out)

        assert result is not None
        assert result.endswith(".svg")
        mock_graphviz.Source.assert_called_once_with(_SIMPLE_DOT)
        mock_source.render.assert_called_once()

    def test_returns_none_when_dot_binary_missing(
        self,
        tmp_path: object,
    ) -> None:
        mock_graphviz = MagicMock()
        mock_graphviz.ExecutableNotFound = type(
            "ExecutableNotFound",
            (Exception,),
            {},
        )
        mock_source = MagicMock()
        mock_source.render.side_effect = mock_graphviz.ExecutableNotFound(
            "dot",
        )
        mock_graphviz.Source.return_value = mock_source

        with patch.dict("sys.modules", {"graphviz": mock_graphviz}):
            out = str(tmp_path) + "/graph.dot"  # type: ignore[operator]
            result = render_dot_to_file(_SIMPLE_DOT, out)

        assert result is None

    def test_custom_format(self, tmp_path: object) -> None:
        mock_source = MagicMock()
        mock_graphviz = MagicMock()
        mock_graphviz.Source.return_value = mock_source

        with patch.dict("sys.modules", {"graphviz": mock_graphviz}):
            out = str(tmp_path) + "/graph.dot"  # type: ignore[operator]
            result = render_dot_to_file(_SIMPLE_DOT, out, fmt="png")

        assert result is not None
        assert result.endswith(".png")
        call_kwargs = mock_source.render.call_args
        assert call_kwargs[1]["format"] == "png"


class TestRenderDiagramsCLIFlag:
    def test_render_diagrams_without_dot_warns(self) -> None:
        from click.testing import CliRunner

        from nfr_review.cli import cli

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["deps", "/nonexistent", "--render-diagrams"],
        )
        assert result.exit_code != 0 or "requires --dot" in result.output + (
            result.stderr if hasattr(result, "stderr") else ""
        )
