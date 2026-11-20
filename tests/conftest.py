import sys
import types as module_types
from types import SimpleNamespace

import pytest

from orchestrator.engine import MockEngine
from orchestrator.pipeline import build_job


TOPIC = "Why is Netflix cheaper than cable TV?"


def make_job(target_seconds: float = 35.0) -> dict:
    engine = MockEngine()
    research = engine.research(TOPIC)
    hook = engine.hook(TOPIC, research)
    script = engine.write_script(TOPIC, research, hook, target_seconds)
    plan = engine.breakdown(TOPIC, research, hook, script, target_seconds)
    return build_job(
        TOPIC,
        research,
        hook,
        script,
        plan,
        provider="offline",
        model="mock",
        mode="mock",
        target_seconds=target_seconds,
    )


@pytest.fixture
def valid_job() -> dict:
    return make_job()


def make_response(text="ok", parsed=None, candidates=None, prompt_feedback=None):
    if candidates is None:
        candidates = [SimpleNamespace(grounding_metadata=None)]
    return SimpleNamespace(
        text=text,
        parsed=parsed,
        candidates=candidates,
        prompt_feedback=prompt_feedback,
    )


def grounding_response(chunks, text="research notes"):
    candidates = [
        SimpleNamespace(
            grounding_metadata=SimpleNamespace(
                grounding_chunks=[
                    SimpleNamespace(web=SimpleNamespace(uri=uri, title=title, domain=domain))
                    for uri, title, domain in chunks
                ]
            )
        )
    ]
    return make_response(text=text, candidates=candidates)


class FakeApiError(Exception):
    def __init__(self, code, message="fake api error"):
        super().__init__(message)
        self.code = code


@pytest.fixture
def fake_sdk(monkeypatch):
    """Inject a fake google-genai SDK so GeminiClient never touches the network."""
    types_mod = module_types.ModuleType("google.genai.types")

    class GenerateContentConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class GoogleSearch:
        pass

    class Tool:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    types_mod.GenerateContentConfig = GenerateContentConfig
    types_mod.GoogleSearch = GoogleSearch
    types_mod.Tool = Tool

    state = SimpleNamespace(responses=[], calls=[], api_key=None)

    class FakeModels:
        def generate_content(self, *, model, contents, config):
            state.calls.append(SimpleNamespace(model=model, contents=contents, config=config))
            if not state.responses:
                raise AssertionError("fake SDK ran out of scripted responses")
            item = state.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    class FakeClient:
        def __init__(self, api_key=None):
            state.api_key = api_key
            self.models = FakeModels()

    genai_mod = module_types.ModuleType("google.genai")
    genai_mod.Client = FakeClient
    genai_mod.types = types_mod

    google_mod = module_types.ModuleType("google")
    google_mod.genai = genai_mod

    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)
    return state


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr("orchestrator.gemini.time.sleep", sleeps.append)
    return sleeps