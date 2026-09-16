"""生成一份 3 页的中文测试 RFP，用于验证 TextIn 解析链路的页码与表格识别。

用法：
    .venv\\Scripts\\python.exe scripts/make_test_rfp.py

产物：scripts/test-rfp.pdf（纯合成数据，可安全上传到解析服务做联调）
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))

styles = getSampleStyleSheet()
title = ParagraphStyle("cn-title", parent=styles["Title"], fontName="STSong-Light", fontSize=18, leading=26)
h2 = ParagraphStyle("cn-h2", parent=styles["Heading2"], fontName="STSong-Light", fontSize=13, leading=20)
body = ParagraphStyle("cn-body", parent=styles["BodyText"], fontName="STSong-Light", fontSize=10.5, leading=17)

out = Path(__file__).resolve().parent / "test-rfp.pdf"
doc = SimpleDocTemplate(str(out), pagesize=A4, topMargin=20 * mm, bottomMargin=18 * mm)

story = [
    Paragraph("XX城市商业银行 智能票据与档案处理平台 招标需求书（RFP）", title),
    Spacer(1, 10),
    Paragraph("1.4 项目周期", h2),
    Paragraph("项目一期需在合同签订后 4 个月内完成上线并通过初验。", body),
    Spacer(1, 8),
    Paragraph("2.3 业务规模", h2),
    Paragraph("一期上线后日均处理票据与档案约 50 万页，业务高峰期集中在每月末 3 个工作日。", body),
    Spacer(1, 8),
    Paragraph("4.2 部署要求", h2),
    Paragraph(
        "投标方案须支持行内私有化部署，系统运行期间不得向行外传输任何影像与识别结果数据。"
        "生产环境要求适配麒麟 V10 操作系统与鲲鹏 920 服务器，数据库采用达梦。",
        body,
    ),
    Spacer(1, 8),
    Paragraph("4.5 安全合规", h2),
    Paragraph(
        "系统需满足等保三级要求，操作与数据访问日志留存不少于 6 个月，并支持对接行内日志平台。",
        body,
    ),
    PageBreak(),
    Paragraph("5.1 识别能力要求", h2),
    Paragraph(
        "识别引擎需支持简体中文、英文、日文、韩文四种语言的票据与档案识别，并支持同一文档内语言混排识别。",
        body,
    ),
    Spacer(1, 8),
    Paragraph("5.3 票据类型", h2),
    Paragraph(
        "需覆盖财政电子票据、海关缴款书、银行回单等 5 类特殊票据；要求以标准产品能力实现，"
        "不接受项目实施期外的额外定制。",
        body,
    ),
    Spacer(1, 8),
    Paragraph("5.5 准确率要求", h2),
    Paragraph("关键字段识别准确率不低于 99%，验收以甲方抽样测试结果为准，抽检样本由双方确认。", body),
    Spacer(1, 10),
    Paragraph("票据类型与预计处理量", h2),
    Table(
        [
            ["票据类型", "日均处理量（页）", "关键字段数"],
            ["增值税发票", "180,000", "12"],
            ["财政电子票据", "60,000", "9"],
            ["海关缴款书", "20,000", "8"],
            ["银行回单", "240,000", "6"],
        ],
        colWidths=[70 * mm, 50 * mm, 40 * mm],
        style=TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("GRID", (0, 0), (-1, -1), 0.5, (0.4, 0.4, 0.4)),
                ("BACKGROUND", (0, 0), (-1, 0), (0.92, 0.94, 0.97)),
            ]
        ),
    ),
    PageBreak(),
    Paragraph("6.1 接口要求", h2),
    Paragraph(
        "需提供标准 REST 接口与 SDK，与现有影像平台对接，峰值并发不低于 200 QPS，"
        "支持批量异步处理与结果回调。",
        body,
    ),
    Spacer(1, 8),
    Paragraph("6.4 基础环境", h2),
    Paragraph("生产环境要求适配麒麟 V10 操作系统与鲲鹏 920 服务器，数据库采用达梦。", body),
    Spacer(1, 8),
    Paragraph("7.2 现有影像平台对接（答疑纪要）", h2),
    Paragraph(
        "现有影像平台由第三方厂商提供，对接方式待确认；本次提供的接口清单为 2023 年 V2 版本，"
        "认证方式与限流策略未包含在内。",
        body,
    ),
]

doc.build(story)
print(f"generated: {out} ({out.stat().st_size} bytes)")
