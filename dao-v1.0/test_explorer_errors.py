import unittest
from unittest.mock import Mock, patch

import requests
import metaforo_watchdog_en as watchdog


def http_error(status, body):
    response = Mock(status_code=status)
    response.json.return_value = body
    return requests.exceptions.HTTPError(response=response)


class ExplorerErrorTests(unittest.TestCase):
    def test_unknown_address_has_zero_weight_in_strict_mode(self):
        error = http_error(404, [{"title": "Address Not Found", "code": 1010, "status": 404}])
        with patch.object(watchdog, 'request_with_retry', side_effect=error):
            self.assertEqual(watchdog.get_address_onchain_weight('ckb1unknown', strict=True), 0)

    def test_other_upstream_errors_still_fail_in_strict_mode(self):
        for error in (http_error(404, [{"code": 999, "status": 404}]),
                      http_error(500, [{"code": 1010, "status": 404}]),
                      requests.exceptions.Timeout()):
            with self.subTest(error=error), patch.object(watchdog, 'request_with_retry', side_effect=error):
                with self.assertRaises(RuntimeError):
                    watchdog.get_address_onchain_weight('ckb1unknown', strict=True)

    def test_unknown_address_after_first_page_does_not_hide_partial_results(self):
        first_page = Mock()
        first_page.json.return_value = {"data": [{"attributes": {}}] * 20}
        error = http_error(404, [{"code": 1010, "status": 404}])
        with patch.object(watchdog, 'request_with_retry', side_effect=[first_page, error]), \
             patch.object(watchdog.time, 'sleep'):
            with self.assertRaises(RuntimeError):
                watchdog.get_address_onchain_weight('ckb1unknown', strict=True)


if __name__ == '__main__':
    unittest.main()
