# cassettes/

Recorded HTTP fixtures for provider tests, so they run without a key or a network.

Right now `test_anthropic_provider.py` mocks responses inline with `respx` (simpler
than managing files for a couple of cases). When we have enough recorded fixtures to
be worth it, they land here.
