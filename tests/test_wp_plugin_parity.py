"""The uploadable plugin must stay byte-identical to the mu-plugin below its header.

Both forms of perkins-jsonld ship the same hooks; only the header differs (mu-plugins load
without a Plugin Name, wp-admin uploads require one). They drifted once on 2026-07-29: the
post-type fix landed in the mu-plugin while the plugin copy kept `register_post_meta('post',
...)`, referenced an undefined PERKINS_JSONLD_POST_TYPES, and carried an unmatched brace that
made it fail to parse. Nothing caught it because nothing compared them.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MU = ROOT / "wp-mu-plugin" / "perkins-jsonld.php"
PLUGIN = ROOT / "wp-plugin" / "perkins-jsonld" / "perkins-jsonld.php"


def _body(path: Path) -> str:
    """Everything after the file's opening header docblock."""
    return path.read_text().split("*/", 1)[1]


def test_plugin_body_matches_mu_plugin():
    assert _body(PLUGIN) == _body(MU), (
        "wp-plugin/perkins-jsonld/perkins-jsonld.php has drifted from "
        "wp-mu-plugin/perkins-jsonld.php. Regenerate it: header + _body(MU)."
    )


def test_plugin_declares_a_plugin_name():
    """Without this line wp-admin refuses the zip; the mu-plugin must NOT have it."""
    assert "Plugin Name:" in PLUGIN.read_text().split("*/", 1)[0]
    assert "Plugin Name:" not in MU.read_text().split("*/", 1)[0]


@pytest.mark.parametrize("path", [MU, PLUGIN])
def test_braces_balance(path):
    """A PHP parse error is otherwise invisible until WordPress fatals on load."""
    depth = 0
    for i, ch in enumerate(src := path.read_text()):
        depth += (ch == "{") - (ch == "}")
        assert depth >= 0, f"{path.name}: unmatched }} on line {src[:i].count(chr(10)) + 1}"
    assert depth == 0, f"{path.name}: {depth} unclosed {{"


@pytest.mark.parametrize("path", [MU, PLUGIN])
def test_registers_every_post_type_projects_can_use(path):
    """Articles are 'post'; the generated portfolio is 'avada_portfolio'; the nine public
    project write-ups are 'page'. Registering a subset silently drops meta writes: WordPress
    returns 200 for a write to an unregistered key and stores nothing."""
    src = path.read_text()
    assert "define( 'PERKINS_JSONLD_POST_TYPES', [ 'post', 'avada_portfolio', 'page' ] );" in src
    assert "register_post_meta( 'post'," not in src, "hard-coded single post type"
