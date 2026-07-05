from checks.check_book_contents import _is_json_object_string


def test_json_object_string():
    assert _is_json_object_string('{"text":"Hi"}')


def test_json_array_string():
    assert _is_json_object_string('[{"text":"a"},"b"]')


def test_bare_text_is_not_json():
    assert not _is_json_object_string("Hello world")


def test_bare_number_is_not_json():
    assert not _is_json_object_string("42")


def test_empty_is_not_json():
    assert not _is_json_object_string("")
    assert not _is_json_object_string("   ")


def test_malformed_json_is_not_json():
    assert not _is_json_object_string("{unterminated")
    assert not _is_json_object_string("{'single_quotes':true}")
