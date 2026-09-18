# -*- coding: utf-8 -*-
"""生成铁路电子客票报销凭证 PDF。

版面(元素位置/字号/字距)依据本目录参考图 cr 001.png (2046x1276 px) 逐像素测量标定,
字体经与参考图字形逐像素比对识别:
  - 中文  : 宋体 (SimSun, 归为 Sun, 模拟印刷墨迹加粗)
  - 数字字母: 黑体 (SimHei, 归为 Hei; 原图 3 平顶、2 平底、1 无底线, 为黑体数字特征)
  - 站名拼音: Times 系衬线体 (Times New Roman, 归为 Times)
生成时按比例缩放到 85.6mm 宽的卡片, 输出矢量 PDF。

用法:
    python make_ticket.py                        # 用默认数据生成 ticket.pdf
    python make_ticket.py -o my.pdf              # 指定输出文件
    python make_ticket.py --json data.json       # 从 JSON 读入字段值
    python make_ticket.py --preview              # 同时输出 PNG 预览

    # 从电子发票(铁路电子客票)生成:
    python make_ticket.py --invoice a.pdf b.pdf --preview
    python make_ticket.py --invoice "C:/.../车票/*.pdf" --outdir out --preview
"""
import argparse
import datetime as _dt
import glob
import io
import json
import os
import re

from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

try:
    import qrcode
except ImportError:
    qrcode = None

HERE = os.path.dirname(os.path.abspath(__file__))
REF_W, REF_H = 2046.0, 1276.0
MM2PT = 72.0 / 25.4
PAGE_W_MM = 85.6
PX = PAGE_W_MM * MM2PT / REF_W
PAGE_W, PAGE_H = REF_W * PX, REF_H * PX

FONTS = {
    "Sun": [
        (r"C:\Windows\Fonts\simsun.ttc", 0),
        (r"C:\Windows\Fonts\simsun.ttf", 0),
        (r"/usr/share/fonts/truetype/arphic/uming.ttc", 0),
        (r"/System/Library/Fonts/Supplemental/Songti.ttc", 0),
    ],
    "Hei": [
        (r"C:\Windows\Fonts\simhei.ttf", 0),
        (r"/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
        (r"/System/Library/Fonts/Supplemental/Heiti SC.ttc", 0),
    ],
    "HeiR": [
        (r"C:\Windows\Fonts\simhei.ttf", 0),
        (r"/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
        (r"/System/Library/Fonts/Supplemental/Heiti SC.ttc", 0),
    ],
    "ZS": [
        (r"C:\Windows\Fonts\STZHONGS.TTF", 0),
        (r"C:\Windows\Fonts\simsun.ttc", 0),
        (r"/usr/share/fonts/fonts-go/STZhongsong.ttf", 0),
    ],
    "CoreDS": [
        (os.path.join(HERE, "fonts", "CoreSansDS35Regular.ttf"), 0),
        (r"C:\Windows\Fonts\CoreSansDS35Regular.ttf", 0),
    ],
    "Times": [
        (r"C:\Windows\Fonts\times.ttf", 0),
        (r"/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf", 0),
        (r"/System/Library/Fonts/Supplemental/Times New Roman.ttf", 0),
    ],
    "Camb": [
        (r"C:\Windows\Fonts\cambria.ttc", 0),
        (r"/usr/share/fonts/truetype/crosextra/Caladea-Regular.ttf", 0),
        (r"C:\Windows\Fonts\times.ttf", 0),
    ],
}
REGISTERED = {}

INK = Color(78 / 255, 71 / 255, 87 / 255)
RED = Color(201 / 255, 107 / 255, 130 / 255)
QR_COLOR = Color(74 / 255, 69 / 255, 90 / 255)
BAND = Color(148 / 255, 192 / 255, 229 / 255)
BG_STOPS = [
    (0.00, Color(188 / 255, 213 / 255, 243 / 255)),
    (0.30, Color(208 / 255, 231 / 255, 254 / 255)),
    (0.55, Color(218 / 255, 238 / 255, 255 / 255)),
    (1.00, Color(198 / 255, 224 / 255, 252 / 255)),
]
EDGE_DARK = Color(126 / 255, 156 / 255, 190 / 255)
EDGE_LIGHT = Color(232 / 255, 244 / 255, 255 / 255)

CARD_RADIUS = 95.0
BAND_TOP = 1141.0

DASH_BOX = (226.0, 900.0, 1404.0, 1077.0)
DASH_ON, DASH_OFF, DASH_W = 34.0, 10.5, 5.0

CIRCLES = [(899.5, 518.0, 45.5, "学"), (1029.0, 518.0, 45.5, "惠")]
CIRCLE_W = 5.0

QR_BOX = (1558.0, 757.5, 4, 10.121, 9.97)

CR_Y = 1133.0
CR_SIZE, CR_SX = 30.0, 2.60
CR_START, CR_STEP = 23.0, 44.5
CR_TINT = Color(184 / 255, 210 / 255, 240 / 255)

# 字体分配(按用户指定):
#   站名(合肥南/济南西) = 黑体 SimHei 标准(小"站"字为华文中宋)
#   其余汉字        = 华文中宋 STZhongsong 标准
#   车次           = Times New Roman
#   ￥            = 宋体 SimSun
#   日期/时间/座位/票价/证件号数字 = Core Sans DS 35 Regular(不描边, 字距收紧 -6~-6.5px)
#   "元" 与 年/月/日 同高; "学"/"惠" 放大撑满圆圈; JM 正常比例(不横向拉伸)
#   检票口/底部序列号 = Cambria(替代原衬线数字)
#   站名拼音        = Times New Roman
# 描边宽度为字号的比例(0 表示标准字重不加描边)
STROKE_BY_FONT = {"Sun": 0.028, "Hei": 0.020, "HeiR": 0.0, "ZS": 0.0,
                  "CoreDS": 0.0, "Times": 0.022, "Camb": 0.008}
RED_STROKE = 0.016

# 逐字符字距(页面px): 数字紧凑, 接近原图几乎无字间距的效果
TRACKING = {"date_y": -6.5, "date_m": -6.0, "date_d": -6.0, "date_hm": -6.5,
            "coach": -6.5, "seat": -6.5, "price_int": -6.0, "price_dec": -6.0, "id": -6.5}

# 参考图逐像素标定: 名称 -> (字号px, 横向缩放, 绘制起点x, 基线y, 字体, 参考文本)
LAYOUT = {
    "red":        (117.39, 1.0036, 112.88, 153.29, "Hei", "A00B000000"),
    "gate_cn":    (81.22, 0.9959, 1597.79, 95.14, "ZS", "检票"),
    "gate_colon": (79.37, 1.5429, 1762.84, 100.00, "Camb", ":"),
    "gate_code":  (86.51, 0.9755, 1787.68, 96.31, "Camb", "20A"),
    "from_name":  (128.19, 1.0524, 221.18, 252.60, "HeiR", "合肥南"),
    "from_zhan":  (69.63, 1.1590, 642.89, 233.50, "ZS", "站"),
    "from_py":    (80.51, 0.9442, 310.71, 333.95, "Times", "Hefeinan"),
    "train_no":   (124.19, 1.0162, 934.59, 253.13, "Times", "G46"),
    "to_name":    (125.94, 1.0907, 1277.56, 249.72, "HeiR", "济南西"),
    "to_zhan":    (68.55, 1.1467, 1701.95, 230.62, "ZS", "站"),
    "to_py":      (81.69, 0.9430, 1448.38, 332.77, "Times", "Jinanxi"),
    "date_y":     (104.97, 0.9994, 152.68, 448.76, "CoreDS", "2025"),
    "date_yn":    (56.08, 0.9611, 355.93, 429.99, "ZS", "年"),
    "date_m":     (103.59, 1.0159, 433.56, 447.77, "CoreDS", "06"),
    "date_mn":    (62.22, 0.8869, 545.21, 431.82, "ZS", "月"),
    "date_d":     (103.59, 1.0723, 624.39, 447.79, "CoreDS", "23"),
    "date_dn":    (58.89, 1.0018, 729.99, 430.55, "ZS", "日"),
    "date_hm":    (107.82, 1.1021, 807.49, 447.72, "CoreDS", "18:55"),
    "date_kai":   (55.31, 0.9936, 1062.85, 429.45, "ZS", "开"),
    "coach":      (104.84, 1.0889, 1312.95, 446.78, "CoreDS", "13"),
    "coach_che":  (58.02, 0.9336, 1414.22, 430.89, "ZS", "车"),
    "seat":       (104.75, 1.0440, 1476.41, 446.70, "CoreDS", "16F"),
    "seat_hao":   (57.60, 0.9546, 1627.89, 428.92, "ZS", "号"),
    "price_yen":  (104.52, 0.7306, 162.48, 554.41, "Sun", "￥"),
    "price_int":  (100.66, 1.0695, 243.57, 552.74, "CoreDS", "235."),
    "price_dec":  (100.83, 1.1328, 430.06, 552.75, "CoreDS", "0"),
    "price_yuan": (62.51, 1.0896, 481.80, 543.67, "ZS", "元"),
    "seat_class": (83.20, 1.0040, 1476.29, 541.60, "ZS", "二等座"),
    "notice":     (82.34, 1.0328, 138.82, 745.45, "ZS", "仅供报销使用"),
    "refund_fee": (82.34, 1.0328, 138.82, 637.45, "ZS", "退票费"),
    "id":         (105.06, 0.9869, 131.52, 872.69, "CoreDS", "1101011990****1234"),
    "name":       (94.88, 1.0029, 1006.14, 862.89, "ZS", "张三"),
    "box1a":      (65.03, 1.0313, 531.13, 965.00, "ZS", "报销凭证"),
    "box1b":      (64.89, 1.0365, 826.38, 964.76, "ZS", "遗失不补"),
    "box2":       (70.68, 0.9559, 474.65, 1056.67, "ZS", "退票改签时须交回车站"),
    "serial":     (85.04, 0.8105, 127.00, 1207.32, "Camb", "12345678901234567890123"),
    "serial_jm":  (67.67, 1.0000, 973.03, 1194.15, "Camb", "JM"),
    "mark_xue":   (90.71, 1.0000, 852.65, 545.39, "ZS", "学"),
    "mark_hui":   (90.41, 1.0000, 983.75, 546.66, "ZS", "惠"),
}

TRAIN_ARROW = (863.0, 1213.0, 1160.0, 278.0, 259.0)

# 电子发票席别识别顺序(由特殊到一般)
CLASS_PATTERNS = [
    r"商务座", r"特等座", r"优选一等座", r"一等包座", r"二等包座",
    r"新空调硬卧", r"新空调软卧", r"新空调硬座",
    r"高级软卧", r"动卧", r"软卧", r"硬卧", r"软座", r"硬座",
    r"一等座", r"二等座", r"无座",
]


def register_fonts():
    for key, candidates in FONTS.items():
        for path, idx in candidates:
            if os.path.exists(path):
                try:
                    pdfmetrics.registerFont(TTFont(key, path, subfontIndex=idx))
                    REGISTERED[key] = path
                    break
                except Exception:
                    continue
        if key not in REGISTERED:
            raise RuntimeError("未找到字体 %s, 请检查系统字体或修改 FONTS 配置" % key)


def X(px):
    return px * PX


def Y(px):
    return (REF_H - px) * PX


def advance_px(text, size_px, sx, font=None):
    if font is None:
        font = LAYOUT["red"][4]
    return pdfmetrics.stringWidth(text, font, size_px * PX) * sx / PX


class Ticket:
    def __init__(self, **kw):
        self.ticket_no = kw.get("ticket_no", "A00B000000")
        self.gate = kw.get("gate", "20A")
        self.from_station = kw.get("from_station", "合肥南")
        self.from_pinyin = kw.get("from_pinyin", "Hefeinan")
        self.to_station = kw.get("to_station", "济南西")
        self.to_pinyin = kw.get("to_pinyin", "Jinanxi")
        self.train_no = kw.get("train_no", "G46")
        depart = kw.get("depart", "2025-06-23 18:55")
        if isinstance(depart, str):
            depart = _dt.datetime.strptime(depart, "%Y-%m-%d %H:%M")
        self.depart = depart
        self.coach = kw.get("coach", "13")
        self.seat = kw.get("seat", "16F")
        self.seat_suffix = kw.get("seat_suffix", "号")
        self.price = float(kw.get("price", 235.0))
        self.seat_class = kw.get("seat_class", "二等座")
        self.discount = bool(kw.get("discount", True))
        self.passenger = kw.get("passenger", "张三")
        self.id_no = kw.get("id_no", "1101011990****1234")
        self.serial = kw.get("serial", "12345678901234567890123")
        self.serial_suffix = kw.get("serial_suffix", "JM")
        self.refund_fee = kw.get("refund_fee")
        self.qr_data = kw.get("qr_data")
        self.qr_image = kw.get("qr_image")
        self.texture = bool(kw.get("texture", True))

    @classmethod
    def from_json(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            return cls(**json.load(f))

    @classmethod
    def from_invoice(cls, path, use_qr_image=True):
        d = parse_invoice(path)
        y, m, dd = (int(v) for v in d["travel_date"]) if d.get("travel_date") else (2025, 1, 1)
        hh, mi = (int(v) for v in d["time"]) if d.get("time") else (0, 0)
        return cls(
            ticket_no=d.get("invoice_no") or "A00B000000",
            gate=None,
            from_station=(d.get("from_station") or "合肥").rstrip("站"),
            from_pinyin=d.get("from_pinyin") or "",
            to_station=(d.get("to_station") or "济南").rstrip("站"),
            to_pinyin=d.get("to_pinyin") or "",
            train_no=d.get("train") or "G46",
            depart=_dt.datetime(y, m, dd, hh, mi),
            coach=d.get("coach") or "13",
            seat=d.get("seat") or "",
            seat_suffix=d.get("seat_suffix") or "号",
            price=d.get("price") if d.get("price") is not None else 0.0,
            seat_class=d.get("seat_class") or "二等座",
            discount=bool(d.get("discount")),
            passenger=d.get("passenger") or "张三",
            id_no=d.get("id_no") or "1101011990****1234",
            serial=d.get("eticket_no") or "",
            serial_suffix="",
            refund_fee=d.get("refund_fee"),
            qr_image=d.get("qr") if use_qr_image else None,
            texture=True,
        )


def parse_invoice(path):
    """从电子发票(铁路电子客票) PDF 中提取票面字段。"""
    import fitz
    doc = fitz.open(path)
    page = doc.load_page(0)
    text = page.get_text()
    flat = re.sub(r"\s+", "", text)
    words = [(w[0], w[1], w[2], w[3], w[4]) for w in page.get_text("words")]
    d = {}

    m = re.search(r"发票号码[:：](\d+)", flat)
    d["invoice_no"] = m.group(1) if m else None
    m = re.search(r"电子客票号[:：](\d+)", flat)
    d["eticket_no"] = m.group(1) if m else None

    print_m = re.search(r"开票日期[:：](\d{4})年(\d{1,2})月(\d{1,2})日", flat)
    print_span = print_m.span() if print_m else None
    travel = None
    for mm in re.finditer(r"(\d{4})年(\d{1,2})月(\d{1,2})日", flat):
        if print_span and mm.start() >= print_span[0] and mm.end() <= print_span[1]:
            continue
        travel = mm.groups()
        break
    d["travel_date"] = travel

    m = re.search(r"(\d{1,2}):(\d{2})开", flat)
    d["time"] = (m.group(1), m.group(2)) if m else None

    train = None
    for (x0, y0, x1, y1, w) in words:
        if re.fullmatch(r"[GDCKZTSY]\d{1,4}", w):
            train = w
            break
    if train is None:
        m = re.search(r"(?<![0-9A-Za-z])([GDCKZTSY]\d{1,4})(?![0-9])", flat)
        train = m.group(1) if m else None
    d["train"] = train

    stations = sorted([(x0, y0, w) for (x0, y0, x1, y1, w) in words
                       if len(w) >= 2 and w.endswith("站")], key=lambda t: (t[1], t[0]))
    if len(stations) >= 2:
        d["from_station"], d["to_station"] = stations[0][2], stations[-1][2]
        fx, tx = stations[0][0], stations[-1][0]
    else:
        d["from_station"] = d["to_station"] = None
        fx = tx = None

    latin = [(x0, y0, x1, y1, w) for (x0, y0, x1, y1, w) in words if re.fullmatch(r"[A-Za-z]{2,20}", w)]
    latin.sort(key=lambda t: (round(t[1] / 4), t[0]))
    tokens = []
    for (x0, y0, x1, y1, w) in latin:
        if tokens and abs(tokens[-1][1] - y0) <= 4 and x0 - tokens[-1][2] <= 20:
            tokens[-1] = (tokens[-1][0], tokens[-1][1], x1, tokens[-1][3] + w)
        else:
            tokens.append((x0, y0, x1, w))
    if len(tokens) >= 2 and fx is not None:
        tokens.sort(key=lambda t: t[0])
        pick = []
        for target in (fx, tx):
            cands = [t for t in tokens if t not in pick]
            best = min(cands, key=lambda t: abs(t[0] - target))
            pick.append(best)
        d["from_pinyin"], d["to_pinyin"] = pick[0][3], pick[1][3]
    elif len(tokens) >= 2:
        d["from_pinyin"], d["to_pinyin"] = tokens[0][3], tokens[1][3]
    else:
        d["from_pinyin"] = d["to_pinyin"] = None

    seat_word = None
    for (x0, y0, x1, y1, w) in words:
        mm = re.fullmatch(r"(\d{1,2})车(.+)", w)
        if mm and not seat_word:
            seat_word = mm
    if seat_word is None:
        seat_word = re.search(r"(\d{1,2})车(\d{1,4}[A-Z]?号[\u4e00-\u9fff]{0,2}|无座)", flat)
    if seat_word:
        d["coach"] = seat_word.group(1)
        rest = seat_word.group(2)
        if "号" in rest:
            seat, tail = rest.split("号", 1)
            d["seat"], d["seat_suffix"] = seat, "号" + tail
        else:
            d["seat"], d["seat_suffix"] = "", rest
    else:
        d["coach"], d["seat"], d["seat_suffix"] = None, None, None

    # 退票费: 定位"退票费"标签词, 取同一行右侧的金额词; 仅出现标签无金额时记为 0
    d["refund_fee"] = None
    for (wx0, wy0, wx1, wy1, w) in words:
        if w.startswith("退票费"):
            fee = None
            for (ax0, ay0, ax1, ay1, aw) in words:
                if ax0 > wx0 and abs(ay0 - wy0) <= 12:
                    mm = re.fullmatch(r"[¥￥](\d+(?:\.\d{1,2})?)", aw)
                    if mm:
                        fee = float(mm.group(1))
                        break
            d["refund_fee"] = fee if fee is not None else 0.0
            break

    m = re.search(r"[¥￥](\d+(?:\.\d{1,2})?)", flat)
    d["price"] = float(m.group(1)) if m else None

    d["seat_class"] = None
    for pat in CLASS_PATTERNS:
        mm = re.search(pat, flat)
        if mm:
            d["seat_class"] = mm.group(0)
            break

    d["discount"] = any(w == "学" for (*_r, w) in words)

    m = re.search(r"\d{6,}\*+\d{2,4}", flat)
    d["id_no"] = m.group(0) if m else None
    d["passenger"] = None
    idw = None
    for (x0, y0, x1, y1, w) in words:
        if m and w == m.group(0):
            idw = (x0, y0, x1, y1)
    if idw:
        cy = (idw[1] + idw[3]) / 2
        cands = [(x0, y0, x1, y1, w) for (x0, y0, x1, y1, w) in words
                 if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", w) and not w.endswith("站")]
        same_row = [c for c in cands if abs((c[1] + c[3]) / 2 - cy) <= 12]
        if same_row:
            d["passenger"] = min(same_row, key=lambda c: abs(c[0] - idw[2]))[4]
        elif cands:
            d["passenger"] = min(
                cands,
                key=lambda c: ((c[0] + c[2]) / 2 - (idw[0] + idw[2]) / 2) ** 2
                + ((c[1] + c[3]) / 2 - cy) ** 2)[4]

    d["qr"] = None
    for img in page.get_images(full=True):
        info = doc.extract_image(img[0])
        if abs(info["width"] - info["height"]) <= 4 and info["width"] >= 100:
            d["qr"] = info["image"]

    if "铁路电子客票" not in flat or not (d["train"] and d["from_station"] and d["to_station"]):
        raise ValueError("不是铁路电子客票(电子发票) PDF")
    return d


def draw_text(c, text, key, color=INK, dx=0.0, dy=0.0, size=None, sx=None, stroke=None, track=None):
    size_px, sxf, x, base, font_key, _ = LAYOUT[key]
    if size is not None:
        size_px = size
    if sx is not None:
        sxf = sx
    if stroke is None:
        stroke = RED_STROKE if color is RED else STROKE_BY_FONT.get(font_key, 0.02)
    if track is None:
        track = TRACKING.get(key, 0.0)
    if track:
        cur = x + dx
        for ch in text:
            c.saveState()
            c.setFillColor(color)
            c.setFont(font_key, size_px * PX)
            c.translate(X(cur), Y(base + dy))
            if sxf != 1.0:
                c.scale(sxf, 1.0)
            if stroke:
                c.setStrokeColor(color)
                c.setLineWidth(size_px * stroke * PX)
                c._textRenderMode = 2
            c.drawString(0, 0, ch)
            c.restoreState()
            cur += sxf * advance_px(ch, size_px, 1.0, font_key) + track
        return sxf * advance_px(text, size_px, 1.0, font_key) + track * (len(text) - 1)
    c.saveState()
    c.setFillColor(color)
    c.setFont(font_key, size_px * PX)
    c.translate(X(x + dx), Y(base + dy))
    if sxf != 1.0:
        c.scale(sxf, 1.0)
    if stroke:
        c.setStrokeColor(color)
        c.setLineWidth(size_px * stroke * PX)
        c._textRenderMode = 2
    c.drawString(0, 0, text)
    c.restoreState()
    return advance_px(text, size_px, sxf, font_key)


def fit_scale(text, key, min_sx=0.6):
    size_px, sx, x, base, font_key, ref = LAYOUT[key]
    nat_ref = pdfmetrics.stringWidth(ref, font_key, size_px * PX)
    nat_new = pdfmetrics.stringWidth(text, font_key, size_px * PX)
    target = nat_ref * sx
    if nat_new * sx <= target:
        return size_px, sx
    sx_out = target / nat_new
    if sx_out >= min_sx:
        return size_px, sx_out
    return size_px * sx_out / min_sx, min_sx


def make_qr_transparent(data):
    try:
        from PIL import Image
    except ImportError:
        return data
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    px = im.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = px[x, y]
            if r > 190 and g > 190 and b > 190:
                px[x, y] = (r, g, b, 0)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def draw_qr_image(c, data):
    from reportlab.lib.utils import ImageReader
    x0, y0, version, mw, mh = QR_BOX
    modules = version * 4 + 17
    w, h = modules * mw, modules * mh
    c.drawImage(ImageReader(io.BytesIO(make_qr_transparent(data))),
                X(x0), Y(y0 + h), width=w * PX, height=h * PX, mask="auto")


def make_texture(width_px, height_px):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    img = Image.new("RGBA", (int(width_px), int(height_px)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    tile, dash = 8, 6
    col = (150, 190, 232, 15)
    for j, y in enumerate(range(-dash, int(height_px) + tile, tile)):
        off = (tile // 2) if j % 2 else 0
        for x in range(-dash, int(width_px) + tile, tile):
            x0 = x + off
            d.line([(x0, y + dash), (x0 + dash, y)], fill=col, width=1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def draw_card_background(c, t: Ticket):
    c.saveState()
    path = c.beginPath()
    path.roundRect(0, 0, PAGE_W, PAGE_H, X(CARD_RADIUS))
    c.clipPath(path, stroke=0, fill=0)
    c.linearGradient(
        X(0), Y(0), X(0), Y(BAND_TOP),
        colors=[col for _, col in BG_STOPS],
        positions=[pos for pos, _ in BG_STOPS],
    )
    if t.texture:
        buf = make_texture(X(REF_W), Y(BAND_TOP))
        if buf is not None:
            c.drawImage(
                __import__("reportlab.lib.utils", fromlist=["ImageReader"]).ImageReader(buf),
                0, Y(BAND_TOP), width=PAGE_W, height=Y(0) - Y(BAND_TOP),
                mask="auto",
            )
    c.setFillColor(BAND)
    c.rect(0, 0, PAGE_W, Y(BAND_TOP), stroke=0, fill=1)
    c.restoreState()

    c.saveState()
    c.setStrokeColor(EDGE_LIGHT)
    c.setLineWidth(2.0 * PX)
    c.roundRect(1.0 * PX, 1.0 * PX, PAGE_W - 2.0 * PX, PAGE_H - 2.0 * PX, X(CARD_RADIUS), stroke=1, fill=0)
    c.setStrokeColor(EDGE_DARK)
    c.setLineWidth(0.7 * PX)
    c.roundRect(0.4 * PX, 0.4 * PX, PAGE_W - 0.8 * PX, PAGE_H - 0.8 * PX, X(CARD_RADIUS), stroke=1, fill=0)
    c.restoreState()


def draw_cr_pattern(c):
    c.saveState()
    c.setFillColor(CR_TINT)
    c.setFont("Times", CR_SIZE * PX)
    k = 0
    x = CR_START
    while x < REF_W - 10:
        ch = "C" if k % 2 == 0 else "R"
        c.saveState()
        c.translate(X(x), Y(CR_Y))
        c.scale(CR_SX, 1.0)
        c.drawString(0, 0, ch)
        c.restoreState()
        k += 1
        x += CR_STEP
    c.restoreState()


def draw_dashed_box(c):
    x0, y0, x1, y1 = DASH_BOX
    c.saveState()
    c.setStrokeColor(INK)
    c.setLineWidth(DASH_W * PX)
    c.setDash([DASH_ON * PX, DASH_OFF * PX])
    c.rect(X(x0), Y(y1), X(x1) - X(x0), Y(y0) - Y(y1), stroke=1, fill=0)
    c.restoreState()


def draw_qr(c, data):
    if qrcode is None:
        raise RuntimeError("缺少 qrcode 库, 请先 pip install qrcode")
    x0, y0, version, mw, mh = QR_BOX
    qr = qrcode.QRCode(version=version, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=0)
    qr.add_data(data)
    try:
        qr.make(fit=False)
    except qrcode.exceptions.DataOverflowError:
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=1, border=0)
        qr.add_data(data)
        qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    mx, my = mw * (version * 4 + 17) / n, mh * (version * 4 + 17) / n
    c.saveState()
    c.setFillColor(QR_COLOR)
    for r, row in enumerate(matrix):
        for col, dark in enumerate(row):
            if dark:
                c.rect(X(x0 + col * mx), Y(y0 + (r + 1) * my), mx * PX, my * PX, stroke=0, fill=1)
    c.restoreState()


def draw_circles(c, t: Ticket):
    if not t.discount:
        return
    for cx, cy, r, ch in CIRCLES:
        c.saveState()
        c.setStrokeColor(INK)
        c.setLineWidth(CIRCLE_W * PX)
        c.circle(X(cx), Y(cy), X(r), stroke=1, fill=0)
        c.restoreState()
        draw_text(c, ch, "mark_xue" if ch == "学" else "mark_hui")


def draw_arrow(c):
    x0, x1, xb, y, yb = TRAIN_ARROW
    c.saveState()
    c.setStrokeColor(INK)
    c.setLineWidth(5.0 * PX)
    c.setLineCap(1)
    c.line(X(x0), Y(y), X(x1), Y(y))
    c.line(X(xb), Y(yb), X(x1), Y(y))
    c.restoreState()


def build_ticket(t: Ticket, out_path: str):
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    c = canvas.Canvas(out_path, pagesize=(PAGE_W, PAGE_H))
    c.setTitle("铁路电子客票报销凭证")
    draw_card_background(c, t)
    draw_cr_pattern(c)
    draw_dashed_box(c)
    draw_arrow(c)

    date = t.depart
    coach_new = t.coach
    seat_new = t.seat

    def width_delta(key, text):
        size_px, sxf, _, _, font_key, ref = LAYOUT[key]
        return advance_px(text, size_px, sxf, font_key) - advance_px(ref, size_px, sxf, font_key)

    # 两字站名: 中间加一字宽空格
    from_name_s = t.from_station[0] + "\u3000" + t.from_station[1] if len(t.from_station) == 2 else t.from_station
    to_name_s = t.to_station[0] + "\u3000" + t.to_station[1] if len(t.to_station) == 2 else t.to_station
    # 四字站名: "站"略微右移
    from_zhan_slip = 12.0 if len(t.from_station) == 4 else 0.0
    to_zhan_slip = 12.0 if len(t.to_station) == 4 else 0.0

    d_name = width_delta("from_name", from_name_s)
    d_namer = width_delta("to_name", to_name_s)
    d_coach = width_delta("coach", coach_new)
    d_seat = width_delta("seat", seat_new)
    d_id = width_delta("id", t.id_no)

    red_size, red_sx = fit_scale(t.ticket_no, "red")
    draw_text(c, t.ticket_no, "red", RED, size=red_size, sx=red_sx)
    if t.gate is not None:
        draw_text(c, "检票", "gate_cn")
        draw_text(c, ":", "gate_colon")
        if t.gate:
            draw_text(c, t.gate, "gate_code")

    train_ref = LAYOUT["train_no"][5]
    train_font = LAYOUT["train_no"][4]
    d_train = (advance_px(train_ref, LAYOUT["train_no"][0], LAYOUT["train_no"][1], train_font)
               - advance_px(t.train_no, LAYOUT["train_no"][0], LAYOUT["train_no"][1], train_font)) / 2
    draw_text(c, from_name_s, "from_name")
    draw_text(c, "站", "from_zhan", dx=d_name + from_zhan_slip)
    draw_text(c, t.from_pinyin, "from_py", dx=d_name / 2)
    draw_text(c, t.train_no, "train_no", dx=d_train)
    draw_text(c, to_name_s, "to_name", dx=-d_namer)
    draw_text(c, "站", "to_zhan", dx=to_zhan_slip)
    draw_text(c, t.to_pinyin, "to_py", dx=-d_namer / 2)

    draw_text(c, "%04d" % date.year, "date_y")
    draw_text(c, "年", "date_yn")
    draw_text(c, "%02d" % date.month, "date_m")
    draw_text(c, "月", "date_mn")
    draw_text(c, "%02d" % date.day, "date_d")
    draw_text(c, "日", "date_dn")
    draw_text(c, "%02d:%02d" % (date.hour, date.minute), "date_hm")
    draw_text(c, "开", "date_kai")

    draw_text(c, coach_new, "coach", dx=-d_coach)
    draw_text(c, "车", "coach_che")
    if seat_new:
        draw_text(c, seat_new, "seat", dx=-d_seat)
    if t.seat_suffix:
        suffix_dx = 0.0 if seat_new else LAYOUT["seat"][2] - LAYOUT["seat_hao"][2]
        draw_text(c, t.seat_suffix, "seat_hao", dx=suffix_dx)

    # 金额自 ￥ 起向左对齐流动, "元"跟随金额字符数移动
    yuan = int(abs(t.price))
    dec = int(round(abs(t.price) * 10)) % 10
    d_price = width_delta("price_int", "%d." % yuan)
    d_dec = (advance_px("%d" % dec, LAYOUT["price_dec"][0], LAYOUT["price_dec"][1], LAYOUT["price_dec"][4])
             - advance_px("0", LAYOUT["price_dec"][0], LAYOUT["price_dec"][1], LAYOUT["price_dec"][4]))
    draw_text(c, "￥", "price_yen")
    draw_text(c, "%d." % yuan, "price_int")
    draw_text(c, "%d" % dec, "price_dec", dx=d_price)
    draw_text(c, "元", "price_yuan", dx=d_price + d_dec)
    class_font = LAYOUT["seat_class"][4]
    d_class = advance_px(t.seat_class, LAYOUT["seat_class"][0], LAYOUT["seat_class"][1], class_font) - \
        advance_px("二等座", LAYOUT["seat_class"][0], LAYOUT["seat_class"][1], class_font)
    draw_text(c, t.seat_class, "seat_class", dx=-d_class)

    draw_text(c, "仅供报销使用", "notice")
    if t.refund_fee is not None:
        draw_text(c, "退票费", "refund_fee")
    draw_text(c, t.id_no, "id")
    draw_text(c, t.passenger, "name", dx=d_id)
    draw_circles(c, t)

    draw_text(c, "报销凭证", "box1a")
    draw_text(c, "遗失不补", "box1b")
    draw_text(c, "退票改签时须交回车站", "box2")

    ser_size, ser_sx = fit_scale(t.serial, "serial")
    draw_text(c, t.serial, "serial", size=ser_size, sx=ser_sx)
    if t.serial_suffix:
        ser_font = LAYOUT["serial"][4]
        adv_new = advance_px(t.serial, ser_size, ser_sx, ser_font)
        adv_ref = advance_px(LAYOUT["serial"][5], LAYOUT["serial"][0], LAYOUT["serial"][1], ser_font)
        draw_text(c, t.serial_suffix, "serial_jm", dx=adv_new - adv_ref)

    if t.qr_image:
        draw_qr_image(c, t.qr_image)
    else:
        draw_qr(c, t.qr_data or t.serial)
    c.showPage()
    c.save()


def render_preview(pdf_path, png_path, target_w=2046):
    try:
        import fitz
    except ImportError:
        print("未安装 PyMuPDF, 跳过预览")
        return
    doc = fitz.open(pdf_path)
    page = doc.load_page(0)
    zoom = target_w / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    pix.save(png_path)
    doc.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description="按参考图版面生成铁路电子客票报销凭证 PDF")
    ap.add_argument("output", nargs="?", default="ticket.pdf", help="输出 PDF 路径(默认模式)")
    ap.add_argument("-o", "--out", help="输出 PDF 路径(单张)或输出目录(批量)")
    ap.add_argument("--json", help="从 JSON 文件读取票面数据")
    ap.add_argument("--invoice", nargs="+", metavar="PDF",
                    help="从电子发票(铁路电子客票) PDF 生成, 可多个文件或通配符")
    ap.add_argument("--outdir", help="电子发票批量模式的输出目录(默认与发票同目录)")
    ap.add_argument("--preview", action="store_true", help="同时生成 PNG 预览")
    ap.add_argument("--no-texture", action="store_true", help="不绘制纸张纹理")
    ap.add_argument("--no-invoice-qr", action="store_true", help="不使用发票内二维码图, 改用程序生成")
    args = ap.parse_args(argv)

    register_fonts()

    if args.invoice:
        paths = []
        for pat in args.invoice:
            found = glob.glob(pat)
            paths.extend(sorted(found) if found else [pat])
        if not paths:
            ap.error("未找到发票文件")
        for path in paths:
            if not os.path.exists(path):
                print("跳过(不存在):", path)
                continue
            try:
                ticket = Ticket.from_invoice(path, use_qr_image=not args.no_invoice_qr)
            except Exception as exc:
                print("解析失败 %s: %s" % (path, exc))
                continue
            if args.no_texture:
                ticket.texture = False
            stem = os.path.splitext(os.path.basename(path))[0]
            if args.out and len(paths) == 1:
                out = args.out
            else:
                outdir = args.outdir or os.path.dirname(os.path.abspath(path))
                out = os.path.join(outdir, stem + ".ticket.pdf")
            build_ticket(ticket, out)
            print("已生成:", out)
            if args.preview:
                png = os.path.splitext(out)[0] + ".png"
                render_preview(out, png)
                print("已生成预览:", png)
        return

    out = args.out or args.output
    ticket = Ticket.from_json(args.json) if args.json else Ticket()
    if args.no_texture:
        ticket.texture = False
    build_ticket(ticket, out)
    print("已生成:", out)
    if args.preview:
        png = os.path.splitext(out)[0] + ".png"
        render_preview(out, png)
        print("已生成预览:", png)


if __name__ == "__main__":
    main()
