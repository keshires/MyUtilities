import pd_precheck as p


def test_load_ids_file(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text("A\nB\n\nA\n  C  \n", encoding="utf-8")
    assert p.load_ids_file(str(f)) == {"A", "B", "C"}
