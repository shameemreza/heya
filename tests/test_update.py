from heya.update import is_newer


def test_is_newer_true_when_latest_greater():
    assert is_newer("0.0.3", "0.0.2") is True
    assert is_newer("1.0.1", "1.0") is True
    assert is_newer("0.1.0", "0.0.9") is True


def test_is_newer_false_when_same_or_older():
    assert is_newer("0.0.2", "0.0.2") is False
    assert is_newer("0.0.1", "0.0.2") is False
    assert is_newer("1.0", "1.0.1") is False


def test_is_newer_handles_prerelease_and_garbage():
    # numeric part wins; trailing suffix is ignored for the compare
    assert is_newer("0.2.0rc1", "0.1.9") is True
    # malformed input never raises, returns False
    assert is_newer("not-a-version", "0.0.2") is False
    assert is_newer(None, "0.0.2") is False
