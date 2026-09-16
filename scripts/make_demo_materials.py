"""生成演示用的两份客户材料（虚构客户，纯合成数据）。

用法：
    .venv\\Scripts\\python.exe scripts\\make_demo_materials.py
（依赖 reportlab：.venv\\Scripts\\python.exe -m pip install reportlab）

产物（demo/ 目录，演示时手动上传这两份）：
    demo/1-XX市档案馆数字化平台招标需求书.pdf   → 材料类型 rfp（主文件）
    demo/2-XX市档案馆招标答疑与补充通知.pdf     → 材料类型 qa（改工期、补档案类型清单）

两份材料是配套设计的：
  - 主文件把工期写成 4 个月，答疑改成 3 个月 —— 制造"同一件事两份材料口径不一致"，
    项目要点会按原文各记一条，人一眼能看到冲突；
  - 主文件只写"5 类特殊档案"，答疑才给出清单 —— 演示"新信息让待确认项变明确"；
  - 档案类型里有明确的摩擦点（大幅面图纸、无边框台账、多页 OFD、手写批注），
    用于演示"部分支持 / 待补依据 / 暂不支持"三种结论。

企业内部知识库不在这里 —— 它是 server/seed/knowledge_base.json 预置的（星云科技）。
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
TITLE = ParagraphStyle("cn-title", parent=styles["Title"], fontName="STSong-Light", fontSize=17, leading=25)
H2 = ParagraphStyle("cn-h2", parent=styles["Heading2"], fontName="STSong-Light", fontSize=12.5, leading=19)
BODY = ParagraphStyle("cn-body", parent=styles["BodyText"], fontName="STSong-Light", fontSize=10.5, leading=17)
NOTE = ParagraphStyle("cn-note", parent=BODY, fontSize=9.5, textColor="#555555")

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "demo"


def build(path: Path, story: list) -> None:
    doc = SimpleDocTemplate(
        str(path), pagesize=A4, topMargin=20 * mm, bottomMargin=18 * mm, title=path.stem
    )
    doc.build(story)
    print(f"generated: {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


def rfp_story() -> list:
    return [
        Paragraph("XX市档案馆 档案数字化与智能处理平台建设项目 招标需求书", TITLE),
        Spacer(1, 10),
        Paragraph("1.1 项目背景", H2),
        Paragraph(
            "我馆现有档案约 420 万件（含纸质卷宗、照片、图纸与电子档案），历史档案数字化率不足 40%。"
            "本项目拟建设档案数字化与智能处理平台，实现档案扫描件入库、字段结构化、全文检索与长期保存。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("1.2 建设范围", H2),
        Paragraph(
            "建设范围包括：档案扫描件与电子档案的批量解析、关键字段提取与结构化入库、"
            "档案管理系统对接、检索服务与统计报表。不含实体档案搬运与扫描外包服务。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("1.3 项目周期", H2),
        Paragraph(
            "项目一期需在合同签订后 4 个月内完成上线并通过初步验收，含系统部署、数据接入与试运行。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("2.1 处理规模", H2),
        Paragraph(
            "一期上线后日均处理档案扫描件约 8 万页，业务高峰期集中在每年档案移交季，"
            "峰值处理能力要求不低于 200 QPS。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("2.3 档案类型与预计处理量", H2),
        Table(
            [
                ["档案类型", "占比", "日均处理量（页）", "关键字段数"],
                ["纸质文书档案（扫描件）", "55%", "44,000", "8"],
                ["表格类台账（无边框）", "20%", "16,000", "12"],
                ["历史档案（繁体、纸张泛黄）", "15%", "12,000", "6"],
                ["工程图纸（大幅面）", "10%", "8,000", "4"],
            ],
            colWidths=[62 * mm, 20 * mm, 45 * mm, 30 * mm],
            style=TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("GRID", (0, 0), (-1, -1), 0.5, (0.4, 0.4, 0.4)),
                    ("BACKGROUND", (0, 0), (-1, 0), (0.92, 0.94, 0.97)),
                ]
            ),
        ),
        Spacer(1, 8),
        Paragraph("2.4 特殊档案类型", H2),
        Paragraph(
            "除常规纸质文书档案外，本项目需处理 5 类特殊档案，具体类型清单以答疑澄清文件为准；"
            "投标方需明确各类档案的支持状态，不接受在实施期外补充定制。",
            BODY,
        ),
        PageBreak(),
        Paragraph("3.1 部署要求", H2),
        Paragraph(
            "平台须在我馆机房内网私有化部署，全离线运行，不得向馆外传输任何档案影像与识别结果，"
            "不得使用公有云服务。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("3.2 信创环境适配", H2),
        Paragraph(
            "生产环境要求适配麒麟 V10 操作系统与鲲鹏 920 服务器，数据库采用达梦，"
            "不接受仅提供适配矩阵而未在同类环境验证过的方案。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("4.1 安全合规", H2),
        Paragraph(
            "平台需满足等保三级要求，操作日志与数据访问日志留存不少于 6 个月，"
            "并支持对接我馆现有日志审计平台（SIEM）。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("4.2 数据责任", H2),
        Paragraph("档案数据属我馆所有，中标方不得留存、复制或用于模型训练。", BODY),
        PageBreak(),
        Paragraph("5.1 格式支持", H2),
        Paragraph(
            "需支持 PDF、OFD、扫描影像（JPG/TIFF）以及 Excel 台账的解析；"
            "OFD 卷宗常见为多页文件，需直接支持多页 OFD 的解析与字段提取。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("5.2 手写与印章场景", H2),
        Paragraph(
            "部分历史档案含手写批注、毛笔字与盖章遮挡，需在方案中说明该类档案的识别能力与准确率水平。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("5.3 表格类台账", H2),
        Paragraph(
            "台账多为无边框、多级表头形式，需支持单元格级结构化提取；"
            "无法自动处理的档案需给出人工复核流程。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("5.4 历史档案", H2),
        Paragraph("历史档案以繁体字为主，纸张泛黄、字迹存在褪色，需保持可检索的识别质量。", BODY),
        Spacer(1, 8),
        Paragraph("6.1 接口与集成", H2),
        Paragraph(
            "需提供标准 REST 接口与 SDK，与我馆现有档案管理系统对接；"
            "现有系统由第三方厂商提供，接口文档为 2023 年 V2 版本，认证方式与限流策略未包含在内。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("7.1 准确率与验收", H2),
        Paragraph(
            "关键字段识别准确率不低于 99%，验收以我馆抽样测试结果为准，抽检样本与字段口径由双方在启动阶段确认。",
            BODY,
        ),
        Spacer(1, 10),
        Paragraph("说明：本文件为演示用合成材料，客户名称、规模数据与要求均为虚构。", NOTE),
    ]


def qa_story() -> list:
    return [
        Paragraph("XX市档案馆 档案数字化与智能处理平台建设项目 答疑与补充通知", TITLE),
        Spacer(1, 10),
        Paragraph("一、关于项目周期（对招标需求书 1.3 的修改）", H2),
        Paragraph(
            "经馆内研究并报上级主管部门同意，项目一期上线时间由原“合同签订后 4 个月”调整为"
            "“合同签订后 3 个月内完成上线并投入试运行”，请投标方按调整后的工期响应。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("二、关于特殊档案类型清单（对 2.4 的补充）", H2),
        Paragraph("招标需求书 2.4 提到的 5 类特殊档案，明确为以下类型：", BODY),
        Table(
            [
                ["序号", "特殊档案类型", "说明"],
                ["1", "多页 OFD 卷宗", "单份卷宗 20-200 页，含目录与正文"],
                ["2", "无边框多级表头台账", "单元格无框线，表头 2-3 级"],
                ["3", "手写批注与盖章遮挡件", "含钢笔批注、印章覆盖正文"],
                ["4", "繁体字历史档案", "纸张泛黄、字迹褪色"],
                ["5", "大幅面工程图纸", "A0/A1 拼接扫描，单页尺寸超过 1 米"],
            ],
            colWidths=[14 * mm, 52 * mm, 92 * mm],
            style=TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("GRID", (0, 0), (-1, -1), 0.5, (0.4, 0.4, 0.4)),
                    ("BACKGROUND", (0, 0), (-1, 0), (0.92, 0.94, 0.97)),
                ]
            ),
        ),
        Spacer(1, 8),
        PageBreak(),
        Paragraph("三、关于部署方式的补充要求（对 3.1 的补充）", H2),
        Paragraph(
            "明确要求全部处理环节在馆内内网完成，不接受任何形式的公有云推理服务；"
            "如投标方案包含外部模型服务，需在响应文件中单独说明数据处理方式。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("四、关于接口对接的澄清（对 6.1 的补充）", H2),
        Paragraph(
            "现有档案管理系统为第三方厂商产品，接口文档仍为 2023 年 V2 版本；"
            "认证方式与限流策略需待我馆安全部门与厂商确认后另行提供，暂无法在投标阶段给出。",
            BODY,
        ),
        Spacer(1, 8),
        Paragraph("五、关于验收与抽样", H2),
        Paragraph(
            "验收按档案类型分层抽样，每类抽取不少于 200 页；关键字段准确率以抽样结果为准，"
            "未达标的档案类型需整改后复验。",
            BODY,
        ),
        Spacer(1, 10),
        Paragraph("说明：本文件为演示用合成材料，内容均为虚构。", NOTE),
    ]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    build(OUT_DIR / "1-XX市档案馆数字化平台招标需求书.pdf", rfp_story())
    build(OUT_DIR / "2-XX市档案馆招标答疑与补充通知.pdf", qa_story())
    print(f"\n演示时手动上传这两份：{OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
