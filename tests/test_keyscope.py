from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from keyscope.env import find_secret, load_env_file
from keyscope.http import ApiError, ApiResponse, _SameHostRedirectHandler
from keyscope.providers import PROVIDERS, PROVIDER_BY_SLUG, audit_provider, normalize_model
from urllib.request import Request


class FakeClient:
    def __init__(self, responses):
        self.responses = {url: list(items) for url, items in responses.items()}
        self.calls = []

    def get_json(self, url, *, headers=None, secret=""):
        self.calls.append((url, headers or {}, secret))
        if url not in self.responses or not self.responses[url]:
            raise AssertionError(f"resposta não configurada para {url}")
        item = self.responses[url].pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def response(data, headers=None):
    return ApiResponse(status=200, data=data, headers=headers or {})


class EnvironmentTests(unittest.TestCase):
    def test_exact_user_aliases_are_supported(self):
        expected = {
            "openai": "openai_proj",
            "anthropic": "anthropic_api_key",
            "openrouter": "openrouter_api_key",
            "groq": "groq_api_key",
            "cerebras": "cerebras_api_key_context",
            "mistral": "mistral_api_key_context",
            "deepseek": "deepseek_api_key_context",
            "together": "together_api_key_context",
            "huggingface": "huggingface",
            "replicate": "replicate_api_token",
        }
        for slug, alias in expected.items():
            with self.subTest(slug=slug):
                self.assertIn(alias, PROVIDER_BY_SLUG[slug].aliases)

    def test_find_secret_is_case_insensitive(self):
        secret, source = find_secret(("OPENAI_API_KEY",), {"openai_api_key": " sk-test "})
        self.assertEqual(secret, "sk-test")
        self.assertEqual(source, "openai_api_key")

    def test_env_file_does_not_override_existing_value(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text('OPENAI_API_KEY="from-file"\nGROQ_API_KEY=groq-file\n', encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "from-shell"}, clear=True):
                load_env_file(env_path)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "from-shell")
                self.assertEqual(os.environ["GROQ_API_KEY"], "groq-file")


class NormalizationTests(unittest.TestCase):
    def test_normalizes_model_metadata(self):
        model = normalize_model(
            {
                "id": "vendor/model",
                "display_name": "Model",
                "organization": "vendor",
                "context_length": 32768,
                "pricing": {"input": 1, "output": 2},
                "capabilities": {"vision": True},
            }
        )
        self.assertEqual(model["id"], "vendor/model")
        self.assertEqual(model["owner"], "vendor")
        self.assertEqual(model["context_length"], 32768)
        self.assertEqual(model["pricing"]["input"], 1)


class HttpSafetyTests(unittest.TestCase):
    def test_redirect_to_another_origin_is_blocked(self):
        handler = _SameHostRedirectHandler()
        request = Request("https://api.example.test/v1/models", headers={"Authorization": "Bearer secret"})
        with self.assertRaises(ApiError) as context:
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://evil.example.test/collect",
            )
        self.assertEqual(context.exception.kind, "unsafe_redirect")

    def test_https_downgrade_is_blocked_even_on_same_host(self):
        handler = _SameHostRedirectHandler()
        request = Request("https://api.example.test/v1/models")
        with self.assertRaises(ApiError):
            handler.redirect_request(request, None, 302, "Found", {}, "http://api.example.test/models")


class ProviderTests(unittest.TestCase):
    def test_all_ten_providers_are_registered(self):
        self.assertEqual(len(PROVIDERS), 10)
        self.assertEqual(
            {provider.slug for provider in PROVIDERS},
            {
                "openai",
                "anthropic",
                "openrouter",
                "groq",
                "cerebras",
                "mistral",
                "deepseek",
                "together",
                "huggingface",
                "replicate",
            },
        )

    def test_generic_model_endpoint_validates_and_limits_output(self):
        spec = PROVIDER_BY_SLUG["openai"]
        client = FakeClient(
            {
                spec.models_url: [
                    response(
                        {"data": [{"id": "z-model"}, {"id": "a-model"}]},
                        {"x-ratelimit-remaining-requests": "99"},
                    )
                ]
            }
        )
        result = audit_provider(spec, "secret-openai", "OPENAI_API_KEY", client, model_limit=1)
        self.assertEqual(result["status"], "valid")
        self.assertTrue(result["authenticated"])
        self.assertEqual(result["model_count"], 2)
        self.assertEqual(result["models"][0]["id"], "a-model")
        self.assertEqual(result["rate_limits"]["models"]["x-ratelimit-remaining-requests"], "99")
        self.assertNotIn("secret-openai", json.dumps(result))

    def test_unauthorized_key_is_invalid(self):
        spec = PROVIDER_BY_SLUG["groq"]
        client = FakeClient({spec.models_url: [ApiError("invalid key", status=401)]})
        result = audit_provider(spec, "gsk-secret", "GROQ_API_KEY", client)
        self.assertEqual(result["status"], "invalid")
        self.assertFalse(result["authenticated"])

    def test_openrouter_standard_key_reports_key_limit_not_account_balance(self):
        spec = PROVIDER_BY_SLUG["openrouter"]
        client = FakeClient(
            {
                "https://openrouter.ai/api/v1/key": [
                    response(
                        {
                            "data": {
                                "label": "dev",
                                "is_management_key": False,
                                "limit": 10,
                                "limit_remaining": 7.5,
                                "usage": 2.5,
                            }
                        }
                    )
                ],
                spec.models_url: [response({"data": [{"id": "openai/test", "context_length": 8192}]})],
            }
        )
        result = audit_provider(spec, "sk-or-secret", "OPENROUTER_API_KEY", client)
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["balance"]["kind"], "api_key_limit")
        self.assertEqual(result["balance"]["remaining"], 7.5)
        self.assertEqual(len(client.calls), 2)

    def test_openrouter_management_key_computes_account_credits(self):
        spec = PROVIDER_BY_SLUG["openrouter"]
        client = FakeClient(
            {
                "https://openrouter.ai/api/v1/key": [response({"data": {"is_management_key": True}})],
                "https://openrouter.ai/api/v1/credits": [
                    response({"data": {"total_credits": 100.5, "total_usage": 25.75}})
                ],
                spec.models_url: [response({"data": []})],
            }
        )
        result = audit_provider(spec, "management-secret", "OPENROUTER_API_KEY", client)
        self.assertEqual(result["balance"]["kind"], "account_credits")
        self.assertEqual(result["balance"]["remaining"], "74.75")

    def test_deepseek_reports_real_balance_and_models(self):
        spec = PROVIDER_BY_SLUG["deepseek"]
        client = FakeClient(
            {
                "https://api.deepseek.com/user/balance": [
                    response(
                        {
                            "is_available": True,
                            "balance_infos": [
                                {
                                    "currency": "USD",
                                    "total_balance": "12.34",
                                    "granted_balance": "2.34",
                                    "topped_up_balance": "10.00",
                                }
                            ],
                        }
                    )
                ],
                spec.models_url: [response({"data": [{"id": "deepseek-chat"}]})],
            }
        )
        result = audit_provider(spec, "deepseek-secret", "DEEPSEEK_API_KEY", client)
        self.assertEqual(result["balance"]["kind"], "account_balance")
        self.assertEqual(result["balance"]["balances"][0]["total_balance"], "12.34")
        self.assertEqual(result["models"][0]["id"], "deepseek-chat")

    def test_huggingface_validates_identity_and_lists_inference_models(self):
        spec = PROVIDER_BY_SLUG["huggingface"]
        client = FakeClient(
            {
                "https://huggingface.co/api/whoami-v2": [
                    response(
                        {
                            "type": "user",
                            "name": "alice",
                            "email": "not-copied@example.com",
                            "auth": {"accessToken": {"displayName": "local", "role": "read"}},
                            "orgs": [{"name": "team"}],
                        }
                    )
                ],
                spec.models_url: [response({"data": [{"id": "org/chat-model"}]})],
            }
        )
        result = audit_provider(spec, "hf-secret", "HF_TOKEN", client)
        self.assertEqual(result["account"]["name"], "alice")
        self.assertNotIn("email", result["account"])
        self.assertEqual(result["models"][0]["id"], "org/chat-model")

    def test_replicate_uses_account_as_validation_endpoint(self):
        spec = PROVIDER_BY_SLUG["replicate"]
        client = FakeClient(
            {
                "https://api.replicate.com/v1/account": [
                    response({"type": "user", "username": "alice", "name": "Alice"})
                ],
                spec.models_url: [
                    response({"results": [{"owner": "replicate", "name": "hello-world"}], "next": "next-page"})
                ],
            }
        )
        result = audit_provider(spec, "r8_secret", "REPLICATE_API_TOKEN", client)
        self.assertEqual(result["account"]["username"], "alice")
        self.assertEqual(result["models"][0]["id"], "replicate/hello-world")
        self.assertFalse(result["model_list_complete"])

    def test_cerebras_enriches_authenticated_models_with_public_metadata(self):
        spec = PROVIDER_BY_SLUG["cerebras"]
        client = FakeClient(
            {
                spec.models_url: [response({"data": [{"id": "model-a", "owned_by": "Cerebras"}]})],
                "https://api.cerebras.ai/public/v1/models": [
                    response(
                        {
                            "data": [
                                {
                                    "id": "model-a",
                                    "pricing": {"input": 0.1, "output": 0.2},
                                    "context_length": 131072,
                                }
                            ]
                        }
                    )
                ],
            }
        )
        result = audit_provider(spec, "csk-secret", "CEREBRAS_API_KEY", client)
        self.assertEqual(result["models"][0]["context_length"], 131072)
        self.assertEqual(result["models"][0]["pricing"]["output"], 0.2)

    def test_remote_echo_of_secret_is_redacted(self):
        spec = PROVIDER_BY_SLUG["openai"]
        secret = "super-secret-value"
        client = FakeClient(
            {
                spec.models_url: [
                    response({"data": [{"id": "model", "description": f"echo {secret}"}]})
                ]
            }
        )
        result = audit_provider(spec, secret, "OPENAI_API_KEY", client)
        serialized = json.dumps(result)
        self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED]", serialized)


if __name__ == "__main__":
    unittest.main()
