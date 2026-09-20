# -*- coding: utf-8 -*-
"""批量重命名铁路电子客票(电子发票) PDF 为  YYYYMMDD_车次.pdf

退票发票(票面含退票费)命名为  YYYYMMDD_车次_T.pdf
改签发票(票面含改签费)命名为  YYYYMMDD_车次_G.pdf
日期取乘车日期, 车次为票面车次。

用法:
    python rename_invoices.py [目录 / PDF 文件 / 通配符 ...] [-n]
默认处理当前目录; -n, --dry-run 只预览不改名。
"""
import argparse
import glob
import os
import sys

import make_ticket


def target_stem(d):
    y, m, dd = d["travel_date"]
    train = d["train"]
    suffix = ("_T" if d.get("refund_fee") is not None else "") + \
             ("_G" if d.get("change_fee") is not None else "")
    return "%04d%02d%02d_%s%s" % (int(y), int(m), int(dd), train, suffix)


def unique_path(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    k = 2
    while os.path.exists("%s_%d%s" % (stem, k, ext)):
        k += 1
    return "%s_%d%s" % (stem, k, ext)


def main(argv=None):
    ap = argparse.ArgumentParser(description="将铁路电子客票 PDF 重命名为 YYYYMMDD_车次[_T][_G].pdf")
    ap.add_argument("paths", nargs="*", default=["."],
                    help="目录 / PDF 文件 / 通配符, 默认当前目录")
    ap.add_argument("-n", "--dry-run", action="store_true", help="只打印, 不实际改名")
    args = ap.parse_args(argv)

    files = []
    for p in args.paths:
        if os.path.isdir(p):
            files.extend(sorted(glob.glob(os.path.join(p, "*.pdf"))))
        else:
            found = glob.glob(p)
            files.extend(sorted(found) if found else [p])

    renamed = 0
    for src in files:
        name = os.path.basename(src)
        if ".ticket." in name or name.endswith("_pic.pdf"):
            continue
        try:
            d = make_ticket.parse_invoice(src)
        except Exception as exc:
            print("跳过(非铁路电子客票): %s -- %s" % (name, exc))
            continue
        if not (d.get("travel_date") and d.get("train")):
            print("跳过(缺少乘车日期或车次): %s" % name)
            continue
        dst = os.path.join(os.path.dirname(src), target_stem(d) + ".pdf")
        if os.path.normcase(dst) == os.path.normcase(src):
            print("已符合命名: %s" % name)
            continue
        dst = unique_path(dst)
        print("%s -> %s" % (name, os.path.basename(dst)))
        if not args.dry_run:
            os.rename(src, dst)
        renamed += 1

    print("共 %d 个文件%s" % (renamed, " (预览, 未实际改名)" if args.dry_run else "已重命名"))


if __name__ == "__main__":
    main()
