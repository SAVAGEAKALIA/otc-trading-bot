"""Bounded, public-only R1 data collector. No account or order endpoints."""
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request
import urllib.error

BASE = 'https://api.bybit.com'
DAY = 86_400_000
SEEDS = ('BTC','ETH','SOL','XRP','DOGE','ADA','LINK','AVAX','LTC','BCH')
ALLOWED = {'time','instruments-info','tickers','funding/history','kline','mark-price-kline','index-price-kline','risk-limit'}


def ms(text):
    value = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('UTC timezone required')
    return int(value.timestamp()*1000)


def finite(value, positive=False):
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('invalid numeric input') from exc
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError('nonfinite/nonpositive value')
    return result


def unique(rows, key):
    result = {}; duplicates = 0
    for row in rows:
        stamp = key(row)
        if stamp in result:
            if result[stamp] != row:
                raise ValueError('conflicting duplicate at ' + str(stamp))
            duplicates += 1
        result[stamp] = row
    return [result[t] for t in sorted(result)], duplicates


def audit_series(rows, start, end, kind):
    if end <= start or start % DAY or end % DAY:
        raise ValueError('audit window must span positive complete UTC days')
    key = (lambda x:int(x['fundingRateTimestamp'])) if kind == 'funding' else (lambda x:int(x[0]))
    clean, duplicates = unique(rows,key)
    if any(not start <= key(x) < end for x in clean):
        raise ValueError('record outside frozen window')
    for row in clean:
        if kind == 'funding': finite(row['fundingRate'])
        else:
            if len(row) not in (5, 7):
                raise ValueError('daily candle must contain OHLC or OHLC with volume and turnover')
            if any(finite(value) < 0 for value in row[5:]):
                raise ValueError('negative candle volume or turnover')
            if key(row) % DAY:
                raise ValueError('daily candle must start at UTC midnight')
            for value in row[1:5]: finite(value, positive=True)
            opening,high,low,close = map(Decimal,row[1:5])
            if not low <= min(opening,close) <= max(opening,close) <= high:
                raise ValueError('invalid candle range')
    stamps=[key(x) for x in clean]
    gaps=Counter(b-a for a,b in zip(stamps,stamps[1:]))
    days=Counter(t//DAY for t in stamps)
    missing=[datetime.fromtimestamp(d*86400,timezone.utc).date().isoformat()
             for d in range(start//DAY,end//DAY) if not days[d]]
    return {'rows':len(clean),'duplicates':duplicates,'first_ms':stamps[0] if stamps else None,
            'last_ms':stamps[-1] if stamps else None,'gap_hours_histogram':{str(k/3600000):v for k,v in sorted(gaps.items())},
            'whole_missing_days':missing,'daily_count_histogram':dict(sorted(Counter(days.values()).items())),
            'funding_schedule_status':'unverified historical cadence; gaps are not automatically missing payments' if kind=='funding' else None,
            'calendar_complete':not missing and len(stamps)==(end-start)//DAY if kind!='funding' else None}


def screen(spot, perp):
    reasons=[]; values={}
    for name,row,minimum in [('spot',spot,1_000_000),('perp',perp,10_000_000)]:
        try:
            bid=finite(row.get('bid1Price'),True); ask=finite(row.get('ask1Price'),True)
            if ask<bid: raise ValueError('crossed quote')
            spread=(ask-bid)/((ask+bid)/2)*10000
            turnover=finite(row.get('turnover24h'))
            values[name]={'spread_bps':float(spread),'turnover24h_usdt':float(turnover)}
            if spread>20: reasons.append(name+':spread>20bps')
            if turnover<minimum: reasons.append(name+':turnover below policy floor')
        except (ValueError,TypeError): reasons.append(name+':invalid/missing quote')
    return {'passes_current_quote_screen':not reasons,'reasons':reasons,'values':values}


class PublicClient:
    def __init__(self, root):
        self.root=Path(root)
        self.root.parent.mkdir(parents=True,exist_ok=False)
        self.root.mkdir()
        self.records=[]
    def get(self, endpoint, **params):
        if endpoint not in ALLOWED: raise ValueError('endpoint not public-market allowlist')
        url=BASE+'/v5/market/'+endpoint+'?'+urllib.parse.urlencode(params)
        error=None
        for attempt in range(3):
            try:
                req=urllib.request.Request(url,headers={'User-Agent':'R1-public-research'})
                with urllib.request.urlopen(req,timeout=20) as response: raw=response.read()
                payload=json.loads(raw)
                if payload.get('retCode')!=0: raise ValueError('venue error '+str(payload.get('retCode')))
                filename=f'{len(self.records):04d}.json'
                (self.root/filename).write_bytes(raw)
                record={'file':filename,'url':url,'retrieved_at':datetime.now(timezone.utc).isoformat(),
                        'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'venue_time_ms':payload.get('time')}
                self.records.append(record)
                (self.root/'manifest.json').write_text(json.dumps(self.records,indent=2)+'\n')
                return payload['result']
            except urllib.error.HTTPError as exc:
                # Access restriction is not a retry/bypass invitation.
                if exc.code in (401,403,451): raise
                error=exc
            except (urllib.error.URLError,TimeoutError,ValueError) as exc: error=exc
            if attempt<2: time.sleep(attempt+1)
        raise RuntimeError(f'public fetch failed: {url}: {error}')


def instruments(client,category):
    rows=[]; cursor='';seen=set()
    for _ in range(20):
        params={'category':category}
        if category!='spot':params.update(limit=1000,cursor=cursor)
        result=client.get('instruments-info',**params);rows.extend(result['list'])
        cursor=result.get('nextPageCursor','')
        if not cursor:return rows
        if cursor in seen:raise ValueError('instrument cursor did not progress')
        seen.add(cursor)
    raise ValueError('instrument page budget exhausted')


def funding(client,symbol,start,end):
    rows=[];cursor=end-1
    for _ in range(20):
        page=client.get('funding/history',category='linear',symbol=symbol,startTime=start,endTime=cursor,limit=200)['list']
        if not page:return rows
        stamps=[int(x['fundingRateTimestamp']) for x in page]
        if min(stamps)>cursor:raise ValueError('funding cursor did not progress')
        if any(t>cursor or t<start for t in stamps):raise ValueError('funding response outside requested bounds')
        rows.extend(page);cursor=min(stamps)-1
        if cursor<start:return rows
    raise ValueError('funding page budget exhausted')


class ReplayClient:
    """Read-only replay of exact saved requests, validating source hashes."""
    def __init__(self, root, source):
        Path(root).parent.mkdir(parents=True, exist_ok=False)
        self.source=Path(source)
        self.manifest=json.loads((self.source/'manifest.json').read_text())
        self.records=[]
    def get(self, endpoint, **params):
        if endpoint not in ALLOWED: raise ValueError('non-public endpoint')
        expected=BASE+'/v5/market/'+endpoint+'?'+urllib.parse.urlencode(params)
        if len(self.records)>=len(self.manifest):raise ValueError('replay exhausted')
        record=self.manifest[len(self.records)]
        if record['url']!=expected:raise ValueError('replay request mismatch')
        name=record['file']
        if Path(name).name!=name:raise ValueError('invalid source path')
        raw=(self.source/name).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=record['sha256']:raise ValueError('source checksum mismatch')
        payload=json.loads(raw)
        if payload.get('retCode')!=0:raise ValueError('replay venue error')
        self.records.append(record)
        return payload['result']


def collect(output,end_text,days,client_factory=PublicClient):
    if not 1<=days<=90:raise ValueError('days must be in 1..90')
    end=ms(end_text)
    if end%DAY:raise ValueError('end must be UTC midnight')
    start=end-days*DAY
    client=client_factory(Path(output)/'raw')
    server=client.get('time');server_ms=int(server['timeSecond'])*1000
    if end>server_ms//DAY*DAY:raise ValueError('requested cutoff includes incomplete/future UTC day')
    spot=instruments(client,'spot');perp=instruments(client,'linear')
    spot_map={x['baseCoin']:x for x in spot if x['quoteCoin']=='USDT' and x['status']=='Trading'}
    perp_map={x['baseCoin']:x for x in perp if x['quoteCoin']=='USDT' and x['status']=='Trading' and x.get('contractType')=='LinearPerpetual' and x.get('settleCoin')=='USDT'}
    ticks={cat:{x['symbol']:x for x in client.get('tickers',category=cat)['list']} for cat in ('spot','linear')}
    results=[]
    progress=Path('/tmp/crypto-r1/data-progress.log');progress.parent.mkdir(parents=True,exist_ok=True)
    begun=time.monotonic()
    for index,coin in enumerate(SEEDS):
        entry={'asset':coin,'listed_pair_now':coin in spot_map and coin in perp_map,'live_eligible':False}
        if not entry['listed_pair_now']:
            entry['reason']='no current Trading USDT spot/linear perpetual pair'
        else:
            s,p=spot_map[coin],perp_map[coin];symbol=p['symbol']
            entry.update(spot_instrument=s,perp_instrument=p,quote_screen=screen(ticks['spot'].get(s['symbol'],{}),ticks['linear'].get(symbol,{})))
            entry['risk_tiers_current']=client.get('risk-limit',category='linear',symbol=symbol)
            fund=funding(client,symbol,start,end)
            clean,dups=unique(fund,lambda x:int(x['fundingRateTimestamp']))
            entry['funding']=audit_series(fund,start,end,'funding')
            entry['funding']['sum_rates_screen_only']=float(sum((finite(x['fundingRate']) for x in clean),Decimal(0))) if clean else None
            entry['funding']['not_a_portfolio_return']=True
            entry['series']={}
            for label,endpoint,category in [('spot','kline','spot'),('perp','kline','linear'),('mark','mark-price-kline','linear'),('index','index-price-kline','linear')]:
                bars=client.get(endpoint,category=category,symbol=s['symbol'] if label=='spot' else symbol,interval='D',start=start,end=end-1,limit=1000)['list']
                entry['series'][label]=audit_series(bars,start,end,'candle')
        results.append(entry)
        elapsed=time.monotonic()-begun;rate=(index+1)/elapsed;eta=(len(SEEDS)-index-1)/rate
        message=f'{datetime.now(timezone.utc).isoformat()} R1 market-data {(index+1)/len(SEEDS)*100:.0f}% ETA {eta:.1f}s symbols {index+1}/{len(SEEDS)} asset={coin}\n'
        with progress.open('a') as f:f.write(message)
        print(message,end='',flush=True)
    report={'cutoff_utc':end_text,'start_utc':datetime.fromtimestamp(start/1000,timezone.utc).isoformat(),'days':days,
            'current_usdt_spot_perp_intersection_count':len(set(spot_map)&set(perp_map)),
            'seed_assets':SEEDS,'as_of_server_ms':server_ms,'requests':len(client.records),'assets':results,
            'limits':['current metadata is not historical eligibility','funding cadence history unverified','daily OHLC is not executable fill or historical spread','fee tiers require account confirmation','current quotes are one snapshot, not capacity proof','no live eligibility established']}
    if isinstance(client,ReplayClient) and len(client.records)!=len(client.manifest):raise ValueError('unused replay requests')
    path=Path(output)/'report.json';path.write_text(json.dumps(report,indent=2)+'\n')
    return path


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--end',required=True);parser.add_argument('--days',type=int,default=90)
    parser.add_argument('--replay',help='raw directory for offline checksum-validated replay')
    args=parser.parse_args()
    factory=(lambda root:ReplayClient(root,args.replay)) if args.replay else PublicClient
    print(collect(args.output,args.end,args.days,factory))
