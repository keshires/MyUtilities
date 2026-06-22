from engine.parsers._consts import build_const_map, resolve_expr
from engine.parsers._support import python_parser, walk


def test_build_const_map(tmp_path):
    (tmp_path / "c.py").write_text(
        'CTX = "/entity/v1"\nVER = "/v2"\nNOT_STR = 5\n', encoding="utf-8"
    )
    consts = build_const_map(tmp_path)
    assert consts["CTX"] == "/entity/v1"
    assert consts["VER"] == "/v2"
    assert "NOT_STR" not in consts


def _first_router_arg(src):
    """Parse src and return the first argument node of the first call."""
    root = python_parser().parse(src.encode()).root_node
    for n in walk(root):
        if n.type == "call":
            args = n.child_by_field_name("arguments")
            return [c for c in args.children if c.type not in ("(", ")", ",")][0]
    return None


def test_resolve_expr_string_identifier_and_concat():
    consts = {"CTX": "/entity/v1", "VER": "/v2"}
    assert resolve_expr(_first_router_arg('f("/literal")'), consts) == "/literal"
    assert resolve_expr(_first_router_arg("f(CTX)"), consts) == "/entity/v1"
    assert resolve_expr(_first_router_arg('f(CTX + VER + "/resolve")'), consts) == "/entity/v1/v2/resolve"
    assert resolve_expr(_first_router_arg("f(unknown_name)"), consts) is None
