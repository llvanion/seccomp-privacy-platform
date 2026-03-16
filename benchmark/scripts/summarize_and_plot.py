#!/usr/bin/env python3
import argparse, glob, json, os
from typing import Any, Dict, List
import matplotlib.pyplot as plt

def load(p:str)->Dict[str,Any]:
    with open(p,'r',encoding='utf-8') as f: return json.load(f)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="benchmark/out")
    ap.add_argument("--report", default="benchmark/BENCHMARK_REPORT.md")
    args=ap.parse_args()

    paths=sorted(glob.glob(os.path.join(args.out_dir,"*","metrics.json")))
    if not paths:
        raise SystemExit("No metrics.json found. Run benchmark first.")
    rows=[]
    for p in paths:
        m=load(p)
        rows.append({
            "case_id": m.get("case_id"),
            "elapsed_s": m.get("run",{}).get("elapsed_s"),
            "max_rss_mb": m.get("run",{}).get("max_rss_mb"),
            "num_shards": m.get("params",{}).get("num_shards"),
            "max_jobs": m.get("params",{}).get("max_jobs"),
            "bucket_field": m.get("params",{}).get("bucket_field") or "",
            "exposure_n": m.get("dedup",{}).get("exposure_n"),
            "purchase_n": m.get("dedup",{}).get("purchase_n"),
            "intersection_size": m.get("result",{}).get("intersection_size"),
        })

    os.makedirs("benchmark/plots", exist_ok=True)

    xs=[r["exposure_n"] or 0 for r in rows]
    ys=[r["elapsed_s"] or 0 for r in rows]
    labs=[r["case_id"] for r in rows]
    plt.figure()
    plt.xlabel("dedup exposure_n (server.csv rows)")
    plt.ylabel("elapsed seconds (end-to-end)")
    plt.scatter(xs, ys)
    for x,y,lab in zip(xs,ys,labs):
        plt.annotate(lab,(x,y))
    img1="benchmark/plots/elapsed_vs_exposure.png"
    plt.savefig(img1, dpi=200)
    plt.close()

    from collections import defaultdict
    groups=defaultdict(list)
    for r in rows:
        groups[(r["num_shards"], r["bucket_field"])].append(r)

    speed_imgs=[]
    for (s,bf), gr in groups.items():
        base=None
        for r in gr:
            if r["max_jobs"]==1 and r["elapsed_s"]:
                base=r["elapsed_s"]; break
        if not base:
            continue
        gr=sorted(gr, key=lambda x: x["max_jobs"])
        x=[g["max_jobs"] for g in gr if g["elapsed_s"]]
        y=[base/g["elapsed_s"] for g in gr if g["elapsed_s"]]
        plt.figure()
        plt.xlabel("max_jobs")
        plt.ylabel("speedup vs max_jobs=1")
        plt.plot(x,y, marker="o")
        plt.title(f"Speedup (num_shards={s}, bucket={bf or 'none'})")
        img=f"benchmark/plots/speedup_s{s}_b{bf or 'none'}.png"
        plt.savefig(img, dpi=200)
        plt.close()
        speed_imgs.append(img)

    lines=[]
    lines.append("# Benchmark Report\\n\\n")
    lines.append("| case_id | elapsed_s | max_rss_mb | num_shards | max_jobs | bucket_field | exposure_n | purchase_n | intersection_size |\\n")
    lines.append("|---|---:|---:|---:|---:|---|---:|---:|---:|\\n")
    for r in rows:
        lines.append(f"| {r['case_id']} | {r['elapsed_s']} | {r['max_rss_mb']} | {r['num_shards']} | {r['max_jobs']} | {r['bucket_field']} | {r['exposure_n']} | {r['purchase_n']} | {r['intersection_size']} |\\n")
    lines.append("\\n## Plots\\n\\n")
    lines.append(f"![elapsed_vs_exposure]({img1})\\n\\n")
    for img in speed_imgs:
        lines.append(f"![{os.path.basename(img)}]({img})\\n\\n")

    os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report,"w",encoding="utf-8") as f: f.writelines(lines)
    print(f"OK. Wrote {args.report}")

if __name__=="__main__":
    main()
