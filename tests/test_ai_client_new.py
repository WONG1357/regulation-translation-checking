import unittest

from src.ai_client import is_deepseek_url, normalize_base_url


class AIClientNewTests(unittest.TestCase):
    def test_deepseek_url_normalization(self):
        self.assertEqual(
            normalize_base_url("https://api.deepseek.com/chat/completions"),
            "https://api.deepseek.com",
        )
        self.assertTrue(is_deepseek_url("https://api.deepseek.com"))
        self.assertTrue(is_deepseek_url("https://api.deepseek.com/"))


if __name__ == "__main__":
    unittest.main()
