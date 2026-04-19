from bin.slug import slugify


def test_basic() -> None:
    assert slugify("fix checkout 500") == "fix-checkout-500"


def test_strips_unicode() -> None:
    assert slugify("café ☕ demo") == "cafe-demo"


def test_collapses_spaces() -> None:
    assert slugify("  hello   world  ") == "hello-world"


def test_removes_punctuation() -> None:
    assert slugify("what?! bug: foo/bar") == "what-bug-foo-bar"


def test_limits_length() -> None:
    long = "a" * 100
    assert len(slugify(long)) <= 60


def test_empty_returns_untitled() -> None:
    assert slugify("") == "untitled"


def test_all_punctuation_returns_untitled() -> None:
    assert slugify("!!!???") == "untitled"
