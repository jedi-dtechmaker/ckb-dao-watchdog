import unittest
from unittest.mock import Mock, patch

from app import app


class OngoingProposalTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch('app.watchdog.request_with_retry')
    def test_filters_active_polls_across_pages(self, request_mock):
        first_page = [{'id': n, 'title': f'Thread {n}', 'poll_status': 'expire'} for n in range(1, 51)]
        first_page[0]['poll_status'] = 'on'
        second_page = [
            {'id': 1, 'title': 'Duplicate', 'poll_status': 'on'},
            {'id': 51, 'title': 'Active proposal', 'poll_status': 'on'},
            {'id': 52, 'title': 'Upcoming', 'poll_status': 'not_started'},
        ]
        request_mock.side_effect = [Mock(json=Mock(return_value={'status': True, 'data': {'threads': page}}))
                                    for page in (first_page, second_page)]
        response = self.client.get('/api/proposals/ongoing')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['proposals'], [
            {'thread_id': 1, 'title': 'Thread 1'},
            {'thread_id': 51, 'title': 'Active proposal'},
        ])
        self.assertFalse(response.json['limited'])
        self.assertEqual(request_mock.call_count, 2)

    @patch('app.watchdog.request_with_retry')
    def test_invalid_upstream_response_is_not_reported_as_empty(self, request_mock):
        request_mock.return_value.json.return_value = {'status': False, 'description': 'Unavailable'}
        response = self.client.get('/api/proposals/ongoing')
        self.assertEqual(response.status_code, 502)
        self.assertFalse(response.json['success'])


if __name__ == '__main__':
    unittest.main()
