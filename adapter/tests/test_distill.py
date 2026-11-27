from adapter import distill


def test_aggregate_matches_council_formula():
    assert distill.aggregate([]) == {"bias": 0.0, "conviction": 0.0}
    r = distill.aggregate([1, 1, 1])
    assert r["bias"] == 1.0 and r["conviction"] == 1.0
    split = distill.aggregate([1, -1])
    assert split["bias"] == 0.0 and split["conviction"] == 0.0


def test_post_texts_and_lexicon():
    actions = [
        {"action_type": "CREATE_POST", "action_args": {"content": "Buying this breakout, bullish"}},
        {"action_type": "CREATE_COMMENT", "action_args": {"content": "Looks like a bull trap, I'd sell"}},
        {"action_type": "LIKE_POST", "action_args": {"post_id": 1}},
        {"action_type": "CREATE_POST", "action_args": {"content": "fail"}, "success": False},
    ]
    texts = distill.post_texts(actions)
    assert len(texts) == 2
    r = distill.distill_lexicon(texts)
    assert r["method"] == "lexicon" and -1 <= r["bias"] <= 1 and 0 <= r["conviction"] <= 1


def test_llm_distill_parses_and_falls_back():
    r = distill.distill_llm(["a", "b"], "BTC", lambda m: "[0.5, 0.7]")
    assert r["method"] == "llm" and r["bias"] == 0.6
    assert distill.distill_llm(["a", "b"], "BTC", lambda m: "no json") is None
    assert distill.distill_llm([], "BTC", lambda m: "[1]") is None
