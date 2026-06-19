from engine.parsers._support import python_parser, str_literal, text, walk


def test_python_parser_parses_and_helpers_work():
    parser = python_parser()
    tree = parser.parse(b'x = "hello"\n')
    root = tree.root_node
    assert root.type == "module"
    strings = [n for n in walk(root) if n.type == "string"]
    assert len(strings) == 1
    assert str_literal(strings[0]) == "hello"
    assert text(strings[0]).startswith('"')
