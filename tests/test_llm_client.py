import unittest

from src.llm_client import LLMConfig, LLMConfigurationError, validate_llm_config


class LLMConfigTests(unittest.TestCase):
    def test_rejects_pasted_unicode_prose_as_api_key(self):
        config = LLMConfig(
            provider="DeepSeek",
            api_key="Please review the “document” content",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        with self.assertRaisesRegex(LLMConfigurationError, "non-ASCII"):
            validate_llm_config(config)

    def test_rejects_whitespace_in_api_key(self):
        config = LLMConfig(
            provider="DeepSeek",
            api_key="not a valid key",
            model="deepseek-chat",
            base_url="https://api.deepseek.com",
        )
        with self.assertRaisesRegex(LLMConfigurationError, "spaces or line breaks"):
            validate_llm_config(config)

    def test_accepts_ascii_token(self):
        validate_llm_config(
            LLMConfig(
                provider="DeepSeek",
                api_key="sk-valid_ascii-token_123",
                model="deepseek-chat",
                base_url="https://api.deepseek.com",
            )
        )


if __name__ == "__main__":
    unittest.main()
