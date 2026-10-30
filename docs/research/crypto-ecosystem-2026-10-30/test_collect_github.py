"""Offline gate tests + adversarial scenario evals for evidence reporting."""
import unittest
import tempfile
from pathlib import Path

from collect_github import collection_errors, first_maintainer_response, issue_search_path, render, write_snapshot

ISSUE = {'created_at': '2026-10-01T00:00:00Z', 'user': {'login': 'reporter'}}

def comment(login='maintainer', association='MEMBER', kind='User', stamp='2026-10-01T02:00:00Z'):
    return {'user': {'login': login, 'type': kind}, 'author_association': association,
            'created_at': stamp, 'html_url': 'https://github.com/example/repo/issues/1#issuecomment-1'}


class GateTests(unittest.TestCase):
    def test_response_time(self):
        self.assertEqual(first_maintainer_response(ISSUE, [comment()])['hours'], 2)

    def test_unknown_is_not_zero(self):
        self.assertIsNone(first_maintainer_response(ISSUE, []))

    def test_reject_negative_latency(self):
        with self.assertRaises(ValueError):
            first_maintainer_response(ISSUE, [comment(stamp='2026-09-30T23:00:00Z')])

    def test_missing_metadata_not_success(self):
        row = {'repository': 'example/repo', 'commit_evidence': {'url': 'https://api.github.com/repos/example/repo/commits'}}
        text = render({'retrieved_at': '2026-10-30', 'repositories': [row], 'issue_samples': []})
        self.assertIn('| unknown |', text)
        self.assertNotIn('| 0 |', text)


class ScenarioEvals(unittest.TestCase):
    def test_false_responsiveness_is_not_counted(self):
        for fake in [comment(login='reporter'), comment(kind='Bot'), comment(association='NONE')]:
            with self.subTest(fake=fake):
                self.assertIsNone(first_maintainer_response(ISSUE, [fake]))

    def test_unordered_comments_choose_first_qualified(self):
        sequence = [comment(stamp='2026-10-02T00:00:00Z'), comment(kind='Bot', stamp='2026-10-01T00:01:00Z'), comment()]
        self.assertEqual(first_maintainer_response(ISSUE, sequence)['hours'], 2)

    def test_closed_zero_is_distinct_from_unavailable(self):
        sample = {'repository': 'example/repo', 'issue': None,
                  'first_maintainer_response': None, 'closed_issue_count': 0}
        text = render({'retrieved_at': '2026-10-30', 'repositories': [], 'issue_samples': [sample]})
        self.assertIn('not observed | 0 |', text)
        sample['closed_issue_count'] = None
        self.assertIn('not observed | unknown |', render({'retrieved_at': '2026-10-30', 'repositories': [], 'issue_samples': [sample]}))


class IssueSamplingTests(unittest.TestCase):
    def test_search_excludes_prs_and_uncommented(self):
        from urllib.parse import unquote
        path = unquote(issue_search_path('hummingbot/hummingbot'))
        self.assertTrue(path.startswith('search/issues?q=repo:hummingbot/hummingbot '))
        self.assertIn('is:issue', path)
        self.assertIn('comments:>0', path)
        self.assertIn('sort=updated', path)


class IssueFetchFailureTests(unittest.TestCase):
    OK_REPO = {'repository': 'example/repo', 'metadata_evidence': {'ok': True}, 'commit_evidence': {'ok': True}}

    def sample(self, listing=True, comments=True, closed=True):
        return {'repository': 'example/repo', 'listing_ok': listing,
                'issue': {'number': 1, 'html_url': 'https://github.com/example/repo/issues/1', 'title': 't'} if listing else None,
                'comments_evidence': {'ok': comments}, 'first_maintainer_response': None,
                'closed_count_evidence': {'ok': closed}, 'closed_issue_count': 3 if closed else None}

    def test_each_issue_fetch_failure_counts_as_collection_error(self):
        for kwargs, part in (({'listing': False}, 'listing'), ({'comments': False}, 'comments'), ({'closed': False}, 'closed_count')):
            with self.subTest(part=part):
                self.assertIn('example/repo:' + part, collection_errors([self.OK_REPO], [self.sample(**kwargs)]))
        self.assertEqual(collection_errors([self.OK_REPO], [self.sample()]), [])

    def test_failed_fetch_never_rendered_as_observation(self):
        for kwargs in ({'listing': False}, {'comments': False}):
            with self.subTest(kwargs=kwargs):
                text = render({'retrieved_at': '2026-10-30', 'repositories': [], 'issue_samples': [self.sample(**kwargs)]})
                self.assertIn('fetch failed', text)
                self.assertNotIn('not observed', text.split('## Issue responsiveness sample')[1].split('|---')[-1])

    def test_issue_failure_blocks_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / 'snap.json'; good.write_text('GOOD')
            errors = collection_errors([self.OK_REPO], [self.sample(comments=False)])
            write_snapshot(good, {'retrieved_at': 'x', 'repositories': [], 'issue_samples': []}, errors)
            self.assertEqual(good.read_text(), 'GOOD')


class HardeningTests(unittest.TestCase):
    def test_failed_run_without_prior_snapshot_never_uses_canonical_name(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'snap.json'
            written = write_snapshot(target, {'retrieved_at': 'x', 'repositories': [], 'issue_samples': []}, ['a/b'])
            self.assertEqual(written.name, 'snap.failed.json')
            self.assertFalse(target.exists())
            self.assertFalse(target.with_suffix('.md').exists())

    def test_output_without_json_extension_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'snap'
            Path(d, 'snap.md').write_text('GOOD MD')
            with self.assertRaises(ValueError):
                write_snapshot(target, {'retrieved_at': 'x', 'repositories': [], 'issue_samples': []}, ['a/b'])
            self.assertEqual(Path(d, 'snap.md').read_text(), 'GOOD MD')

    def test_good_markdown_survives_failed_run_when_json_missing(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'snap.json'; target.with_suffix('.md').write_text('GOOD MD')
            write_snapshot(target, {'retrieved_at': 'x', 'repositories': [], 'issue_samples': []}, ['a/b'])
            self.assertEqual(target.with_suffix('.md').read_text(), 'GOOD MD')

    def test_failed_metadata_rendered_as_fetch_failed(self):
        row = {'repository': 'a/b', 'metadata_evidence': {'ok': False}, 'commit_evidence': {'ok': False, 'url': 'u'}}
        text = render({'retrieved_at': 'x', 'repositories': [row], 'issue_samples': []})
        self.assertIn('| fetch failed | [fetch failed](u) |', text)
        self.assertNotIn('unknown', text.split('|---')[-1].split('## Issue')[0])

    def test_incomplete_search_results_are_flagged(self):
        sample = {'repository': 'a/b', 'listing_ok': True, 'issue': None, 'comments_evidence': None,
                  'first_maintainer_response': None, 'closed_count_evidence': {'ok': True},
                  'closed_issue_count': 7, 'closed_count_incomplete': True}
        self.assertIn('7 (incomplete search results)', render({'retrieved_at': 'x', 'repositories': [], 'issue_samples': [sample]}))


class SnapshotSafetyTests(unittest.TestCase):
    EMPTY = {'retrieved_at': '2026-10-30', 'repositories': [], 'issue_samples': []}

    def test_failed_run_never_overwrites_good_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / 'snap.json'
            good.write_text('GOOD')
            written = write_snapshot(good, self.EMPTY, errors=['example/repo'])
            self.assertEqual(good.read_text(), 'GOOD')
            self.assertEqual(written.name, 'snap.failed.json')

    def test_clean_run_replaces_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / 'snap.json'
            good.write_text('OLD')
            self.assertEqual(write_snapshot(good, self.EMPTY, errors=[]), good)
            self.assertNotEqual(good.read_text(), 'OLD')


if __name__ == '__main__':
    unittest.main()
