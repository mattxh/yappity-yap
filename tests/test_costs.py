from app.costs import estimate_cost


def test_cost_uses_model_rate():
    # 60s of gpt-4o-transcribe at $0.006/min = $0.006, no cleanup
    assert estimate_cost(60, "gpt-4o-transcribe", cleanup=False) == 0.006


def test_cost_adds_cleanup_flat():
    c_no = estimate_cost(60, "gpt-4o-transcribe", cleanup=False)
    c_yes = estimate_cost(60, "gpt-4o-transcribe", cleanup=True)
    assert c_yes > c_no


def test_cost_cheaper_model():
    assert estimate_cost(60, "gpt-4o-mini-transcribe", cleanup=False) < \
        estimate_cost(60, "gpt-4o-transcribe", cleanup=False)


def test_cost_unknown_model_uses_default():
    assert estimate_cost(60, "some-future-model", cleanup=False) == 0.006


def test_cost_zero_duration():
    assert estimate_cost(0, "gpt-4o-transcribe", cleanup=False) == 0.0
