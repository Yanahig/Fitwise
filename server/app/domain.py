"""领域常量：项目阶段、匹配状态、需求标签词表（前后端共用语义）。"""

from __future__ import annotations

# 项目工作台的 7 步导航（概览 + 6 个执行阶段）
# 面向售前同学，用业务语言描述每个阶段，不出现技术实现词
PROJECT_STAGES: list[dict[str, str | int]] = [
    {"id": "overview", "order": 0, "name": "概览", "description": "项目状态、风险与下一步"},
    {"id": "materials", "order": 1, "name": "客户材料", "description": "上传客户材料，系统自动读完并标好页码"},
    {"id": "requirements", "order": 2, "name": "需求确认", "description": "系统整理需求，你逐条确认"},
    {"id": "matching", "order": 3, "name": "能力匹配", "description": "判断每条需求能不能做，附判断依据"},
    {"id": "solution", "order": 4, "name": "方案与路径", "description": "推荐能力组合与推进路径"},
    {"id": "actions", "order": 5, "name": "行动与承诺", "description": "待办分派与对客承诺登记"},
    {"id": "review", "order": 6, "name": "项目复盘", "description": "记录真实结果与可复用经验"},
]

MATCH_STATUSES: dict[str, dict[str, str]] = {
    "full": {"label": "完全支持", "short": "完全支持", "description": "企业已有正式发布能力，证据充分，可直接纳入方案。"},
    "partial": {"label": "部分支持", "short": "部分支持", "description": "有相关能力，但存在适用范围、资源或精度前提，需确认后使用。"},
    "none": {"label": "暂不支持", "short": "暂不支持", "description": "当前没有标准能力，需要定制开发或替代方案。"},
    "unknown": {"label": "信息不足，待补依据", "short": "待补依据", "description": "知识库或客户材料中缺少关键证据，先不给结论 —— 补齐依据后再判。"},
}

REQUIREMENT_STATUSES = {
    "draft": "待确认",
    "confirmed": "已确认",
    "dropped": "已废弃",
}

MATERIAL_TYPES = {
    "rfp": "招标 / 需求文件",
    "minutes": "会议纪要",
    "qa": "答疑纪要",
    "email": "往来邮件",
    "other": "其他材料",
}

# 客户名 / 项目名允许留空，先建一个占位项目再让 AI 从材料里识别。
# 占位名是"还没定"的意思：识别到真名就替换，人工填的名字不覆盖。
PENDING_CUSTOMER_NAME = "待识别客户"
PENDING_PROJECT_NAME = "待识别项目"


def is_pending_name(value: str | None) -> bool:
    text = (value or "").strip()
    return not text or text in {PENDING_CUSTOMER_NAME, PENDING_PROJECT_NAME}


# 需求文本 → 能力标签（与前端 tagging.ts 保持一致的中文关键词表）
TAG_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("on-premise", ("私有化", "本地部署", "内网部署", "行内机房", "本地化部署", "on-premise")),
    ("offline", ("离线", "断网", "物理隔离", "不出域", "内网运行")),
    ("deployment", ("部署", "实施环境", "机房", "服务器")),
    ("ocr", ("ocr", "文字识别", "识别引擎", "识别能力", "票据识别")),
    ("multi-language", ("多语言", "多语种", "语言混排", "语种")),
    ("zh", ("中文", "简体", "繁体", "简中")),
    ("en", ("英文", "英语")),
    ("ja", ("日文", "日语")),
    ("korean", ("韩语", "韩文", "korean")),
    ("ticket", ("票据", "发票", "单据", "凭证")),
    (
        "special-ticket",
        ("特殊票据", "财政电子票据", "海关缴款书", "非标", "银行回单", "回单", "缴款书"),
    ),
    ("standard-ticket", ("增值税", "行程单", "火车票", "定额发票", "标准票据")),
    ("structured-fields", ("结构化", "字段", "要素提取")),
    ("document-parse", ("文档解析", "档案", "版面", "解析", "数字化")),
    ("pdf", ("pdf",)),
    ("office", ("word", "excel", "office", "docx", "xlsx", "ppt", "pptx")),
    ("scanned", ("扫描件", "影像", "图片", "ofd")),
    ("table", ("表格", "报表", "台账")),
    ("table-complex", ("嵌套表格", "多级表头", "复杂表格", "无边框表格")),
    ("ofd-multi", ("ofd",)),
    # 窄标签：只用来钓"大幅面图纸"这一类需求，别用 archive / scanned 这种泛标签 ——
    # 约束信号挂上泛标签就等于"整个领域都做不了"，会把所有需求一起拉低
    ("large-format", ("大幅面", "工程图纸", "图纸", "蓝图")),
    ("archive", ("档案", "归档", "影像系统")),
    ("api", ("api", "接口", "sdk")),
    ("integration", ("集成", "对接", "打通", "接入现有", "影像平台", "核心系统", "oa")),
    ("image-platform", ("影像平台", "影像系统")),
    ("concurrency", ("并发", "qps", "吞吐")),
    ("concurrency-200", ("200 qps", "200qps", "200 并发", "并发不低于 200")),
    ("accuracy", ("准确率", "精度", "识别率")),
    ("accuracy-99", ("99%", "99％", "99.0", "99 ％")),
    ("handwriting", ("手写", "手写字")),
    ("throughput", ("处理量", "万页", "日均", "吞吐", "页/日", "处理能力")),
    ("throughput-confirmation", ("万页", "日均", "高峰期", "处理量", "吞吐")),
    ("cluster-scale", ("集群", "扩容", "节点")),
    ("xinchuang", ("信创", "国产化", "国产", "麒麟", "统信", "鲲鹏", "海光", "达梦")),
    ("kylin", ("麒麟",)),
    ("kunpeng", ("鲲鹏",)),
    ("domestic-stack", ("达梦", "人大金仓", "国产化环境")),
    ("domestic-gpu", ("昇腾", "国产 gpu", "信创 gpu")),
    ("security", ("安全", "加密", "隔离", "权限")),
    ("data-residency", ("数据不出域", "数据不出行", "不外传", "本地存储")),
    ("audit-log", ("审计", "日志", "留痕", "操作记录")),
    ("log-export", ("日志平台", "siem", "syslog", "kafka")),
    ("compliance", ("合规", "监管", "等保", "测评")),
    ("mlps", ("等保", "等级保护")),
    ("audit", ("审核", "校验", "稽核")),
    ("rule-engine", ("规则", "规则引擎")),
    ("delivery", ("交付", "实施", "上线", "驻场", "服务")),
    ("timeline-4months", ("个月内", "个月", "工期", "上线时间", "项目周期")),
    ("customization", ("定制", "二次开发", "定制化")),
    ("acceptance", ("验收", "评测集", "抽样测试", "测试")),
    ("resource-small", ("最小配置", "资源要求", "节点配置")),
    ("accuracy-sla", ("sla", "可用性", "服务等级")),
]

TAG_LABELS = {
    "on-premise": "私有化部署",
    "offline": "离线运行",
    "deployment": "部署交付",
    "ocr": "OCR 识别",
    "multi-language": "多语言识别",
    "korean": "韩语",
    "ja": "日文",
    "en": "英文",
    "zh": "中文",
    "ticket": "票据识别",
    "special-ticket": "特殊票据",
    "standard-ticket": "标准票据",
    "structured-fields": "字段结构化",
    "document-parse": "文档解析",
    "table": "表格结构化",
    "scanned": "扫描件处理",
    "archive": "档案归档",
    "api": "标准 API",
    "integration": "系统集成",
    "image-platform": "影像平台集成",
    "concurrency": "并发能力",
    "concurrency-200": "200 QPS 并发",
    "accuracy": "识别准确率",
    "accuracy-99": "99% 准确率",
    "throughput": "处理吞吐",
    "throughput-confirmation": "吞吐容量确认",
    "cluster-scale": "集群扩容",
    "xinchuang": "信创适配",
    "kylin": "麒麟操作系统",
    "kunpeng": "鲲鹏服务器",
    "security": "安全能力",
    "data-residency": "数据不出域",
    "audit-log": "审计日志",
    "compliance": "合规能力",
    "mlps": "等保三级",
    "delivery": "交付服务",
    "timeline-4months": "交付周期",
    "customization": "定制开发",
    "acceptance": "验收方式",
}


def infer_tags(text: str) -> list[str]:
    """把需求原文翻译成能力标签（检索条件）。"""
    normalized = (text or "").lower()
    tags: list[str] = []
    for tag, keywords in TAG_RULES:
        if any(keyword.lower() in normalized for keyword in keywords):
            tags.append(tag)
    return tags


def tag_label(tag: str) -> str:
    return TAG_LABELS.get(tag, tag)
