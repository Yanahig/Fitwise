"""生成回归题库的材料（合成数据，可复现）。

用法：
    .venv\\Scripts\\python.exe scripts\\make_testset_materials.py

产物（scripts/testset/，配套的答题卡是 scripts/testset/expected.json）：

    01-招标需求书.pdf        长材料：关键约束埋在第 8 节，含表格与规模指标
    02-答疑与补充通知.pdf    与 01 配套：改工期（口径冲突）+ 补档案类型清单
    03-客户往来邮件.txt      纯文本：寒暄里夹一条真正的变更（无页码材料）
    04-扫描件.pdf            图片型 PDF：没有文字层，考验"读不出来要明说"
    05-超范围需求清单.pdf    需求集中砸在能力库明确写不支持的点上
    06-损坏文件.pdf          故意损坏：必须明确失败并给出成因，不能静默产出空内容

为什么这些材料放在 scripts/testset/ 而不是 demo/：
  demo/ 是现场演示用的两份材料，demo_rehearsal.py 会 glob 整个目录 ——
  往里面加文件会把演示流程带偏，所以题库单独放一个目录。

企业内部知识库不在这里（server/seed/knowledge_base.json 预置的星云科技）。
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

styles = getSampleStyleSheet()
TITLE = ParagraphStyle("ts-title", parent=styles["Title"], fontName="STSong-Light", fontSize=16, leading=24)
H2 = ParagraphStyle("ts-h2", parent=styles["Heading2"], fontName="STSong-Light", fontSize=12, leading=18)
BODY = ParagraphStyle("ts-body", parent=styles["BodyText"], fontName="STSong-Light", fontSize=10.5, leading=17)
NOTE = ParagraphStyle("ts-note", parent=BODY, fontSize=9.5, textColor="#555555")

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "scripts" / "testset"


def build(path: Path, story: list) -> None:
    doc = SimpleDocTemplate(str(path), pagesize=A4, topMargin=20 * mm, bottomMargin=18 * mm, title=path.stem)
    doc.build(story)
    print(f"generated: {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


def table(rows: list[list[str]], widths: list[float]) -> Table:
    item = Table(rows, colWidths=widths, hAlign="LEFT")
    item.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.4, "#999999"),
                ("BACKGROUND", (0, 0), (-1, 0), "#EEEEEE"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return item


def rfp_story() -> list:
    """01：长材料。关键约束故意放在第 8 节（后段），规模指标用表格给。"""
    return [
        Paragraph("XX市城建档案馆 工程图纸与档案数字化平台建设项目 招标需求书", TITLE),
        Spacer(1, 10),
        Paragraph("1. 项目背景与现状", H2),
        Paragraph(
            "我馆现有馆藏档案约 380 万件，其中工程图纸、竣工资料与照片档案占比约 45%，"
            "历史档案数字化率不足 35%。本项目拟建设统一的档案数字化与智能处理平台，"
            "实现扫描件入库、字段结构化、全文检索与长期保存，并与现有城建业务系统对接。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("2. 建设范围", H2),
        Paragraph(
            "2.1 档案扫描与图像预处理；2.2 字段结构化与目录数据著录；2.3 全文检索与借阅流程；"
            "2.4 与城建业务系统、办公系统的数据对接；2.5 数据长期保存与备份。",
            BODY,
        ),
        PageBreak(),
        Paragraph("3. 技术要求", H2),
        Paragraph(
            "3.1 部署方式：系统须在馆内网全离线私有化部署，不得依赖任何公有云服务，"
            "不得通过公网回传任何档案数据。",
            BODY,
        ),
        Spacer(1, 6),
        Paragraph(
            "3.2 信创适配：服务器采用鲲鹏 920 平台，操作系统为银河麒麟 V10，"
            "数据库采用达梦 8；投标方须提供同类信创环境下的适配证明。",
            BODY,
        ),
        Spacer(1, 6),
        Paragraph(
            "3.3 识别准确率：常用表证单据的字段级识别准确率不低于 98%；"
            "竣工资料中的手写批注部分，字段级准确率不低于 85%。",
            BODY,
        ),
        Spacer(1, 6),
        Paragraph("3.4 格式支持：需支持 PDF、OFD、JPG、TIFF、PNG 等常见格式，并支持简体与繁体汉字识别。", BODY),
        Spacer(1, 8),
        Paragraph("4. 规模与性能要求", H2),
        table(
            [
                ["指标", "要求"],
                ["日均处理量", "不低于 30 万页"],
                ["峰值处理能力", "不少于 5 万页/日"],
                ["单页平均处理时延", "不超过 3 秒"],
                ["并发用户数", "不少于 200"],
            ],
            [40 * mm, 90 * mm],
        ),
        PageBreak(),
        Paragraph("5. 数据安全要求", H2),
        Paragraph(
            "5.1 所有档案数据不得出馆内网络；5.2 项目服务期内，投标方不得留存任何档案数据副本，"
            "亦不得将档案数据用于任何形式的模型训练。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("6. 实施与工期", H2),
        Paragraph(
            "6.1 项目总工期 6 个月，自合同签订之日起计算；6.2 其中前端检索功能须在 3 个月内上线；"
            "6.3 实施期间须派驻现场工程师不少于 2 人。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("7. 服务与验收", H2),
        Paragraph(
            "7.1 提供不少于 3 年免费维保；7.2 验收前须完成不少于 20 万页的试运行；"
            "7.3 培训不少于 4 场，覆盖馆内业务人员与运维人员。",
            BODY,
        ),
        PageBreak(),
        Paragraph("8. 特殊载体档案处理要求", H2),
        Paragraph(
            "8.1 大幅面工程图纸：馆藏含大量 A0、A1 幅面工程图纸，须支持原尺寸扫描与原尺寸解析，"
            "不得通过多次拼接降级处理，拼接缝处不得丢失标注信息。",
            BODY,
        ),
        Spacer(1, 6),
        Paragraph(
            "8.2 无边框手写台账：早期台账无表格边框，须能自动识别行列关系并结构化输出。",
            BODY,
        ),
        Spacer(1, 6),
        Paragraph(
            "8.3 多页 OFD 文件：须支持多页 OFD 自动拆页与逐页著录。",
            BODY,
        ),
        Spacer(1, 6),
        Paragraph(
            "8.4 繁体褪色历史档案：民国时期档案字迹褪色、繁体书写，须保证可读性与可检索性。",
            BODY,
        ),
        Spacer(1, 10),
        Paragraph("9. 附录 A：馆藏档案类型清单", H2),
        table(
            [
                ["序号", "档案类型", "数量级", "说明"],
                ["1", "纸质卷宗", "约 180 万件", "含装订成册的会议记录"],
                ["2", "工程图纸", "约 90 万张", "含 A0、A1 大幅面图纸"],
                ["3", "照片档案", "约 12 万张", "含彩色与黑白照片"],
                ["4", "微缩胶片", "约 3 万卷", "历史胶片，部分需要专用阅读设备"],
                ["5", "电子档案", "约 25 万件", "含 OFD、PDF 与专用格式"],
            ],
            [14 * mm, 34 * mm, 30 * mm, 62 * mm],
        ),
    ]


def supplement_story() -> list:
    """02：与 01 配套的答疑，制造工期口径冲突并补充档案类型。"""
    return [
        Paragraph("XX市城建档案馆 招标答疑与补充通知（第 1 号）", TITLE),
        Spacer(1, 10),
        Paragraph("一、关于实施工期的澄清", H2),
        Paragraph(
            "经研究，原招标需求书第 6.1 条约定的项目总工期由 6 个月调整为 4 个月，"
            "其余工期的阶段划分不变。请各投标人据此调整实施方案与人员投入。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("二、关于特殊载体档案类型的补充说明", H2),
        Paragraph(
            "原需求书未列明特殊载体档案的具体清单，现明确为以下五类：A0/A1 大幅面工程图纸、"
            "无边框手写台账、多页 OFD 文件、繁体褪色历史档案、装订成册的会议记录。"
            "其中装订成册的会议记录须支持不完全拆装订的成册扫描。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("三、关于数据安全的再次明确", H2),
        Paragraph(
            "档案数据不得出馆内网络，不得接入任何公有云服务，也不得用于模型训练；"
            "投标方须在投标文件中就此作出书面承诺。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("四、其他", H2),
        Paragraph(
            "本项目不接受联合体投标；投标截止时间不变；答疑澄清文件与招标文件具有同等效力，"
            "如二者内容不一致，以本答疑文件为准。",
            BODY,
        ),
    ]


def out_of_scope_story() -> list:
    """05：需求集中在能力库明确不支持的点上，用来验"结论不能比证据乐观"。"""
    return [
        Paragraph("XX设计院 图纸档案智能解析需求清单", TITLE),
        Spacer(1, 10),
        Paragraph("一、需求清单", H2),
        table(
            [
                ["序号", "需求", "验收口径"],
                ["1", "A0 大幅面工程图纸原尺寸解析", "不拼接、不降分辨率，标注信息完整"],
                ["2", "无边框手写台账识别", "自动补全行列关系，准确率不低于 90%"],
                ["3", "多页 OFD 文件自动拆页与逐页著录", "拆页准确率 100%"],
                ["4", "繁体褪色历史档案识别", "可读可检索"],
                ["5", "日均 50 万页吞吐", "峰值不低于 8 万页/日"],
            ],
            [14 * mm, 66 * mm, 60 * mm],
        ),
        Spacer(1, 10),
        Paragraph("二、说明", H2),
        Paragraph(
            "以上五项为本项目必须全部满足的硬性要求，不接受分阶段实现或人工替代方案。"
            "投标方须在方案中逐条说明实现方式与验收证据。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("三、其他要求", H2),
        Paragraph("系统须提供开放接口，支持后续与院内其他系统对接。", BODY),
    ]


EMAIL_TEXT = """发件人：李工（XX设计院 信息中心）
收件人：张岚（星云科技 售前）
主题：关于图纸档案项目的一些事

张岚你好，

上次交流以后我们内部碰了一下，有几个事跟你说一声：

1. 接口联调时间要提前：原计划 9 月 30 日，现在改到 9 月 15 日前完成，
   因为院里的季度检查要用到检索功能。
2. 领导提了个想法，最好能在手机上看档案目录和缩略图，能不能做你们评估一下，
   不着急，但这个方向要有。
3. 另外档案室的现场条件我拍了照片，稍后发你，主要是扫描工位和电路的问题。

上周那家川菜馆味道不错，下次你过来我们再去。

李工
"""


def scanned_pdf(path: Path) -> None:
    """04：图片型 PDF，没有文字层 —— 考"读不出来要明说"，不能静默产出空内容。"""
    lines = [
        "档案室现场条件补充说明",
        "",
        "一、场地与工位",
        "现有可用工位 12 个，位于三楼东侧库房外间，单工位面积约 2.4 平方米。",
        "其中 4 个工位已完成网络布线，其余工位需在本项目内补布线。",
        "",
        "二、电力条件",
        "单工位提供 220V/10A 电源，合计容量不超过 20 千瓦。",
        "扫描设备集中使用时段为上午 9:00 至 11:30。",
        "",
        "三、环境要求",
        "库房相对湿度控制在 45% 至 60%，温度 18 至 24 摄氏度。",
        "大幅面图纸需在恒湿区域完成扫描，不得搬运至普通办公区。",
        "",
        "四、现场配合",
        "档案室可安排 3 名人员配合清点与归档，配合时间为每周二、周四全天。",
        "",
        "（本说明为扫描件，原件由档案室留存）",
    ]
    font_path = "C:/Windows/Fonts/msyh.ttc"
    font = ImageFont.truetype(font_path, 34)
    title_font = ImageFont.truetype(font_path, 42)

    page = Image.new("RGB", (1240, 1754), "white")  # A4 @150dpi
    draw = ImageDraw.Draw(page)
    y = 140
    for index, line in enumerate(lines):
        if not line:
            y += 26
            continue
        draw.text((120, y), line, fill=(28, 28, 28), font=title_font if index == 0 else font)
        y += 58
    # 制造一点扫描件的观感：轻微倾斜的页边线
    draw.line((120, 120, 1120, 126), fill=(180, 180, 180), width=2)
    image_path = OUT_DIR / "_scan_page.png"
    page.save(image_path)

    doc = pdf_canvas.Canvas(str(path), pagesize=A4)
    doc.drawImage(str(image_path), 0, 0, width=A4[0], height=A4[1])
    doc.showPage()
    doc.save()
    image_path.unlink()
    print(f"generated: {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


def broken_pdf(path: Path) -> None:
    """06：故意损坏的文件 —— 必须明确失败，不能"显示已读完但内容是空的"。"""
    path.write_bytes(
        b"%PDF-1.7\n"
        b"% \xe8\xbf\x99\xe6\x98\xaf\xe6\x95\x85\xe6\x84\x8f\xe6\x8d\x9f\xe5\x9d\x8f\xe7\x9a\x84\xe6\xb5\x8b\xe8\xaf\x95\xe6\x96\x87\xe4\xbb\xb6\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"%%EOF"
    )
    print(f"generated: {path.relative_to(ROOT)} ({path.stat().st_size} bytes，故意不完整)")


def write_expected() -> None:
    payload = {
        "version": "2026-09-16.1",
        "note": (
            "回归题库的答题卡：材料固定，所以抽全率与越界率才可复现。"
            "must_extract 的命中范围是「需求 + 项目要点」——关键信息落成哪一类都算读出来了。"
        ),
        "materials": [
            {
                "file": "01-招标需求书.pdf",
                "project_name": "效果评测 · 长材料（招标需求书）",
                "expect_parse": "parsed",
                "min_requirements": 6,
                "max_requirements": 40,
                "must_extract": ["工期", "准确率", "内网", "信创", "图纸", "日均"],
                "must_not_full_support": ["大幅面", "图纸"],
                "notes": "关键约束在第 8 节（后段）：考抽全率与「埋得深」；大幅面图纸必须命中能力缺口",
            },
            {
                "file": "02-答疑与补充通知.pdf",
                "project_name": "效果评测 · 答疑（口径冲突）",
                "expect_parse": "parsed",
                "min_requirements": 2,
                "max_requirements": 30,
                "must_extract": ["工期", "装订"],
                "must_not_full_support": [],
                "notes": "与 01 配合：工期 6 个月 → 4 个月，考口径冲突能不能被抓到并转成待确认",
            },
            {
                "file": "03-客户往来邮件.txt",
                "project_name": "效果评测 · 邮件（无页码材料）",
                "expect_parse": "parsed",
                "min_requirements": 1,
                "max_requirements": 8,
                "must_extract": ["联调"],
                "must_not_full_support": [],
                "notes": "寒暄里夹一条真正的变更；不能把「川菜馆」这类内容抽成需求（用条数上限兜住噪音）",
            },
            {
                "file": "04-扫描件.pdf",
                "project_name": "效果评测 · 扫描件（无文字层）",
                "expect_parse": "parsed|failed",
                "min_requirements": 0,
                "max_requirements": 30,
                "must_extract": [],
                "must_not_full_support": [],
                "notes": "OCR 读出来算过，读不出来也必须明确失败并给成因 —— 不许「已读完但内容为空」",
            },
            {
                "file": "05-超范围需求清单.pdf",
                "project_name": "效果评测 · 超范围需求（不能比证据乐观）",
                "expect_parse": "parsed",
                "min_requirements": 3,
                "max_requirements": 20,
                "must_extract": ["图纸", "OFD"],
                "must_not_full_support": ["图纸", "台账", "OFD", "繁体", "50 万", "50万"],
                "notes": "五条硬要求全部超出或接近能力边界：越界率必须为 0（一条都不许判成完全支持）",
            },
            {
                "file": "06-损坏文件.pdf",
                "project_name": "效果评测 · 损坏文件（明确失败）",
                "expect_parse": "failed",
                "min_requirements": 0,
                "max_requirements": 0,
                "must_extract": [],
                "must_not_full_support": [],
                "notes": "解析失败必须带成因码前缀，且不允许产出需求",
            },
        ],
    }
    path = OUT_DIR / "expected.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"generated: {path.relative_to(ROOT)}")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    build(OUT_DIR / "01-招标需求书.pdf", rfp_story())
    build(OUT_DIR / "02-答疑与补充通知.pdf", supplement_story())
    (OUT_DIR / "03-客户往来邮件.txt").write_text(EMAIL_TEXT, encoding="utf-8")
    print(f"generated: scripts/testset/03-客户往来邮件.txt")
    scanned_pdf(OUT_DIR / "04-扫描件.pdf")
    build(OUT_DIR / "05-超范围需求清单.pdf", out_of_scope_story())
    broken_pdf(OUT_DIR / "06-损坏文件.pdf")
    write_expected()
    print("\n题库已就绪。跑效果评测：")
    print("  $env:FITWISE_SANDBOX_PORT=\"8023\"; .venv\\Scripts\\python.exe scripts\\regression_check.py --testset")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
