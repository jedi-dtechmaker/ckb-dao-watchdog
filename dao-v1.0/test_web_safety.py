import json
import os
import queue
import tempfile
import time
import unittest
from unittest.mock import patch

import app as web


class WebSafetyTests(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()
        web.JOBS.clear()
        web.LAST_JOB_STARTED = 0
        for timestamps in web.REQUEST_TIMES.values():
            timestamps.clear()

    def test_history_serves_only_report_files(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'REPORT_DIR', directory):
            os.mkdir(os.path.join(directory, '123'))
            with open(os.path.join(directory, '123', 'Yes_1CKB_report.json'), 'w') as report:
                json.dump([{'nickname': 'test'}], report)
            os.symlink(os.path.join(web.CURRENT_DIR, 'requirements.txt'), os.path.join(directory, '123', 'link.json'))
            good = self.client.get('/api/history/file', query_string={'path': 'vote_result/123/Yes_1CKB_report.json'})
            self.assertEqual(good.status_code, 200)
            self.assertEqual(good.json['data'][0]['nickname'], 'test')
            for path in ('../requirements.txt', 'requirements.txt', 'vote_result/123/../requirements.txt',
                         'vote_result/123/link.json', 'vote_result/123/secret.txt'):
                self.assertEqual(self.client.get('/api/history/file', query_string={'path': path}).status_code, 403)

    def test_audit_limit_and_input_validation(self):
        self.assertEqual(self.client.post('/api/audit/start', json={'url': []}).status_code, 400)
        self.assertEqual(self.client.post('/api/preview', json={'url': '-1'}).status_code, 400)
        with patch.object(web.threading.Thread, 'start'):
            self.assertEqual(self.client.post('/api/audit/start', json={'url': '123'}).status_code, 200)
            self.assertEqual(self.client.post('/api/audit/start', json={'url': '124'}).status_code, 429)
            web.LAST_JOB_STARTED = 0
            self.assertEqual(self.client.post('/api/audit/start', json={'url': '124'}).status_code, 200)
            web.LAST_JOB_STARTED = 0
            self.assertEqual(self.client.post('/api/audit/start', json={'url': '125'}).status_code, 429)

    def test_failed_upstream_audit_never_reports_success(self):
        job_id = 'test-job'
        web.JOBS[job_id] = {'queue': queue.Queue(maxsize=1000), 'status': 'running', 'streaming': False}
        options = [{'id': 1, 'html': 'Yes', 'weights': 10}]
        with patch.object(web.watchdog, 'get_poll_options', return_value=(options, 123)), \
             patch.object(web.watchdog, 'get_all_votes', return_value=None):
            web.run_audit_worker(job_id, 123)
        self.assertEqual(web.JOBS[job_id]['status'], 'failed')
        events = []
        while not web.JOBS[job_id]['queue'].empty():
            events.append(web.JOBS[job_id]['queue'].get_nowait()['type'])
        self.assertIn('error', events)
        self.assertNotIn('complete', events)

    def test_successful_job_saves_and_streams_report(self):
        job_id = 'test-job'
        web.JOBS[job_id] = {'queue': queue.Queue(maxsize=1000), 'status': 'running', 'streaming': False}
        options = [{'id': 1, 'html': 'Yes', 'weights': 0}]
        votes = [{'user_id': 2, 'name': 'Voter', 'weight': 0}]
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'REPORT_DIR', directory), \
             patch.object(web.watchdog, 'get_poll_options', return_value=(options, 123)), \
             patch.object(web.watchdog, 'get_all_votes', return_value=votes), \
             patch.object(web.watchdog, 'get_user_dao_addresses', return_value=[]):
            web.run_audit_worker(job_id, 123)
            response = self.client.get('/api/audit/stream/' + job_id)
            self.assertIn(b'event: complete', response.data)
            history = self.client.get('/api/history').json['proposals']
            self.assertEqual(history[-1]['thread_id'], 123)
            self.assertEqual(len(history[-1]['files']), 2)
            path = next(f['rel_path'] for f in history[-1]['files'] if f['type'] == 'json')
            self.assertEqual(self.client.get('/api/history/file', query_string={'path': path}).status_code, 200)


if __name__ == '__main__':
    unittest.main()
