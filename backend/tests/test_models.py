"""Model selection: Gemini options, availability, error handling. No network access or real API key is used."""
import pytest

from app.config import DEFAULT_MODELS, ModelSpec, Settings
from app.container import get_container
from app.providers.generators import LangChainGenerator, ModelCatalog, ModelUnavailable, content_text

GEMINI_IDS = ["gemini-3.5-flash-lite"]


def settings(**kw):
    return Settings(_env_file=None, **kw)


def test_default_catalog_offers_gemini_next_to_local_models():
    by_id = {m.id: m for m in DEFAULT_MODELS}
    for model_id in GEMINI_IDS:
        assert by_id[model_id].provider == "gemini" and "cloud" in by_id[model_id].label.lower()
    assert {"llama3.1-8b", "qwen2.5-7b", "mistral-7b", "extractive"} <= set(by_id)
    assert [m.id for m in DEFAULT_MODELS if m.default] == ["llama3.1-8b"]  # open-source model stays the default


def test_gemini_availability_depends_on_the_api_key():
    spec = next(m for m in DEFAULT_MODELS if m.id == "gemini-3.5-flash-lite")
    missing = ModelCatalog(DEFAULT_MODELS, settings()).describe(spec)
    assert missing["available"] is False and "GOOGLE_API_KEY" in missing["unavailable_reason"] and missing["local"] is False
    present = ModelCatalog(DEFAULT_MODELS, settings(google_api_key="fake-key")).describe(spec)
    assert present["available"] is True and present["unavailable_reason"] is None


def test_local_models_are_marked_local_and_available():
    cat = ModelCatalog(DEFAULT_MODELS, settings())
    for spec in DEFAULT_MODELS:
        if spec.provider in ("ollama", "extractive"):
            d = cat.describe(spec)
            assert d["local"] is True and d["available"] is True


def test_gemini_key_can_come_from_either_env_name(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-gemini-name")  # GOOGLE_API_KEY is empty in the test environment
    assert Settings(_env_file=None).gemini_key == "from-gemini-name"
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "from-google-name")
    assert Settings(_env_file=None).gemini_key == "from-google-name"
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    assert Settings(_env_file=None).gemini_key is None  # empty strings count as not configured


def test_catalog_refuses_gemini_without_key_and_builds_it_with_one():
    with pytest.raises(ModelUnavailable, match="GOOGLE_API_KEY"):
        ModelCatalog(DEFAULT_MODELS, settings()).get("gemini-3.5-flash-lite")
    generator = ModelCatalog(DEFAULT_MODELS, settings(google_api_key="fake-key")).get("gemini-3.5-flash-lite")  # no network until invoked
    assert isinstance(generator, LangChainGenerator)


def test_models_config_can_pin_a_gemini_model(tmp_path):
    path = tmp_path / "models.json"
    path.write_text('[{"id": "g-pinned", "label": "Pinned", "provider": "gemini", "name": "gemini-3.5-flash", "default": true}]')
    cfg = settings(models_config=str(path))
    assert [m.id for m in cfg.models] == ["g-pinned"] and cfg.models[0].name == "gemini-3.5-flash"


def test_content_text_handles_string_and_part_lists():
    assert content_text("  hello ") == "hello"
    assert content_text([{"type": "text", "text": "a"}, {"type": "image_url", "image_url": "x"}, "b", {"text": "c"}]) == "abc"
    assert content_text(None) == "" and content_text([]) == ""


class FakeChat:
    def __init__(self, content):
        self.content, self.calls = content, []

    def invoke(self, messages):
        self.calls.append(messages)
        return type("Msg", (), {"content": self.content})()


def test_langchain_generator_sends_sources_and_parses_part_lists():
    chat = FakeChat([{"type": "text", "text": "Ten days [1]."}])
    from app.domain import Source

    out = LangChainGenerator(chat).generate("How many sick days?", [Source("d", "Leave", "Sick", None, "1", "10 days of sick leave", 0.9)])
    assert out == "Ten days [1]."
    system, human = chat.calls[0]
    assert "ONLY from the numbered sources" in system[1] and "[1] (Leave - Sick)" in human[1] and "How many sick days?" in human[1]


# ---------------- through the API ----------------
def test_api_lists_gemini_models_as_unavailable_without_a_key(client, alice):
    data = client.get("/api/models", headers=alice).json()
    by_id = {m["id"]: m for m in data["models"]}
    for model_id in GEMINI_IDS:
        assert by_id[model_id]["local"] is False and by_id[model_id]["available"] is False
        assert "GOOGLE_API_KEY" in by_id[model_id]["unavailable_reason"]
    assert by_id["extractive"]["available"] is True and by_id["extractive"]["local"] is True
    assert data["default"] == "llama3.1-8b"


def test_api_chat_with_gemini_and_no_key_is_a_clear_503(client, alice):
    r = client.post("/api/chat", headers=alice, json={"question": "How many sick days?", "model_id": "gemini-3.5-flash-lite"})
    assert r.status_code == 503
    assert "GOOGLE_API_KEY" in r.json()["detail"] and "gemini-3.5-flash-lite" in r.json()["detail"]


def test_api_chat_end_to_end_through_a_fake_gemini(client, alice, monkeypatch):
    """With a key configured the request flows through guard, retrieval, generation and verification like any model."""
    from app.config import settings as app_settings

    class FakeGemini:
        def generate(self, question, sources):
            return f"Employees receive 10 days of paid sick leave per year [1]."

    container = get_container()
    monkeypatch.setattr(app_settings, "google_api_key", "fake-key")
    monkeypatch.setitem(container.models._cache, "gemini-3.5-flash-lite", FakeGemini())
    r = client.post("/api/chat", headers=alice, json={"question": "How many days of sick leave do I get?", "model_id": "gemini-3.5-flash-lite"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model_id"] == "gemini-3.5-flash-lite" and not body["abstained"]
    assert body["model_local"] is False  # the UI flags answers produced by cloud models
    assert body["verification"]["passed"] is True and body["sources"][0]["title"] == "Leave Policy"
    listed = {m["id"]: m for m in client.get("/api/models", headers=alice).json()["models"]}
    assert listed["gemini-3.5-flash-lite"]["available"] is True  # the key now makes it selectable


def test_api_provider_failure_does_not_leak_details(client, alice, monkeypatch):
    from app.config import settings as app_settings

    class Exploding:
        def generate(self, question, sources):
            raise RuntimeError("quota exceeded for key AIza-SECRET-VALUE")

    monkeypatch.setattr(app_settings, "google_api_key", "fake-key")
    monkeypatch.setitem(get_container().models._cache, "gemini-3.5-flash-lite", Exploding())
    r = client.post("/api/chat", headers=alice, json={"question": "How many days of sick leave do I get?", "model_id": "gemini-3.5-flash-lite"})
    assert r.status_code == 503
    assert "AIza" not in r.text and "SECRET" not in r.text and "RuntimeError" in r.json()["detail"]
