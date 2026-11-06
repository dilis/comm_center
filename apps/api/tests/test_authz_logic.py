from app.authz import AuthUser, is_subset


def test_is_subset():
    assert is_subset({("a", "x")}, {("a", "x"), ("b", "y")})
    assert is_subset(set(), set())
    assert not is_subset({("a", "x"), ("c", "z")}, {("a", "x")})


def test_auth_user_can():
    user = AuthUser(id=5, permissions=frozenset({("messages", "read_own")}))
    assert user.can("messages", "read_own")
    assert not user.can("messages", "read_all")


def test_read_all_covers_narrower_reads_in_the_escalation_check():
    held = {("messages", "read_all")}
    assert is_subset({("messages", "read_own"), ("messages", "read_received")}, held)
    assert not is_subset({("contacts", "read_own")}, held)  # only the same resource
    assert not is_subset({("messages", "update")}, held)
    assert not is_subset({("messages", "read_all")}, {("messages", "read_own")})  # never upward
