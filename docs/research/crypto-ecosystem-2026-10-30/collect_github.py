"""Public GitHub snapshot: no installs, inference or trading. Optional GITHUB_TOKEN (read from env, never logged).

python3 collect_github.py --output /tmp/github_snapshot.json
Network errors remain explicit. A latest push is NOT a latest default-branch commit.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

REPOSITORIES = (
    'ccxt/ccxt', 'freqtrade/freqtrade', 'hummingbot/hummingbot',
    'hummingbot/condor', 'jesse-ai/jesse', 'Drakkar-Software/OctoBot',
    'enarjord/passivbot', 'nautechsystems/nautilus_trader', 'QuantConnect/Lean',
    'Lumiwealth/lumibot', 'polakowo/vectorbt', 'kernc/backtesting.py',
    'OpenBB-finance/OpenBB', 'CryptoSignal/Crypto-Signal', 'microsoft/RD-Agent',
    'microsoft/qlib', 'TauricResearch/TradingAgents', 'virattt/ai-hedge-fund',
    'AI4Finance-Foundation/FinRobot', 'AI4Finance-Foundation/FinRL',
    'AI4Finance-Foundation/FinRL-Trading', 'NoFxAiOS/nofx', 'HKUDS/Vibe-Trading',
    'Starlien95/Awesome-TradingAI', 'Superalgos/Superalgos',
    # Second pass (gap closure): agent frameworks, candle foundation models,
    # trading MCP servers, funding-arb and market-making simulators.
    'elizaOS/eliza', 'shiyu-coder/Kronos', 'AI4Finance-Foundation/FinGPT',
    'amazon-science/chronos-forecasting', 'google-research/timesfm',
    'nkaz001/hftbacktest', 'kukapay/freqtrade-mcp', 'doggybee/mcp-server-ccxt',
    '50shadesofgwei/funding-rate-arbitrage', 'hummingbot/hummingbot-api',
)
ISSUE_REPOS = ('freqtrade/freqtrade', 'hummingbot/hummingbot',
               'TauricResearch/TradingAgents', 'microsoft/RD-Agent')


def request(path):
    url = 'https://api.github.com/' + path
    headers = {'User-Agent': 'crypto-ecosystem-research', 'Accept': 'application/vnd.github+json'}
    if os.environ.get('GITHUB_TOKEN'):  # optional; lifts the 60/h anonymous limit, never logged
        headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(3):  # transient DNS/timeouts; HTTP errors (403/404) are not retried
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return {'url': url, 'ok': True, 'server_date': response.headers.get('Date'),
                        'data': json.load(response)}
        except urllib.error.HTTPError as error:
            return {'url': url, 'ok': False, 'error': str(error), 'data': None}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last = error
            time.sleep(2 * (attempt + 1))
    return {'url': url, 'ok': False, 'error': str(last), 'attempts': 3, 'data': None}


def repository(repo):
    metadata = request('repos/' + repo)
    commits = request('repos/' + repo + '/commits?per_page=1')
    data = metadata['data'] or {}
    latest = commits['data'][0] if commits['ok'] and commits['data'] else {}
    return {'requested_repository': repo, 'repository': data.get('full_name', repo),
            'stars': data.get('stargazers_count'), 'archived': data.get('archived'),
            'license_spdx': (data.get('license') or {}).get('spdx_id'),
            'default_branch': data.get('default_branch'), 'pushed_at': data.get('pushed_at'),
            'latest_commit_sha': latest.get('sha'),
            'latest_commit_at': latest.get('commit', {}).get('committer', {}).get('date'),
            'latest_commit_url': latest.get('html_url'),
            'metadata_evidence': {k: v for k, v in metadata.items() if k != 'data'},
            'commit_evidence': {k: v for k, v in commits.items() if k != 'data'}}


def first_maintainer_response(issue, comments):
    """Sampled response, excluding issue author and bots; None means unobserved."""
    opened = datetime.fromisoformat(issue['created_at'].replace('Z', '+00:00'))
    qualified = [c for c in comments
                 if c.get('author_association') in ('OWNER', 'MEMBER', 'COLLABORATOR')
                 and c.get('user', {}).get('login') != issue.get('user', {}).get('login')
                 and c.get('user', {}).get('type') != 'Bot']
    if not qualified:
        return None
    first = min(qualified, key=lambda c: c['created_at'])
    replied = datetime.fromisoformat(first['created_at'].replace('Z', '+00:00'))
    if replied < opened:
        raise ValueError('response predates issue')
    return {'hours': (replied - opened).total_seconds() / 3600,
            'url': first.get('html_url'), 'association': first['author_association']}


def issue_search_path(repo):
    """Most recently updated real issue (never a PR) that has at least one comment.

    The plain /issues listing mixes in PRs; on busy repos its first page can be all
    PRs, which silently produced 'unavailable' samples.
    """
    query = urllib.parse.quote(f'repo:{repo} is:issue comments:>0')
    return 'search/issues?q=' + query + '&sort=updated&order=desc&per_page=5'


def issue_sample(repo, as_of):
    listing = request(issue_search_path(repo))
    items = (listing['data'] or {}).get('items', []) if listing['ok'] else []
    candidates = [i for i in items if 'pull_request' not in i and i.get('comments', 0) > 0]
    issue = candidates[0] if candidates else None
    comments = request('repos/' + repo + '/issues/' + str(issue['number']) + '/comments?per_page=100') if issue else None
    cutoff = (as_of.date() - timedelta(days=30)).isoformat()
    query = urllib.parse.quote(f'repo:{repo} is:issue is:closed closed:{cutoff}..{as_of.date().isoformat()}')
    closed = request('search/issues?q=' + query + '&per_page=1')
    return {'repository': repo, 'selection': 'most recently updated commented issue via search (is:issue comments:>0)',
            'listing_url': listing['url'], 'listing_ok': listing['ok'],
            'issue': {k: issue.get(k) for k in ('number', 'html_url', 'title', 'created_at', 'updated_at', 'state', 'comments')} if issue else None,
            'comments_evidence': {k: v for k, v in comments.items() if k != 'data'} if comments else None,
            'comments_examined': len(comments['data']) if comments and comments['ok'] else None,
            'first_maintainer_response': first_maintainer_response(issue, comments['data']) if issue and comments and comments['ok'] else None,
            'closed_issue_count': closed['data'].get('total_count') if closed['ok'] else None,
            'closed_count_window': [cutoff, as_of.date().isoformat()],
            'closed_count_evidence': {k: v for k, v in closed.items() if k != 'data'},
            'closed_count_incomplete': closed['data'].get('incomplete_results') if closed['ok'] else None}


def sample_fetch_failures(sample):
    """Names of the issue-sample fetches that failed; a failure is never rendered as an observation."""
    failed = []
    if not sample.get('listing_ok', True):
        failed.append('listing')
    if (sample.get('comments_evidence') or {}).get('ok') is False:
        failed.append('comments')
    if (sample.get('closed_count_evidence') or {}).get('ok') is False:
        failed.append('closed_count')
    return failed


def collection_errors(repositories, samples):
    """Every failed fetch, repository and issue sample alike; any entry blocks overwriting a snapshot."""
    errors = [row['repository'] for row in repositories
              if not row['metadata_evidence']['ok'] or not row['commit_evidence']['ok']]
    errors += [s['repository'] + ':' + part for s in samples for part in sample_fetch_failures(s)]
    return errors


def render(snapshot):
    lines = ['# GitHub metadata snapshot', '',
             'Fetched UTC: ' + snapshot['retrieved_at'], '',
             'Counts measure attention/activity, not reliability or investment returns. Commit date is default-branch committer time. NOASSERTION means inspect the license text. Missing fields are unknown, not zero.', '',
             '| Repository | Stars | Default-branch commit UTC | License signal | Archived |',
             '|---|---:|---|---|---|']
    for row in snapshot['repositories']:
        value = lambda k: 'unknown' if row.get(k) is None else str(row[k])
        if (row.get('metadata_evidence') or {}).get('ok') is False:
            value = lambda k: 'fetch failed'
        commit = 'fetch failed' if (row.get('commit_evidence') or {}).get('ok') is False else value('latest_commit_at')
        lines.append(f"| [{row['repository']}](https://github.com/{row['repository']}) | {value('stars')} | [{commit}]({row.get('latest_commit_url') or row['commit_evidence']['url']}) | {value('license_spdx')} | {value('archived')} |")
    lines += ['', '## Issue responsiveness sample', '',
              'One deliberately small convenience sample per project; not a median or comparative service-level guarantee. We exclude PRs, bots and issue-author self-replies. Only OWNER/MEMBER/COLLABORATOR comments count. A null response means no qualifying response in the retrieved first 100 comments, not proof nobody responded. Closed counts include all closed issues in the inclusive date range and do not imply fixes.', '',
              'A sample whose title shows a housekeeping/community thread (e.g. a chat-group QR code) is non-diagnostic for defect response.', '',
              '| Repository | Sample issue (title shown: a community or support thread is not a defect report) | First qualifying reply, hours | Closed issues in window |',
              '|---|---|---:|---:|']
    for sample in snapshot['issue_samples']:
        issue = sample['issue']
        response = sample['first_maintainer_response']
        failed = sample_fetch_failures(sample)
        if 'listing' in failed:
            link = 'fetch failed'
        else:
            link = f"[#{issue['number']}]({issue['html_url']}) {issue.get('title') or ''}".strip() if issue else 'no commented issue found'
        if 'comments' in failed or 'listing' in failed:
            reply = 'fetch failed'
        else:
            reply = f"[{response['hours']:.2f}]({response['url']})" if response else 'not observed'
        count = sample['closed_issue_count']
        count = 'fetch failed' if 'closed_count' in failed else (count if count is not None else 'unknown')
        if sample.get('closed_count_incomplete'):
            count = f'{count} (incomplete search results)'
        lines.append(f"| {sample['repository']} | {link} | {reply} | {count} |")
    lines += ['', 'Exact windows, SHAs, endpoint URLs and error states are in github_snapshot.json. Rerunning collects a new snapshot; it does not reproduce historical star counts.', '']
    return '\n'.join(lines)


def write_snapshot(target, snapshot, errors):
    """Write JSON + Markdown. A run with any fetch error always goes to <stem>.failed.json/.md,
    so it can never replace (or masquerade as) a canonical snapshot, JSON or Markdown."""
    if target.suffix != '.json':
        raise ValueError('--output must end in .json')
    if errors:
        target = target.with_name(target.stem + '.failed' + target.suffix)
    target.write_text(json.dumps(snapshot, indent=2) + '\n')
    target.with_name(target.stem + '.md').write_text(render(snapshot))
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=3) as pool:
        repositories = list(pool.map(repository, REPOSITORIES))
    samples = [issue_sample(repo, now) for repo in ISSUE_REPOS]
    snapshot = {'retrieved_at': now.isoformat(), 'repositories': repositories, 'issue_samples': samples}
    errors = collection_errors(repositories, samples)
    target = write_snapshot(Path(args.output), snapshot, errors)
    print(json.dumps({'repositories': len(repositories), 'repo_errors': errors, 'output': str(target)}))
