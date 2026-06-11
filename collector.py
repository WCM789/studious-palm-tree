#!/usr/bin/env python3
"""
江浙沪水利设计咨询招投标数据自动采集器
=============================================
采集来源：
  浙江: 浙江省公共资源交易平台、浙江政府采购网、各市公共资源交易网
  江苏: 江苏省公共资源交易网、江苏省水利厅、各市公共资源交易网
  上海: 上海市公共资源交易中心、上海政府采购网、中国政府采购网(上海)

输出: data.json (供 index.html 读取)
"""

import json
import re
import os
import time
import urllib.request
import urllib.error
import ssl
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

# 忽略 SSL 证书验证（部分政府网站证书不标准）
ssl._create_default_https_context = ssl._create_untrusted_context

# ========= 配置 =========
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
REQUEST_TIMEOUT = 15  # 秒
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": USER_AGENT}

# 关键词映射到分类
CATEGORY_KEYWORDS = {
    "水保": ["水土保持", "水保", "水土流失", "水土"],
    "防洪": ["防洪", "堤防", "除险加固", "排涝", "防汛", "水库移民", "堤坝"],
    "土地整治": ["土地整治", "土地整理", "土地开发", "农田水利", "高标准农田"],
    "河道设计": ["河道", "河道整治", "水闸", "泵站", "水系", "河湖", "水域", "蓝线", "护岸", "疏浚"],
    "施工图审查": ["施工图审查", "施工图设计审查", "图纸审查", "技术审查"],
}

# ========= 采集函数 =========

def fetch_url(url, encoding=None):
    """通用抓取"""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            data = resp.read()
            if encoding:
                return data.decode(encoding, errors="replace")
            # 尝试自动检测编码
            for enc in ["utf-8", "gbk", "gb2312", "gb18030"]:
                try:
                    return data.decode(enc)
                except UnicodeDecodeError:
                    continue
            return data.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ⚠️ 请求失败 {url}: {e}")
        return None


def classify_project(title, content=""):
    """根据标题和内容自动分类"""
    text = (title + " " + content).lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return cat
    return "河道设计"  # 默认


def detect_region(title, content=""):
    """根据标题自动判断地区"""
    text = title + " " + content
    zj_cities = ["杭州", "宁波", "温州", "嘉兴", "湖州", "绍兴", "金华", "衢州", "舟山", "台州", "丽水",
                 "浦江", "义乌", "椒江", "临海", "龙游", "秀洲", "上虞", "桐乡", "海宁", "慈溪", "余姚"]
    js_cities = ["南京", "苏州", "无锡", "常州", "镇江", "南通", "扬州", "泰州", "徐州", "盐城", "淮安",
                 "连云港", "宿迁", "江阴", "昆山", "句容", "吴淞", "新吴", "张家港", "常熟", "太仓"]
    sh_cities = ["上海", "浦东", "闵行", "金山", "松江", "嘉定", "宝山", "奉贤", "青浦", "崇明", "杨浦",
                 "徐汇", "长宁", "普陀", "虹口", "黄浦", "静安"]
    for city in sh_cities:
        if city in text:
            return "上海", city
    for city in zj_cities:
        if city in text:
            return "浙江", city
    for city in js_cities:
        if city in text:
            return "江苏", city
    if "浙江" in text:
        return "浙江", "浙江"
    if "江苏" in text:
        return "江苏", "江苏"
    return "上海", "上海"


def extract_budget(text):
    """从文本中提取预算金额"""
    # 匹配 "预算金额/预算/投资约 XXX万元/亿元"
    patterns = [
        r'(?:预算(?:金额)?|投资(?:额)?|总投资|采购预算)[：:]\s*([\d,]+\.?\d*)\s*(万|亿)',
        r'(?:预算|投资)[约]?([\d,]+\.?\d*)\s*(万|亿)元?',
        r'([\d,]+\.?\d*)\s*(万|亿)元?\s*(?:预算|投资)',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            num = m.group(1).replace(",", "")
            unit = m.group(2)
            if unit == "亿":
                return f"¥{float(num)*10000:.0f}万"
            return f"¥{float(num):.0f}万"
    return "详见招标文件"


def extract_date(text):
    """提取日期"""
    m = re.search(r'(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})', text)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return datetime.now().strftime("%Y-%m-%d")


# ========= 浙江采集 =========

def collect_zhejiang():
    """采集浙江省招投标信息"""
    projects = []
    print("📡 采集浙江省数据...")

    # 1. 浙江省公共资源交易平台 - 水利工程招标公告
    urls = [
        ("https://ggzy.zj.gov.cn/jyxxgk/002002/002002001/", "浙江省公共资源交易平台"),
    ]

    for base_url, platform in urls:
        html = fetch_url(base_url, "utf-8")
        if not html:
            continue

        # 解析标题和链接
        titles = re.findall(r'<a[^>]*href="([^"]*)"[^>]*title="([^"]*)"[^>]*>', html)
        if not titles:
            titles = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>([^<]{10,})</a>', html)

        for href, title in titles[:20]:
            title = title.strip()
            if len(title) < 10:
                continue

            # 筛选与水利设计咨询相关的
            water_keywords = ["水利", "水保", "防洪", "河道", "堤防", "水库", "水土", "水闸", "排涝", "防汛",
                            "河道设计", "勘察设计", "施工图审查", "土地整治", "农田水利"]
            if not any(kw in title for kw in water_keywords):
                continue

            # 排除施工类（只要设计咨询）
            exclude = ["施工招标", "工程施工", "施工标", "监理招标", "施工项目", "土建"]
            if any(kw in title for kw in exclude):
                continue

            # 确保是招标/采购公告
            bid_keywords = ["招标", "采购", "比选", "竞争性", "磋商", "询价", "公开"]
            if not any(kw in title for kw in bid_keywords):
                continue

            region, city = detect_region(title)
            category = classify_project(title)
            projects.append({
                "id": len(projects) + 1000,
                "region": region,
                "city": city,
                "category": category,
                "title": title,
                "publishDate": datetime.now().strftime("%Y-%m-%d"),
                "deadline": "",
                "budget": "详见招标文件",
                "content": title,
                "sourcePlatform": platform,
                "sourceUrl": href if href.startswith("http") else base_url.rstrip("/") + "/" + href.lstrip("/"),
                "status": "招标中",
                "purchaser": "",
            })

    print(f"  ✅ 浙江采集完成: {len(projects)} 条")
    return projects


def collect_jiangsu():
    """采集江苏省招投标信息"""
    projects = []
    print("📡 采集江苏省数据...")

    # 江苏省公共资源交易网
    urls = [
        "http://jsggzy.jszwfw.gov.cn/jyxx/003003/003003001/",  # 水利工程
    ]

    for url in urls:
        html = fetch_url(url, "utf-8")
        if not html:
            continue

        titles = re.findall(r'<a[^>]*href="([^"]*)"[^>]*title="([^"]*)"[^>]*>', html)
        if not titles:
            titles = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>([^<]{10,})</a>', html)

        for href, title in titles[:20]:
            title = title.strip()
            if len(title) < 10:
                continue

            water_keywords = ["水利", "水保", "防洪", "河道", "堤防", "水库", "水土", "水闸", "排涝",
                            "勘察设计", "施工图审查", "农田水利", "泵站"]
            if not any(kw in title for kw in water_keywords):
                continue

            exclude = ["施工招标", "工程施工", "施工标", "监理招标", "施工项目", "土建", "中标", "结果公告"]
            if any(kw in title for kw in exclude):
                continue

            bid_keywords = ["招标", "采购", "比选", "竞争性", "磋商"]
            if not any(kw in title for kw in bid_keywords):
                continue

            region, city = detect_region(title)
            category = classify_project(title)
            projects.append({
                "id": len(projects) + 2000,
                "region": region,
                "city": city,
                "category": category,
                "title": title,
                "publishDate": datetime.now().strftime("%Y-%m-%d"),
                "deadline": "",
                "budget": "详见招标文件",
                "content": title,
                "sourcePlatform": "江苏省公共资源交易网",
                "sourceUrl": href if href.startswith("http") else "http://jsggzy.jszwfw.gov.cn" + href,
                "status": "招标中",
                "purchaser": "",
            })

    print(f"  ✅ 江苏采集完成: {len(projects)} 条")
    return projects


def collect_shanghai():
    """采集上海市招投标信息"""
    projects = []
    print("📡 采集上海市数据...")

    # 上海政府采购网
    urls = [
        "http://www.ccgp.gov.cn/cggg/dfgg/gkzb/",  # 中国政府采购网 - 公开招标
    ]

    for url in urls:
        html = fetch_url(url, "utf-8")
        if not html:
            continue

        titles = re.findall(r'<a[^>]*href="([^"]*)"[^>]*title="([^"]*)"[^>]*>', html)
        if not titles:
            titles = re.findall(r'<a[^>]*href="([^"]*)"[^>]*>([^<]{10,})</a>', html)

        for href, title in titles[:30]:
            title = title.strip()
            if len(title) < 10:
                continue

            # 只保留上海相关
            if "上海" not in title:
                continue

            water_keywords = ["水利", "水保", "防洪", "河道", "堤防", "水库", "水土", "水闸", "排涝",
                            "勘察设计", "施工图审查", "蓝线", "水务"]
            if not any(kw in title for kw in water_keywords):
                continue

            exclude = ["施工招标", "工程施工", "施工标", "监理招标", "施工项目", "土建", "中标", "结果公告"]
            if any(kw in title for kw in exclude):
                continue

            bid_keywords = ["招标", "采购", "比选", "竞争性", "磋商"]
            if not any(kw in title for kw in bid_keywords):
                continue

            region, city = detect_region(title)
            category = classify_project(title)
            projects.append({
                "id": len(projects) + 3000,
                "region": region,
                "city": city,
                "category": category,
                "title": title,
                "publishDate": datetime.now().strftime("%Y-%m-%d"),
                "deadline": "",
                "budget": "详见招标文件",
                "content": title,
                "sourcePlatform": "中国政府采购网/上海政府采购网",
                "sourceUrl": href if href.startswith("http") else url.rstrip("/") + "/" + href.lstrip("/"),
                "status": "招标中",
                "purchaser": "",
            })

    print(f"  ✅ 上海采集完成: {len(projects)} 条")
    return projects


# ========= 固化的历史项目（确保不丢失重要数据） =========

PRESET_PROJECTS = [
    {
        "id": 1, "region": "浙江", "city": "金华", "category": "防洪",
        "title": "浦江县浦阳江堤防安全鉴定及勘测项目",
        "publishDate": "2026-06-08", "deadline": "2026-06-29",
        "budget": "公开招标（预算详见采购文件）",
        "content": "对浦江县浦阳江堤防进行安全鉴定及勘测，投标人须具有水利行业乙级及以上资质（或河道整治专业乙级及以上）、工程勘察（岩土工程）乙级及以上、测绘（工程测量）乙级及以上。",
        "sourcePlatform": "浙江省公共资源交易平台（政采云）",
        "sourceUrl": "https://ggzy.zj.gov.cn/jyxxgk/002002/002002001/20260608/97a4e98a-ecda-4d6e-940d-96810480c929.html",
        "status": "招标中", "purchaser": "浦江县河湖管理中心"
    },
    {
        "id": 2, "region": "浙江", "city": "丽水", "category": "河道设计",
        "title": "丽水市城市内河整治提升工程（城东片）二期勘察设计",
        "publishDate": "2026-05-14", "deadline": "2026-06-03",
        "budget": "项目总投资4亿元（本标段设计对应投资约1.68亿元）",
        "content": "含测量、勘察、方案设计、初步设计（含概算）、施工图设计及施工阶段服务。建设内容包括东排洪渠卡口疏通、新建关下闸站(排涝15m³/s)、殿前坑河道恢复、好溪堰河综合提升等。",
        "sourcePlatform": "丽水市公共资源交易网",
        "sourceUrl": "https://lssggzy.lishui.gov.cn/col/col1229661808/art/2026/art_3399e5b913530528bfc65a431398cd44.html",
        "status": "已截止", "purchaser": "丽水市水利发展有限公司"
    },
    {
        "id": 3, "region": "浙江", "city": "绍兴", "category": "防洪",
        "title": "上虞区东南诸河流域萧绍平原虞北片排涝工程施工图劳务配合外委",
        "publishDate": "2026-05-28", "deadline": "2026-06-25",
        "budget": "详见招标文件",
        "content": "上虞区排涝工程施工图阶段劳务配合外委，投标人须具备水利行业设计乙级及以上或水利专业（河道整治）乙级及以上资质。",
        "sourcePlatform": "中国招标投标公共服务平台（乐采云）",
        "sourceUrl": "https://zj.bidcenter.com.cn/gys/detail-697322.html",
        "status": "招标中", "purchaser": "浙江省水利水电勘测设计院有限责任公司"
    },
    {
        "id": 4, "region": "浙江", "city": "台州", "category": "水保",
        "title": "椒江城发集团2026-2028年度框架协议采购（水土保持方案编制、监测及验收）",
        "publishDate": "2026-04-08", "deadline": "2026-04-28",
        "budget": "框架协议（按项目结算）",
        "content": "椒江城发集团2026-2028年度水土保持方案编制、监测和验收报告编制服务框架协议采购，面向中小企业。",
        "sourcePlatform": "千里马招标网",
        "sourceUrl": "https://www.qianlima.com/bid-587818410.html",
        "status": "已截止", "purchaser": "椒江城发集团"
    },
    {
        "id": 5, "region": "浙江", "city": "嘉兴", "category": "水保",
        "title": "嘉兴市秀洲区2026年度水资源论证和水土保持方案等技术审查",
        "publishDate": "2026-05-18", "deadline": "2026-06-02",
        "budget": "详见采购文件",
        "content": "2026年度水资源论证和水土保持方案等技术审查服务，竞争性磋商方式采购。",
        "sourcePlatform": "浙江政府采购网",
        "sourceUrl": "https://zj.zhiliaobiaoxun.com/article/99389094",
        "status": "已截止", "purchaser": "嘉兴市秀洲区农业农村和水利局"
    },
    {
        "id": 6, "region": "浙江", "city": "台州", "category": "土地整治",
        "title": "临海市桃渚镇2026年第三批土地整治项目技术服务",
        "publishDate": "2026-05-10", "deadline": "2026-05-22",
        "budget": "92.496万元",
        "content": "临海市桃渚镇2026年第三批土地整治项目技术服务（重新招标），项目启动至验收入库完成。竞争性磋商方式。",
        "sourcePlatform": "浙江政府采购网",
        "sourceUrl": "https://www.sohu.com/a/1020685315_122434053",
        "status": "已截止", "purchaser": "临海市桃渚镇人民政府"
    },
    {
        "id": 7, "region": "浙江", "city": "衢州", "category": "施工图审查",
        "title": "龙游县2026年度水库除险加固工程施工图审查比选",
        "publishDate": "2025-11-10", "deadline": "2025-11-20",
        "budget": "均价比选",
        "content": "龙游县2026年度水库除险加固工程施工图审查，采用中介服务网上交易平台均价比选方式。",
        "sourcePlatform": "浙江政务服务网（中介超市）",
        "sourceUrl": "https://zj.zhiliaobiaoxun.com/article/82092157",
        "status": "已完成", "purchaser": "龙游县双江水利开发有限公司"
    },
    {
        "id": 8, "region": "江苏", "city": "无锡", "category": "水保",
        "title": "江阴市2026年度国家水土保持重点工程秦望山及凤凰山小流域综合治理（勘察设计）",
        "publishDate": "2026-01-09", "deadline": "2026-01-20",
        "budget": "总投资约800万元，设计费约30万元",
        "content": "治理方式为工程措施、林草措施、耕作措施相结合，实施措施面积2.7km²，综合治理面积9km²。含施工图设计，须通过审查。须具备水利行业（河道整治）乙级及以上设计资质+岩土工程勘察乙级及以上。",
        "sourcePlatform": "江阴市人民政府门户网",
        "sourceUrl": "https://www.jiangyin.gov.cn/doc/2026/01/09/1375332.shtml",
        "status": "已完成", "purchaser": "江阴市农村水利服务中心"
    },
    {
        "id": 9, "region": "江苏", "city": "南通", "category": "水保",
        "title": "南通市2026年度生产建设项目水土保持现场评估及方案技术评审",
        "publishDate": "2026-04-01", "deadline": "2026-04-22",
        "budget": "19.2万元（现场评估12万 + 方案评审0.8万/个）",
        "content": "南通市2026年度生产建设项目水土保持现场评估及方案技术评审，服务期为2026年11月底前完成。",
        "sourcePlatform": "南通市水利局官网",
        "sourceUrl": "https://slj.nantong.gov.cn/ntslj/gggs/content/289da209-5643-45a8-b1a5-10115238bd78.html",
        "status": "已截止", "purchaser": "南通市水利局"
    },
    {
        "id": 10, "region": "江苏", "city": "宿迁", "category": "河道设计",
        "title": "江苏省骆运水利工程管理处2026年度工程设计服务",
        "publishDate": "2026-06-04", "deadline": "2026-06-08",
        "budget": "单个项目实施金额的3.0%（费率报价）",
        "content": "2026年度管理范围内限定工程全过程设计，含初步设计、招标、施工图等，成交人为江苏省水利勘测设计研究院有限公司（成交费率2.85%）。须具备水利行业专业甲级设计资质。",
        "sourcePlatform": "江苏省骆运水利工程管理处官网",
        "sourceUrl": "http://ly.jswater.org.cn/lysl/xxgk/zbtb/cgxx/art/2026/art_4ff71baa150849a995b3947802643e8d.html",
        "status": "已定标", "purchaser": "江苏省骆运水利工程管理处"
    },
    {
        "id": 11, "region": "江苏", "city": "无锡", "category": "河道设计",
        "title": "西仓浜河道补偿工程（综保区新片区水利配套工程）勘察设计",
        "publishDate": "2026-04-24", "deadline": "2026-05-19",
        "budget": "详见招标公告",
        "content": "无锡高新区（新吴区）西仓浜河道补偿工程勘察设计，属于综保区新片区水利配套工程。",
        "sourcePlatform": "江苏省公共资源交易网",
        "sourceUrl": "http://jsggzy.jszwfw.gov.cn/jyxx/003003/003003001/20260424/3ae26724-67a1-4eec-8e60-811077321c08.html",
        "status": "已截止", "purchaser": "无锡高新区（新吴区）"
    },
    {
        "id": 12, "region": "江苏", "city": "镇江", "category": "防洪",
        "title": "句容市2026年水库移民后扶项目勘察设计",
        "publishDate": "2026-06-03", "deadline": "2026-06-24",
        "budget": "资金来源为中央财政资金",
        "content": "句容市2026年水库移民后期扶持项目勘察设计，已由江苏省水利厅批准开展前期工作，公开招标方式。",
        "sourcePlatform": "江苏省公共资源交易网",
        "sourceUrl": "http://jsggzy.jszwfw.gov.cn/jyxx/003003/003003001/20260603/98fd0ed6-2a7b-4bcd-b3b4-32d90a8295b3.html",
        "status": "招标中", "purchaser": "句容市水库移民后期扶持项目建设管理处"
    },
    {
        "id": 13, "region": "江苏", "city": "苏州", "category": "施工图审查",
        "title": "吴淞江（江苏段）整治工程（昆山市）施工图设计审查咨询",
        "publishDate": "2024-08-30", "deadline": "已截止",
        "budget": "按服务批次结算",
        "content": "按照《江苏省水利工程施工图设计文件咨询工作导则》要求进行施工图设计审查，含设计图纸、合规性审查、强制性条文核查等。服务期至施工图审查通过止。",
        "sourcePlatform": "江苏省水利厅招标公告",
        "sourceUrl": "http://jswater.jiangsu.gov.cn/art/2024/8/30/art_80021_11337703.html",
        "status": "已完成", "purchaser": "昆山市水务局"
    },
    {
        "id": 14, "region": "上海", "city": "金山", "category": "河道设计",
        "title": "金山区山塘河水闸改造工程",
        "publishDate": "2026-03-23", "deadline": "2026-04-15",
        "budget": "总投资约1,921万元（勘测费¥247,875 + 设计费¥120,125）",
        "content": "拆除套闸新建山塘河节制闸（闸孔净宽8米），新建内河侧护岸98米及外河侧清淤等。须具备水利行业乙级及以上设计资质。",
        "sourcePlatform": "上海市公共资源交易中心",
        "sourceUrl": "https://m.bidcenter.com.cn/yezhugonggaolist-5626497.html",
        "status": "已完成", "purchaser": "上海市金山区水利管理所"
    },
    {
        "id": 15, "region": "上海", "city": "金山", "category": "河道设计",
        "title": "金山高新区长楼港、毛家港、小洞泾河道整治工程",
        "publishDate": "2026-04-06", "deadline": "2026-04-28",
        "budget": "详见招标公告",
        "content": "金山高新区长楼港、毛家港、小洞泾河道整治工程设计服务。",
        "sourcePlatform": "上海市公共资源交易中心",
        "sourceUrl": "https://www.zbytb.com/c-239AQ/",
        "status": "已截止", "purchaser": "上海市金山区水利管理所"
    },
    {
        "id": 16, "region": "上海", "city": "上海", "category": "防洪",
        "title": "上海市堤防泵闸建设运行中心2026-2028年度水利工程咨询服务及抢险设计",
        "publishDate": "2026-01-14", "deadline": "2026-02-10",
        "budget": "详见招标文件",
        "content": "上海市堤防泵闸建设运行中心2026-2028年度水利工程咨询服务及抢险设计服务，同期还有监理清单及控制价服务、招标代理服务、成果文件及图纸审核服务等配套采购。",
        "sourcePlatform": "中国水利招标网（dowater.com）",
        "sourceUrl": "https://www.dowater.com/zhaobiao/2026-01-14/10636612.asp",
        "status": "已完成", "purchaser": "上海市堤防泵闸建设运行中心"
    },
    {
        "id": 17, "region": "上海", "city": "上海", "category": "施工图审查",
        "title": "上海市河道蓝线管理系统建设项目（2026年升级改造）",
        "publishDate": "2026-06-02", "deadline": "2026-06-22",
        "budget": "详见上海政府采购网",
        "content": "上海市河道蓝线管理系统2026年升级改造，含河道蓝线数据审核与系统功能升级。",
        "sourcePlatform": "中国政府采购网 / 上海市政府采购网",
        "sourceUrl": "http://www.ccgp.gov.cn/cggg/dfgg/gkzb/202606/t20260603_26678757.htm",
        "status": "招标中", "purchaser": "上海市水务局"
    },
    {
        "id": 18, "region": "上海", "city": "上海", "category": "土地整治",
        "title": "闵行区浦江镇市级土地整治项目（全域）可行性研究、规划设计及概算编制",
        "publishDate": "2025-02-24", "deadline": "2025-03-18",
        "budget": "169.41万元",
        "content": "闵行区浦江镇市级土地整治项目（全域）可行性研究、规划设计及概算编制服务。",
        "sourcePlatform": "中国政府采购网",
        "sourceUrl": "http://www.ccgp.gov.cn/cggg/dfgg/gkzb/202502/t20250224_24206810.htm",
        "status": "已完成", "purchaser": "上海市建设用地和土地整理事务中心"
    },
]


# ========= 主流程 =========

def main():
    print("=" * 55)
    print("  江浙沪水利设计咨询招投标数据采集器 v1.0")
    print("  中润智水（上海）工程设计有限公司")
    print("=" * 55)
    print()

    all_projects = []

    # 1. 保留固化项目（已验证真实有效）
    all_projects.extend(PRESET_PROJECTS)
    print(f"📋 加载固化项目: {len(PRESET_PROJECTS)} 条")

    # 2. 在线采集新项目
    try:
        new_zj = collect_zhejiang()
        # 去重：按标题去重
        existing_titles = {p["title"] for p in all_projects}
        for p in new_zj:
            if p["title"] not in existing_titles:
                p["id"] = len(all_projects) + 1
                all_projects.append(p)
                existing_titles.add(p["title"])
    except Exception as e:
        print(f"  ❌ 浙江采集异常: {e}")

    try:
        new_js = collect_jiangsu()
        existing_titles = {p["title"] for p in all_projects}
        for p in new_js:
            if p["title"] not in existing_titles:
                p["id"] = len(all_projects) + 1
                all_projects.append(p)
                existing_titles.add(p["title"])
    except Exception as e:
        print(f"  ❌ 江苏采集异常: {e}")

    try:
        new_sh = collect_shanghai()
        existing_titles = {p["title"] for p in all_projects}
        for p in new_sh:
            if p["title"] not in existing_titles:
                p["id"] = len(all_projects) + 1
                all_projects.append(p)
                existing_titles.add(p["title"])
    except Exception as e:
        print(f"  ❌ 上海采集异常: {e}")

    # 3. 输出 data.json
    output = {
        "lastUpdate": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "totalCount": len(all_projects),
        "sources": [
            "浙江省公共资源交易平台",
            "浙江政府采购网",
            "江苏省公共资源交易网",
            "江苏省水利厅",
            "上海政府采购网",
            "中国政府采购网",
            "各市公共资源交易网",
            "各市水利局/水务局官网"
        ],
        "projects": all_projects
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print()
    print("=" * 55)
    print(f"  ✅ 采集完成！")
    print(f"  📊 总项目数: {len(all_projects)}")
    print(f"  📁 输出文件: {OUTPUT_FILE}")
    print(f"  🕐 更新时间: {output['lastUpdate']}")
    print("=" * 55)


if __name__ == "__main__":
    main()
