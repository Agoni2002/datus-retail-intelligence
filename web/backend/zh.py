"""Simplified Chinese presentation strings for the public Superset embeds."""

import html
import json
import re

DASHBOARD_TITLES = {
    "retail-executive": "电商经营总览",
    "retail-category": "商品与类别分析",
    "retail-seller": "卖家表现分析",
    "retail-fulfillment": "交付与履约分析",
    "retail-customer": "客户与评价分析",
    "retail-quality": "数据质量与治理",
}
NOTES = {
    "retail-executive": "概览指标按下单月份统计。类别和州筛选器仅作用于相关图表。商品交易额不含运费。",
    "retail-category": "一笔订单可能计入多个类别。贡献率以所选类别的商品交易额为分母。可选择类别以查看其月度趋势。",
    "retail-seller": "每笔订单在每位参与卖家的统计中计入一次。多卖家订单可归属多个卖家；交付结果按整笔订单归入每位参与卖家。",
    "retail-fulfillment": "合格交付须满足仓库的日期和时序校验。时间戳缺失或无效的已交付订单单独统计。逾期天数只统计合格的逾期订单。",
    "retail-customer": "每笔已交付订单采用最新评价。购买频次与复购按客户和月份统计。地区客户数按州和月份去重，同一客户可能计入多个州。",
    "retail-quality": "质量检查和发布信息来自已验证的快照，覆盖范围图表实时查询该快照。",
}
LABELS = {
    "Delivered GMV (BRL)": "已交付商品交易额（BRL）",
    "Delivered Orders": "已交付订单数",
    "Average Order Value (BRL)": "平均客单价（BRL）",
    "All Orders": "全部订单",
    "Cancellation Rate": "订单取消率",
    "On-time Delivery Rate": "准时交付率",
    "Average Late Delivery Days": "平均延迟交付天数",
    "Freight Charges (BRL)": "运费（BRL）",
    "Average Review Score": "平均评价分",
    "Reviewed Delivered Orders": "有评价的已交付订单数",
    "Monthly Same-Month Repeat Customer Share": "月度同月复购客户占比",
    "Category GMV (BRL)": "类别交易额（BRL）",
    "Delivered Category Orders": "类别已交付订单数",
    "Delivered Item Lines": "已交付商品明细数",
    "Seller Order Participations": "卖家参与订单数",
    "Seller Participation Cancellation Rate": "卖家参与订单取消率",
    "Eligible Delivered Orders": "符合统计条件的已交付订单",
    "Late Delivered Orders": "逾期交付订单",
    "Excluded Delivered Orders": "排除的已交付订单",
    "Average Delivery Time (Days)": "平均交付用时（天）",
    "Flagged State-Months": "触发预警的州月数",
    "Delivered Customer-Months": "已交付客户月数",
    "State Customer-Months": "按州统计的客户月数",
    "Monthly Delivered GMV · BRL": "月度已交付商品交易额（BRL）",
    "Monthly Delivered Orders": "月度已交付订单量",
    "Monthly Average Order Value · BRL": "月度平均客单价（BRL）",
    "Top 10 Product Categories · BRL": "商品类别前十名（BRL）",
    "Delivered GMV by Customer State · BRL": "按客户所在州统计的已交付交易额（BRL）",
    "State Delivery Performance": "各州交付表现",
    "Category GMV Ranking · BRL": "商品类别交易额排名（BRL）",
    "Category Order Volume": "商品类别订单量",
    "Monthly Category Sales · BRL": "月度类别销售额（BRL）",
    "Category Contribution to Selected GMV": "各类别占所选交易额的比例",
    "Lowest Delivered Category GMV · BRL": "已交付交易额最低的商品类别（BRL）",
    "Category Performance Detail": "类别经营明细",
    "Top Sellers by Delivered GMV · BRL": "按已交付交易额排名的卖家（BRL）",
    "Top Sellers by Order Participation": "按参与订单数排名的卖家",
    "Top Sellers by Delivered Freight · BRL": "按已交付订单运费排名的卖家（BRL）",
    "Seller Delivery Participation": "卖家参与订单的交付表现",
    "Seller Scorecard": "卖家表现明细",
    "Monthly Delivery Denominators": "各月交付统计口径",
    "Monthly Purchase-to-Delivery Time": "月度下单到交付用时",
    "Regional Delivery Performance": "区域交付表现",
    "Delivery Alert Distribution": "交付预警分布",
    "Delivered Basket Distribution · BRL": "已交付订单金额分布（BRL）",
    "Order Frequency per Customer-Month": "每位客户的月度下单频次",
    "Monthly Average Latest Review Score": "月度平均最新评价分",
    "Latest Review Score Distribution": "最新评价分布",
    "Delivered Customer-Months by State": "按州统计的已交付客户月数",
    "Purchase, Delivery and Review Coverage": "下单、交付和评价覆盖情况",
}
FILTERS = {"Purchase date range": "下单日期范围", "Product category": "商品类别",
           "Customer state": "客户所在州", "Seller ID": "卖家 ID"}
CONTROLS = {
    "Filters": "筛选器", "Apply filters": "应用筛选", "Clear all": "清除全部",
    "No filter": "不限", "Select ...": "请选择…", "Search": "搜索",
    "Edit time range": "设置日期范围", "Range type": "日期范围类型",
    "Advanced": "高级", "Custom": "自定义", "Last": "最近", "Previous": "上一时段",
    "Current": "当前时段", "Apply": "应用", "Cancel": "取消", "Actual time range": "实际日期范围",
    "Start (inclusive)": "开始日期（含）", "End (exclusive)": "结束日期（不含）",
    "Loading...": "正在加载…", "No data": "暂无数据", "Data error": "数据加载失败",
    "Select page size": "选择每页行数", "Show": "显示", "entries per page": "条/页",
    "Search %s records": "搜索 %s 条记录", "Show entries per page": "设置每页显示行数",
    "Previous page": "上一页", "Next page": "下一页", "Expand filters": "展开筛选器",
    "Collapse filters": "收起筛选器",
}


def language_pack():
    return {
        "domain": "superset",
        "locale_data": {"superset": {
            "": {"domain": "superset", "lang": "zh", "plural_forms": "nplurals=1; plural=0"},
            **{name: [value] for name, value in CONTROLS.items()},
        }},
    }


def embedded_shell(payload):
    """Select the Chinese pack in the Superset 6 embedded bootstrap."""
    def replace(match):
        bootstrap = json.loads(html.unescape(match[1].decode()))
        bootstrap["common"]["locale"] = "zh"
        return b'data-bootstrap="' + html.escape(json.dumps(bootstrap), quote=True).encode() + b'"'

    return re.sub(rb'data-bootstrap="([^"]*)"', replace, payload, count=1)


def dashboard_payload(document, path, slug, publication):
    result = document["result"]
    if path.rstrip("/").endswith("/charts"):
        for chart in result:
            original = chart["slice_name"]
            chart["slice_name"] = LABELS.get(original, original)
        return
    if path.rstrip("/").endswith("/datasets"):
        for dataset in result:
            dataset["verbose_map"] = {
                key: LABELS.get(label, label) for key, label in dataset.get("verbose_map", {}).items()
            }
        return
    result["dashboard_title"] = DASHBOARD_TITLES[slug]
    position = json.loads(result["position_json"])
    for key, component in position.items():
        if not isinstance(component, dict):
            continue
        metadata = component.get("meta", {})
        if component.get("type") == "HEADER":
            metadata["text"] = DASHBOARD_TITLES[slug]
        elif "sliceName" in metadata:
            metadata["sliceName"] = LABELS.get(metadata["sliceName"], metadata["sliceName"])
        elif key == "MARKDOWN-context":
            metadata["code"] = NOTES[slug] + "\n\n" + publication["quality"]["coverage"]
        elif key.startswith("MARKDOWN-quality-"):
            metadata["code"] = publication["governancePanels"][int(key.rsplit("-", 1)[1])]
    result["position_json"] = json.dumps(position, ensure_ascii=False)
    metadata = json.loads(result["json_metadata"])
    for item in metadata.get("native_filter_configuration", []):
        name = item["name"]
        item["name"] = FILTERS.get(name, name)
        item["description"] = (
            "按下单月份筛选。若需要统计完整月份，请使用月初作为日期边界。"
            if item["filterType"] == "filter_time" else "仅作用于包含该维度的图表。"
        )
    result["json_metadata"] = json.dumps(metadata, ensure_ascii=False)
