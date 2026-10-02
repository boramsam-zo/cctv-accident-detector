from unittest.mock import Mock, patch

from google.genai.errors import APIError
import pytest

from scripts.build_rag_index import embed_batch


def test_rate_limit_retries_after_server_delay():
    client = Mock()
    client.models.embed_content.side_effect = [APIError(429, {"error": {"details": [
        {"@type": "google.rpc.RetryInfo", "retryDelay": "35s"}]}}), "result"]
    with patch("scripts.build_rag_index.time.sleep") as sleep:
        assert embed_batch(client, model="model", contents=["text"], config={}) == "result"
    sleep.assert_called_once_with(36)
    assert client.models.embed_content.call_count == 2


@pytest.mark.parametrize("code", [403, 429])
def test_permanent_or_unclassified_quota_error_is_not_retried(code):
    client = Mock()
    client.models.embed_content.side_effect = APIError(code, {})
    with patch("scripts.build_rag_index.time.sleep") as sleep, pytest.raises(APIError):
        embed_batch(client, model="model", contents=["text"], config={})
    sleep.assert_not_called()
