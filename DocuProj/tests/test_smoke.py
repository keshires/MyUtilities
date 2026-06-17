def test_pydantic_importable():
    import pydantic

    assert pydantic.VERSION.startswith("2")
