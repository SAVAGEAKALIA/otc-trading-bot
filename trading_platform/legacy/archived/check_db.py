import sqlite3, datetime
conn=sqlite3.connect('data/ml/historical_candles.sqlite')
cursor=conn.cursor()
cursor.execute('SELECT COUNT(DISTINCT asset), MIN(timestamp), MAX(timestamp), COUNT(*) FROM candles')
res=cursor.fetchone()
print(f'Assets: {res[0]}')
print(f'Start: {datetime.datetime.fromtimestamp(res[1])}')
print(f'End: {datetime.datetime.fromtimestamp(res[2])}')
print(f'Total Candles: {res[3]}')
