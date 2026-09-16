import unittest
from unittest.mock import MagicMock

from probe_toolbox import read_reply


class ProbeTests(unittest.TestCase):
    def test_json_response_checks_id(self):
        response = MagicMock()
        response.headers = {"Content-Type": "application/json"}
        response.json.return_value = {"id": 2, "result": {"tools": []}}
        self.assertEqual(read_reply(response, 2), response.json.return_value)
        with self.assertRaises(RuntimeError):
            read_reply(response, 3)

    def test_sse_skips_notifications(self):
        response = MagicMock()
        response.headers = {"Content-Type": "text/event-stream"}
        response.iter_lines.return_value = iter([
            ': heartbeat', '', 'data: {"method":"notification"}', '',
            'data: {"id":2,"result":{"tools":[]}}', '',
        ])
        self.assertEqual(read_reply(response, 2), {"id": 2, "result": {"tools": []}})

    def test_empty_sse_is_an_error(self):
        response = MagicMock()
        response.headers = {"Content-Type": "text/event-stream"}
        response.iter_lines.return_value = iter([])
        with self.assertRaises(RuntimeError):
            read_reply(response, 2)


if __name__ == "__main__":
    unittest.main()
