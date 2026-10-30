import sys, zipfile, glob, csv, io, datetime as dt, collections
rows=[]
for f in sorted(glob.glob(sys.argv[1]+"/*.zip")):
    z=zipfile.ZipFile(f)
    for n in z.namelist():
        r=csv.reader(io.TextIOWrapper(z.open(n)))
        for line in r:
            if not line or not line[0].isdigit(): continue
            rows.append((int(line[0]), float(line[2])))
rows=sorted(set(rows))
by=collections.defaultdict(list)
for t,r in rows:
    d=dt.datetime.utcfromtimestamp(t/1000)
    by[d.year if d.year<2025 else f"{d.year}H{1 if d.month<=6 else 2}"].append(r)
print("period n sum_pct(=gross carry %/yr-ish) ann_pct neg_frac max_neg_8h")
for k in sorted(by,key=str):
    v=by[k]; s=sum(v)*100; days=len(v)/3
    print(k,len(v),round(s,2),round(s*365/days,2),round(sum(1 for x in v if x<0)/len(v),3),round(min(v)*100,4))
# 30-day rolling negative windows
v=[r for _,r in rows]; ts=[t for t,_ in rows]
w=90; neg=[i for i in range(w,len(v)) if sum(v[i-w:i])<0]
print("30d windows (90 prints) with net negative funding:", round(len(neg)/(len(v)-w),3))
print("first", dt.datetime.utcfromtimestamp(ts[0]/1000), "last", dt.datetime.utcfromtimestamp(ts[-1]/1000))
