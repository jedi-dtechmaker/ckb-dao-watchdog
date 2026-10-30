"""Offline integration checks for the browser interface and fork report layout."""
from pathlib import Path
import queue
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app as entrypoint
web = sys.modules['watchdog_web']


class WebTest(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()

    def test_page_and_assets(self):
        for path in ('/', '/static/js/app.js', '/static/css/style.css'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()

    def test_fork_history_and_downloads(self):
        proposals = self.client.get('/api/history').json['proposals']
        self.assertTrue(any(p['title'] == 'Kirea' and p['thread_id'] == 80639
                            for p in proposals))
        self.assertTrue(any(p['title'] == 'Invisibook' for p in proposals))
        for proposal in proposals:
            for report in proposal['files']:
                response = self.client.get('/api/history/file', query_string={'path': report['rel_path']})
                self.assertEqual(response.status_code, 200, report['rel_path'])
                if report['type'] == 'json':
                    self.assertIsInstance(response.json['data'], list)
                else:
                    self.assertIn('attachment', response.headers['Content-Disposition'])
                response.close()

    def test_only_report_files_can_be_read(self):
        for path in ('../etc/passwd', 'README.md', 'dao-v1.0/app.py', '/etc/passwd'):
            self.assertEqual(self.client.get('/api/history/file', query_string={'path': path}).status_code, 404)

    def test_url_formats(self):
        for value in ('80044', 'https://dao.ckb.community/landing?method=share&thread=80044&refer_id=53572',
                      'https://dao.ckb.community/thread/proposal-80044?sort=new'):
            self.assertEqual(web.watchdog.parse_thread_id_from_url(value), 80044)

    def test_preview_includes_recorded_weights(self):
        data = {'status': True, 'code': 20000, 'data': {'thread': {'polls': [
            {'options': [{'id': 1, 'html': 'Yes', 'weights': 42}]}]}}}
        with patch.object(web.watchdog, 'request_with_retry') as request:
            request.return_value.json.return_value = data
            response = self.client.post('/api/preview', json={'url': '80044'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['options'][0]['weights'], 42)

    def run_worker(self, votes):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        dao = Path(temp.name) / 'dao-v1.0'
        dao.mkdir()
        job_id = 'test-job'
        web.JOBS[job_id] = {'queue': queue.Queue(), 'status': 'running'}
        self.addCleanup(web.JOBS.pop, job_id, None)
        with patch.object(web, 'CURRENT_DIR', str(dao)), \
             patch.object(web.watchdog, 'get_poll_options', return_value=([{'id': 1, 'html': 'Yes', 'weights': 42}], 80044)), \
             patch.object(web.watchdog, 'get_all_votes', return_value=votes), \
             patch.object(web.watchdog, 'get_user_dao_addresses', return_value=['ckb1test']), \
             patch.object(web.watchdog, 'get_address_onchain_weight', return_value=40):
            web.run_audit_worker(job_id, 80044)
            events = list(web.JOBS[job_id]['queue'].queue)
            if web.JOBS[job_id]['status'] == 'completed' and votes:
                files = self.client.get('/api/history').json['proposals'][0]['files']
                self.assertEqual(len(files), 2)
                for report in files:
                    response = self.client.get('/api/history/file', query_string={'path': report['rel_path']})
                    self.assertEqual(response.status_code, 200)
                    response.close()
            stream = self.client.get('/api/audit/stream/' + job_id)
            self.assertEqual(stream.status_code, 200)
            self.assertIn(b'event:', stream.data)
        return web.JOBS[job_id], events

    def test_audit_exports_discrepancies_and_streams_completion(self):
        job, events = self.run_worker([{'user_id': 1, 'name': 'Voter', 'weight': 42}])
        self.assertEqual(job['status'], 'completed')
        rows = job['results']['options'][0]['export_data']
        self.assertTrue(rows[0]['need_review'])
        self.assertEqual(rows[0]['total weight(on chain, floored)'], 40)
        self.assertTrue(any(e['type'] == 'complete' for e in events))

    def test_failed_voter_fetch_fails_audit(self):
        job, events = self.run_worker(None)
        self.assertEqual(job['status'], 'failed')
        self.assertTrue(any(e['type'] == 'error' for e in events))
        self.assertFalse(any(e['type'] == 'complete' for e in events))

    def test_empty_option_completes(self):
        job, events = self.run_worker([])
        self.assertEqual(job['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
