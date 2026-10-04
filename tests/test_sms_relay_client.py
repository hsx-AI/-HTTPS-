import unittest

from sms_relay_client import SmsRelayClient


def item(ident, sender, code):
    return {"id": ident, "sender": sender, "code": code}


class SmsRelayClientTests(unittest.TestCase):
    def client(self):
        return SmsRelayClient("https://example.invalid", "x" * 40, poll_interval=0.5)

    def test_latest_cursor_uses_highest_recent_id(self):
        client = self.client()
        client.recent = lambda limit: [item(9, "Bank", "123456"), item(14, "AE", "654321")]
        self.assertEqual(14, client.latest_cursor())

    def test_wait_for_code_uses_only_new_matching_sender(self):
        client = self.client()
        client.recent = lambda limit: [
            item(15, "Other", "111111"),
            item(13, "AE Platform", "222222"),
            item(12, "AE Platform", "000000"),
        ]
        self.assertEqual("222222", client.wait_for_code(after_id=12, timeout=1, sender_contains="ae"))

    def test_wait_for_code_times_out_when_no_new_code(self):
        client = self.client()
        client.recent = lambda limit: [item(12, "AE Platform", "222222")]
        with self.assertRaisesRegex(TimeoutError, "未收到"):
            client.wait_for_code(after_id=12, timeout=0)


if __name__ == "__main__":
    unittest.main()
