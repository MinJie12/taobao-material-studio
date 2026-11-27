# -*- coding: utf-8 -*-
"""1688 商品采集：链接直采、网页文件解析、文件夹导入、压缩包导入。"""
from __future__ import annotations

import io
import json
import re
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from PIL import Image

from . import config, storage

RISK_MARKERS = (
    "_____tmd_____",
    "x5secdata",
    "punish",
    "captcha",
    "滑动验证",
    "请完成验证",
    "安全验证",
    "访问被拒绝",
)

# 只有出现这些商品数据结构，才认为页面可用于采集
PRODUCT_DATA_MARKERS = (
    "offerimglist",
    "offer_details",
    "skuimages",
    "skuprops",
    "offerinfomodel",
    "offerimages",
    "window.context",
)

MAIN_KEYS = ("offerimg", "offerimage", "mainimg", "mainpic", "mainimage", "mainpiclist", "mainimages", "offerimagelist")
DETAIL_KEYS = ("detail", "desc", "description", "detailimage", "descimage")
SKU_KEYS = ("sku", "spec", "color")
VIDEO_KEYS = ("video", "mainvideo", "detailvideo", "videourl")
DETAIL_RESOURCE_KEYS = ("detailurl", "descurl", "descriptionurl", "detailresourceurl")
DETAIL_HOSTS = ("1688.com", "alicdn.com", "tbcdn.cn", "tmall.com", "taobao.com")
IMAGE_EXT_RE = re.compile(r"\.(jpg|jpeg|png|webp|gif|bmp|avif|jfif|tif|tiff)(\?|$)", re.I)
VIDEO_EXT_RE = re.compile(r"\.(mp4|mov|m4v|webm|avi|flv|mkv)(\?|$)", re.I)
# 缩略图变体与站点 UI 图标，不应作为商品素材下载
THUMBNAIL_VARIANT_RE = re.compile(r"\.(?:search|summ|\d{1,3}x\d{1,3})\.(?:jpe?g|png|webp|gif)$", re.I)
TINY_ICON_RE = re.compile(r"-tps-(\d{1,4})-(\d{1,4})\.(?:jpe?g|png|webp|gif)$", re.I)
NOISE_PATH_PARTS = ("/code/npm/", "/rax-pkg/", "/alilog/", "/tfs/")
NOISE_EXTENSIONS = (".js", ".css", ".json", ".html", ".htm")
IMAGE_CDN_HOSTS = ("alicdn.com", "tbcdn.cn", "tmall.com", "taobao.com")


class CollectError(Exception):
    """采集失败，可直接展示给用户。"""


def normalize_url(url: str) -> str:
    url = str(url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if not re.match(r"^https?://", url, re.I):
        if "." in url.split("/")[0]:
            return "https://" + url
    return url


def extract_offer_id(text: str) -> str:
    text = str(text or "")
    for pattern in (
        r"/offer/(\d+)\.html",
        r"offerId[=:](\d+)",
        r"offer_id[=:](\d+)",
        r"offer/(\d+)",
        r"/(\d{8,})\.html",
    ):
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)
    return ""


def detect_risk(html: str) -> bool:
    lowered = str(html or "").lower()
    return any(marker.lower() in lowered for marker in RISK_MARKERS)


def _headers(settings: dict, cookie: str = "", mobile: bool = False) -> dict:
    download = settings.get("download", {})
    user_agent = str(download.get("user_agent", ""))
    if mobile:
        user_agent = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        )
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": str(download.get("referer", "https://detail.1688.com/")),
    }
    cookie = str(cookie or download.get("cookie", "") or "").strip()
    if cookie.lower().startswith("cookie:"):
        cookie = cookie[7:].strip()
    if cookie:
        headers["Cookie"] = cookie
    return headers


def fetch_page(url: str, settings: dict, cookie: str = "", mobile: bool = False) -> str:
    timeout = int(settings.get("download", {}).get("timeout", 30))
    response = requests.get(
        url,
        headers=_headers(settings, cookie, mobile),
        timeout=timeout,
        allow_redirects=True,
    )
    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
    return response.text


def _has_product_data(html: str) -> bool:
    lowered = str(html or "").lower()
    return any(marker in lowered for marker in PRODUCT_DATA_MARKERS)


def fetch_product_html(url: str, settings: dict, cookie: str = "") -> tuple[str, str]:
    url = normalize_url(url)
    if not url:
        raise CollectError("请填写有效的 1688 商品链接")
    offer_id = extract_offer_id(url)
    candidates = [url]
    if offer_id:
        candidates.append(f"https://m.1688.com/offer/{offer_id}.html")
        candidates.append(f"https://detail.1688.com/offer/{offer_id}.html?sk=consign")
    seen = set()
    last_html = ""
    for index, candidate in enumerate(candidates):
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            html = fetch_page(candidate, settings, cookie=cookie, mobile=mobile_index(index))
        except requests.RequestException as exc:
            last_html = last_html or f"请求失败: {exc}"
            continue
        if detect_risk(html):
            last_html = html
            continue
        if len(html) > 4000 and _has_product_data(html):
            return html, candidate
        if len(html) > len(last_html):
            last_html = html
    if detect_risk(last_html):
        raise CollectError(
            "1688 返回了风控验证页。请在浏览器登录 1688 后复制 Cookie 填入，"
            "或改用“导入网页文件 / 导入文件夹 / 手动上传”方式采集。"
        )
    if not last_html or last_html.startswith("请求失败"):
        raise CollectError("无法获取商品页面，请检查链接或网络")
    raise CollectError(
        "1688 返回的页面中没有商品数据（可能是页面改版或临时风控）。"
        "请稍后重试、填写 Cookie，或改用“导入网页文件 / 导入文件夹 / 手动上传”方式采集。"
    )


def _is_allowed_detail_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in DETAIL_HOSTS)


def fetch_detail_resource(url: str, settings: dict, cookie: str = "", referer: str = "") -> tuple[str, str]:
    if not _is_allowed_detail_url(url):
        return "", "详情资源域名不在允许范围内"
    headers = _headers(settings, cookie=cookie)
    if referer:
        headers["Referer"] = referer
    try:
        response = requests.get(url, headers=headers, timeout=int(settings.get("download", {}).get("timeout", 30)),
                                allow_redirects=False, stream=True)
    except requests.RequestException as exc:
        return "", f"请求失败：{exc}"
    if response.is_redirect:
        response.close()
        return "", "详情资源返回了重定向，未跟随"
    if response.status_code != 200:
        response.close()
        return "", f"HTTP {response.status_code}"
    chunks = []
    total = 0
    encoding = response.encoding or "utf-8"
    try:
        for chunk in response.iter_content(64 * 1024):
            total += len(chunk)
            if total > 8 * 1024 * 1024:
                return "", "详情资源超过 8 MB 限制"
            chunks.append(chunk)
    finally:
        response.close()
    return b"".join(chunks).decode(encoding, errors="replace"), ""


def mobile_index(index: int) -> bool:
    return index == 1


def iter_json_blobs(text: str):
    text = str(text or "")
    patterns = (
        r"window\.context\s*=\s*",
        r"window\.context\s*=\s*window\.context\s*\|\|\s*",
        r"window\.context\.result\s*=\s*",
        r"window\.__INIT_DATA_*\s*=\s*",
        r"window\.__GLOBAL_DATA_*\s*=\s*",
        r"window\.__GLOBAL_DADA\s*=\s*",
        r"window\.__NEXT_DATA_*\s*=\s*",
        r"window\.__PRELOADED_STATE_*\s*=\s*",
        r"window\.__INITIAL_STATE_*\s*=\s*",
        r"var\s+offer_details\s*=\s*",
        r"window\.__DATA_*\s*=\s*",
    )
    decoder = json.JSONDecoder()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            cursor = match.end()
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            if cursor >= len(text) or text[cursor] not in "{[":
                continue
            try:
                obj, _ = decoder.raw_decode(text, cursor)
                yield pattern, obj
            except (ValueError, json.JSONDecodeError):
                continue
    for match in re.finditer(r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>', text, re.S | re.I):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            yield "script-json", json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            continue


def _walk(obj, path=()):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield from _walk(value, path + (str(key),))
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            yield from _walk(value, path + (str(index),))
    else:
        yield obj, path


def _is_noise_image(url: str) -> bool:
    """过滤 CDN 上的前端脚本、UI 图标和缩略图变体。"""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    if host.startswith(("g.", "g-")) or "code/npm" in path:
        return True
    if any(part in path for part in NOISE_PATH_PARTS):
        return True
    if path.endswith(NOISE_EXTENSIONS):
        return True
    if THUMBNAIL_VARIANT_RE.search(path):
        return True
    match = TINY_ICON_RE.search(path)
    if match and min(int(match.group(1)), int(match.group(2))) <= 300:
        return True
    return False


def _image_url(value) -> str:
    url = str(value or "").strip().replace("\\/", "/").replace("&amp;", "&")
    if url.startswith("//"):
        url = "https:" + url
    if not re.match(r"^https?://", url, re.I):
        return ""
    if _is_noise_image(url):
        return ""
    if IMAGE_EXT_RE.search(url):
        return url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "").lower()
    # 部分 CDN 图片地址没有扩展名，仅接受明确的图片路径
    if any(host == domain or host.endswith("." + domain) for domain in IMAGE_CDN_HOSTS):
        if any(token in path for token in ("/img/", "/imgextra/", "/bao/uploaded/", "/kf/")):
            return url
    return ""


def _video_url(value) -> str:
    url = str(value or "").strip().replace("\\/", "/").replace("&amp;", "&")
    if url.startswith("//"):
        url = "https:" + url
    if not re.match(r"^https?://", url, re.I):
        return ""
    path = urlparse(url).path or ""
    if VIDEO_EXT_RE.search(path) or VIDEO_EXT_RE.search(url):
        return url
    host = (urlparse(url).hostname or "").lower()
    if "vod." in host or host.startswith("video."):
        return url
    return ""


def _classify(path: tuple[str, ...], url: str = "") -> str:
    joined = " ".join(part.lower() for part in path[-6:])
    if any(key in joined for key in VIDEO_KEYS) or VIDEO_EXT_RE.search(url):
        return "video"
    if any(key in joined for key in SKU_KEYS):
        return "sku"
    if any(key in joined for key in DETAIL_KEYS):
        return "detail"
    if any(key in joined for key in MAIN_KEYS):
        return "main"
    if "globaldata" in joined and "images" in joined:
        return "main"
    return "unknown"


def _pick(data: dict, keys: tuple[str, ...], default=""):
    keys_lower = {str(key).lower(): key for key in data}
    for key in keys:
        actual = key if key in data else keys_lower.get(key.lower())
        value = data.get(actual) if actual is not None else None
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _new_result() -> dict:
    return {
        "title": "",
        "offerId": "",
        "sourceUrl": "",
        "price": "",
        "category": "",
        "main": [],
        "detail": [],
        "sku": [],
        "video": [],
        "unknown": [],
        "skuProps": [],
        "skuMap": [],
        "detailUrls": [],
        "detailText": "",
        "notes": [],
    }


def _append_unique(target: list, value: str) -> None:
    if value and value not in target:
        target.append(value)


def _add_sku_image(result: dict, url: str, name: str = "") -> None:
    if not url:
        return
    for existing in result["sku"]:
        if existing.get("url") == url:
            if name and not existing.get("name"):
                existing["name"] = name
            return
    for kind in ("main", "detail"):
        if url in result[kind]:
            return
    result["unknown"] = [item for item in result["unknown"] if item != url]
    result["sku"].append({"name": name, "url": url})


def _add_image_candidate(result: dict, url: str, kind: str) -> None:
    if not url:
        return
    if kind == "sku":
        _add_sku_image(result, url)
        return
    for existing_kind in ("main", "detail", "sku"):
        for item in result[existing_kind]:
            existing_url = item.get("url", "") if isinstance(item, dict) else item
            if existing_url == url:
                return
    result["unknown"] = [item for item in result["unknown"] if item != url]
    if kind in ("main", "detail"):
        _append_unique(result[kind], url)
    else:
        _append_unique(result["unknown"], url)


def parse_json_blob(obj, result: dict, depth: int = 0) -> None:
    if depth > 40:
        return
    if isinstance(obj, dict):
        keys_lower = {str(key).lower(): key for key in obj.keys()}
        if not result.get("title"):
            for key in ("offertitle", "subject", "itemtitle", "producttitle", "title"):
                actual = keys_lower.get(key)
                if actual:
                    value = _pick(obj, (actual,), "")
                    if value and 4 <= len(value) <= 120:
                        result["title"] = value
                        break
        if not result.get("price"):
            for key in ("pricerange", "saleprice", "discountprice", "price", "priceinfo"):
                actual = keys_lower.get(key)
                if actual:
                    value = _pick(obj, (actual,), "")
                    if value and len(value) < 60:
                        result["price"] = value
                        break
        if not result.get("offerId"):
            for key in ("offerid", "id"):
                actual = keys_lower.get(key)
                if actual and re.fullmatch(r"\d{6,}", str(obj.get(actual, ""))):
                    result["offerId"] = str(obj[actual])
                    break
        main_value = None
        for key in ("offerimglist", "mainimages", "mainimglist", "mainpiclist"):
            if key in keys_lower:
                main_value = obj[keys_lower[key]]
                break
        if isinstance(main_value, (list, tuple)):
            for item in main_value:
                if isinstance(item, str):
                    url = _image_url(item)
                elif isinstance(item, dict):
                    url = _image_url(_pick(item, ("url", "imgurl", "src", "imageurl", "picurl")))
                else:
                    url = ""
                _append_unique(result["main"], url)
        sku_images = None
        for key in ("skuimages", "skupiclist", "skuimage"):
            if key in keys_lower:
                sku_images = obj[keys_lower[key]]
                break
        if isinstance(sku_images, (list, tuple)):
            for item in sku_images:
                if isinstance(item, str):
                    _add_sku_image(result, _image_url(item))
                    continue
                if not isinstance(item, dict):
                    continue
                name = _pick(item, ("name", "colorname", "valuename", "specname", "title", "value"), "")
                url = _image_url(_pick(item, ("imgurl", "imageurl", "url", "src", "img", "picurl")))
                if name or url:
                    _add_sku_image(result, url, name)
        sku_props = None
        for key in ("skuprops", "props", "skupropertys", "property"):
            if key in keys_lower:
                sku_props = obj[keys_lower[key]]
                break
        if isinstance(sku_props, (list, tuple)):
            for prop in sku_props:
                if not isinstance(prop, dict):
                    continue
                prop_name = _pick(prop, ("prop", "name", "propname", "title"), "")
                values = prop.get("value") or prop.get("values") or prop.get("valueList") or []
                if not isinstance(values, (list, tuple)):
                    continue
                for value in values:
                    if not isinstance(value, dict):
                        continue
                    value_name = _pick(value, ("name", "value", "title"), "")
                    image = _image_url(_pick(value, ("imgurl", "imageurl", "url", "img", "picurl")))
                    item = {"prop": prop_name, "name": value_name, "image": image}
                    if item not in result["skuProps"]:
                        result["skuProps"].append(item)
                    if image:
                        _add_sku_image(result, image, value_name)
        sku_map = obj.get(keys_lower.get("skuinfomap", "")) or obj.get(keys_lower.get("skumap", ""))
        if isinstance(sku_map, dict):
            for key, value in sku_map.items():
                if not isinstance(value, dict):
                    continue
                result["skuMap"].append({
                    "spec": str(key).replace("&gt;", " > ").replace(">", " / "),
                    "price": _pick(value, ("price", "discountprice", "saleprice"), ""),
                    "stock": _pick(value, ("canbookcount", "stock", "amount", "quantity"), ""),
                })
        for value, path in _walk(obj):
            if not isinstance(value, str):
                continue
            if any(part.lower() in DETAIL_RESOURCE_KEYS for part in path):
                detail_url = value.strip()
                if detail_url and len(detail_url) < 2048:
                    _append_unique(result["detailUrls"], detail_url)
            url = _image_url(value)
            if url:
                kind = _classify(path, url)
                _add_image_candidate(result, url, kind)
            video = _video_url(value)
            if video:
                _append_unique(result["video"], video)
        for value in obj.values():
            if isinstance(value, (dict, list)):
                parse_json_blob(value, result, depth + 1)
    elif isinstance(obj, list):
        for item in obj:
            parse_json_blob(item, result, depth + 1)


class _ProductImageMarkupParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    MAIN_MARKERS = ("dt-tab", "detail-gallery-turn", "detail-gallery-img", "img-list-wrapper", "od-gallery-img", "od-scroller-item")
    SKU_MARKERS = ("pc-sku-wrapper", "prop-item-inner-wrapper", "sku-item-wrapper", "specification-cell", "sku-filter-button", "expand-view-item", "feature-item")
    DETAIL_MARKERS = ("de-description-detail", "detailcontentcontainer", "html-description", "desc-lazyload-container")

    def __init__(self, result: dict):
        super().__init__(convert_charrefs=True)
        self.result = result
        self.stack: list[tuple[str, dict[str, str]]] = []

    def _context_kind(self, attrs: dict[str, str]) -> str:
        values = [attrs.get("id", ""), attrs.get("class", "")]
        values.extend(parent_attrs.get("id", "") + " " + parent_attrs.get("class", "") for _, parent_attrs in self.stack)
        context = " ".join(values).lower()
        if any(marker in context for marker in self.MAIN_MARKERS):
            return "main"
        if any(marker in context for marker in self.SKU_MARKERS):
            return "sku"
        if any(marker in context for marker in self.DETAIL_MARKERS):
            return "detail"
        return "unknown"

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value or "" for key, value in attrs}
        kind = self._context_kind(attr_map)
        candidates = [
            attr_map.get(key, "")
            for key in ("src", "data-src", "data-lazy-src", "data-lazyload-src", "data-ks-lazyload")
        ]
        candidates.extend(re.findall(r"url\(\s*['\"]?([^)'\" ]+)['\"]?\s*\)", attr_map.get("style", ""), re.I))
        if tag.lower() in ("img", "source") or attr_map.get("style"):
            for candidate in candidates:
                _add_image_candidate(self.result, _image_url(candidate), kind)
        if tag.lower() not in self.VOID_TAGS:
            self.stack.append((tag.lower(), attr_map))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def _normalize_detail_resource_url(value: str, base_url: str) -> str:
    url = urljoin(base_url, str(value or "").strip().replace("\\/", "/"))
    if not url.startswith(("http://", "https://")):
        return ""
    # 1688 会用 air.1688.com 的外壳页包裹真实详情资源，优先取内层直链
    inner = parse_qs(urlparse(url).query).get("url", [""])[0]
    if inner:
        inner_url = urljoin(url, inner)
        if inner_url.startswith(("http://", "https://")) and _is_allowed_detail_url(inner_url):
            return inner_url
    if _is_allowed_detail_url(url):
        return url
    return ""


def parse_html(html: str, base_url: str = "") -> dict:
    result = _new_result()
    result["sourceUrl"] = normalize_url(base_url)
    result["offerId"] = extract_offer_id(base_url or html)
    for name, obj in iter_json_blobs(html):
        before = tuple(len(result[key]) for key in ("main", "detail", "sku", "video", "unknown"))
        parse_json_blob(obj, result)
        after = tuple(len(result[key]) for key in ("main", "detail", "sku", "video", "unknown"))
        if before != after:
            result["notes"].append(f"从 {name} 解析到素材数据")

    title_match = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if not title_match:
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.I | re.S)
    if title_match and not result.get("title"):
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title_match.group(1))).strip()
        title = re.split(r"[—_\-|\-]", title)[0].replace("阿里巴巴", "").strip()
        if 4 <= len(title) <= 120:
            result["title"] = title
    og_image = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if og_image:
        _add_image_candidate(result, _image_url(og_image.group(1)), "main")
    markup_parser = _ProductImageMarkupParser(result)
    markup_parser.feed(html)
    for url in re.findall(r"https?:\\?/\\?/[^\"'\s<>]+?\.(?:jpg|jpeg|png|webp)", html, re.I):
        image_url = _image_url(url.replace("\\/", "/"))
        _add_image_candidate(result, image_url, "unknown")
    result["detailUrls"] = list(dict.fromkeys(
        normalized for value in result["detailUrls"]
        if (normalized := _normalize_detail_resource_url(value, result["sourceUrl"]))
    ))[:3]
    unknown_count = len(result["unknown"])
    result["unknown"] = result["unknown"][:120]
    if result["unknown"]:
        result["notes"].append(f"有 {len(result['unknown'])} 张图片无法确定用途，已放入待确认")
    if unknown_count > len(result["unknown"]):
        result["notes"].append(f"页面图片较多，仅保留前 {len(result['unknown'])} 张待确认候选")
    result["main"] = [url for url in result["main"] if url][:12]
    result["detail"] = [url for url in result["detail"] if url][:120]
    result["sku"] = [item for item in result["sku"] if item.get("url")][:40]
    result["video"] = [url for url in result["video"] if url][:8]
    return result


def parse_desc_html(text: str, base_url: str = "") -> dict:
    result = _new_result()
    match = re.search(r"var\s+offer_details\s*=\s*(\{.*?\})\s*;?\s*$", text, re.S)
    if not match:
        match = re.search(r"offer_details\s*=\s*(\{.*?\})\s*;", text, re.S)
    content = text
    if match:
        try:
            obj, _ = json.JSONDecoder().raw_decode(match.group(1), 0)
        except (ValueError, json.JSONDecodeError):
            obj = None
        if isinstance(obj, dict):
            content = str(obj.get("content", ""))
    for src in re.findall(r'<(?:img|source)[^>]+(?:src|data-src|data-lazy-src)=["\']([^"\']+)', content, re.I):
        _add_image_candidate(result, _image_url(urljoin(base_url, src)), "detail")
    for style in re.findall(r'\bstyle=["\']([^"\']*url\([^)]+\)[^"\']*)["\']', content, re.I):
        for src in re.findall(r"url\(\s*['\"]?([^)'\" ]+)['\"]?\s*\)", style, re.I):
            _add_image_candidate(result, _image_url(urljoin(base_url, src)), "detail")
    result["detailText"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", content)).strip()[:4000]
    return result


def parse_bytes(filename: str, data: bytes) -> dict:
    text = data.decode("utf-8", errors="replace")
    lowered = filename.lower()
    if lowered.endswith(".json") or text.lstrip().startswith(("{", "[")):
        try:
            obj = json.loads(text)
        except (ValueError, json.JSONDecodeError):
            obj = None
        if obj is not None:
            result = _new_result()
            parse_json_blob(obj, result)
            return result
    if lowered.endswith("desc.html") or "offer_details" in text:
        desc = parse_desc_html(text, "")
        if desc["detail"]:
            return desc
    return parse_html(text, "")


def merge_results(results: list[dict]) -> dict:
    merged = _new_result()
    for result in results:
        for key in ("title", "offerId", "sourceUrl", "price", "category", "detailText"):
            if not merged.get(key) and result.get(key):
                merged[key] = result[key]
        for key in ("main", "detail", "video", "unknown"):
            for item in result.get(key, []):
                _append_unique(merged[key], item)
        for item in result.get("detailUrls", []):
            _append_unique(merged["detailUrls"], item)
        for item in result.get("sku", []):
            if item not in merged["sku"]:
                merged["sku"].append(item)
        for item in result.get("skuProps", []):
            if item not in merged["skuProps"]:
                merged["skuProps"].append(item)
        for item in result.get("skuMap", []):
            if item not in merged["skuMap"]:
                merged["skuMap"].append(item)
        merged["notes"].extend(result.get("notes", []))
    return merged


def _tmp_file(data: bytes, suffix: str) -> Path:
    fd, path = tempfile.mkstemp(suffix=suffix or ".jpg")
    with open(fd, "wb") as f:
        f.write(data)
    return Path(path)


def download_one(
    task_id: str,
    kind: str,
    index: int,
    url: str,
    name: str,
    settings: dict,
    seen_hashes: set,
    cookie: str = "",
) -> tuple[dict | None, str | None]:
    url = normalize_url(url)
    if not url:
        return None, "空链接"
    download = settings.get("download", {})
    timeout = int(download.get("timeout", 30))
    retries = int(download.get("retries", 3))
    max_bytes = int(download.get("max_file_mb", 40)) * 1024 * 1024
    headers = _headers(settings, cookie=cookie)
    headers["Accept"] = "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"
    last_error = "未知错误"
    for attempt in range(max(1, retries)):
        try:
            response = requests.get(url, headers=headers, timeout=timeout, stream=True)
            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}"
                response.close()
                continue
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                response.close()
                return None, "文件过大"
            buffer = io.BytesIO()
            for chunk in response.iter_content(1024 * 64):
                if not chunk:
                    continue
                buffer.write(chunk)
                if buffer.tell() > max_bytes:
                    response.close()
                    return None, "文件过大"
            response.close()
            data = buffer.getvalue()
            if len(data) < 512:
                return None, "文件为空或过小"
            import hashlib

            digest = hashlib.sha1(data).hexdigest()
            if digest in seen_hashes:
                return None, None
            suffix = Path(url.split("?")[0]).suffix.lower()
            if suffix not in storage.ALLOWED_RAW_EXTS:
                suffix = ".mp4" if kind == "video" else ".jpg"
            if kind != "video":
                try:
                    with Image.open(io.BytesIO(data)) as image:
                        width, height = image.size
                        image.verify()
                    if kind != "review" and min(width, height) < 120:
                        return None, "图片分辨率过低"
                except Exception as exc:
                    return None, f"不是有效图片: {exc}"
            temp = _tmp_file(data, suffix)
            try:
                record = storage.copy_into_raw(task_id, temp, kind, index=index, name=name, url=url)
            finally:
                temp.unlink(missing_ok=True)
            seen_hashes.add(digest)
            return record, None
        except requests.RequestException as exc:
            last_error = str(exc)
            time.sleep(0.3 * (attempt + 1))
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.2)
    return None, last_error


def download_all(task_id: str, parsed: dict, settings: dict, progress=None, cookie: str = "") -> dict:
    jobs = []
    parsed_kinds = (
        ("main", "main"),
        ("detail", "detail"),
        ("sku", "sku"),
        ("video", "video"),
        ("review", "unknown"),
    )
    for kind, parsed_kind in parsed_kinds:
        seen_in_kind = set()
        for index, item in enumerate(parsed.get(parsed_kind, []), 1):
            url = item if isinstance(item, str) else item.get("url", "")
            name = "" if isinstance(item, str) else item.get("name", "")
            if not url or url in seen_in_kind:
                continue
            seen_in_kind.add(url)
            jobs.append((kind, index, url, name))
    total = len(jobs)
    if progress:
        progress(0, total)
    records: dict[str, list[dict]] = {kind: [] for kind in storage.RAW_KINDS}
    errors = []
    seen_hashes: dict[str, set] = {kind: set() for kind in records}
    workers = max(1, int(settings.get("download", {}).get("concurrency", 4)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                download_one, task_id, kind, index, url, name, settings, seen_hashes[kind], cookie
            ): (kind, url)
            for kind, index, url, name in jobs
        }
        done = 0
        for future in as_completed(futures):
            kind, url = futures[future]
            done += 1
            try:
                record, error = future.result()
            except Exception as exc:
                record, error = None, str(exc)
            if record:
                records[kind].append(record)
            elif error:
                errors.append({"kind": kind, "url": url, "error": error})
            if progress:
                progress(done, total)
    for kind in records:
        def sort_key(record):
            match = re.search(r"(\d+)", Path(record.get("file", "")).stem)
            return int(match.group(1)) if match else 0

        records[kind].sort(key=sort_key)
    if parsed.get("sku"):
        names = [item.get("name", "") for item in parsed["sku"] if isinstance(item, dict)]
        urls = [item.get("url", "") for item in parsed["sku"] if isinstance(item, dict)]
        for record in records["sku"]:
            index_match = re.search(r"(\d+)", Path(record.get("file", "")).stem)
            position = int(index_match.group(1)) - 1 if index_match else -1
            if 0 <= position < len(names) and names[position]:
                record["name"] = names[position]
                record["url"] = urls[position] if position < len(urls) else record.get("url", "")
    return {"records": records, "errors": errors, "total": total}


def build_sku(task_id: str, parsed: dict, records: dict) -> list[dict]:
    groups = storage.scan_raw(task_id)
    sku_records = records.get("sku", [])
    sku = []
    for index, rel in enumerate(groups.get("sku", [])):
        record = next((item for item in sku_records if item.get("file") == rel), None)
        name = record.get("name", "") if record else ""
        if not name and index < len(parsed.get("sku", [])):
            name = parsed["sku"][index].get("name", "")
        if not name:
            name = re.sub(r"^sku_\d+_", "", Path(rel).stem)
        sku.append({
            "name": name,
            "price": "",
            "stock": "",
            "image": rel,
            "url": (record or {}).get("url", ""),
        })
    for item in parsed.get("skuMap", []):
        spec = str(item.get("spec", ""))
        for entry in sku:
            if entry["name"] and entry["name"] in spec:
                entry["price"] = item.get("price", "")
                entry["stock"] = item.get("stock", "")
    return sku


def apply_parsed(task_id: str, parsed: dict, settings: dict, progress=None, cookie: str = "") -> dict:
    def _update(meta):
        for key, source in (
            ("title", "title"),
            ("offerId", "offerId"),
            ("sourceUrl", "sourceUrl"),
            ("price", "price"),
            ("category", "category"),
        ):
            value = parsed.get(source)
            if value and not meta.get(key):
                meta[key] = value
        meta["skuProps"] = parsed.get("skuProps", [])
        storage.add_log(
            meta,
            f"解析完成：主图 {len(parsed.get('main', []))} / 详情 {len(parsed.get('detail', []))} / "
            f"SKU {len(parsed.get('sku', []))} / 待确认 {len(parsed.get('unknown', []))}",
        )
        return meta

    storage.update_meta(task_id, _update)
    result = download_all(task_id, parsed, settings, progress, cookie=cookie)
    records = result["records"]
    sku = build_sku(task_id, parsed, records)

    def _finish(meta):
        meta["raw"] = records
        meta["sku"] = sku
        meta["status"] = "collected"
        meta["statusText"] = "已归档"
        meta["lastError"] = ""
        meta["progress"] = {"done": result["total"], "total": result["total"]}
        if result["errors"]:
            meta["status"] = "collected_partial"
            meta["statusText"] = "已归档（部分失败）"
            storage.add_log(meta, f"下载失败 {len(result['errors'])} 项，详情见日志", "warn")
            for error in result["errors"][:20]:
                storage.add_log(meta, f"{error['kind']} 下载失败：{error['error']}", "warn")
        for note in parsed.get("notes", []):
            storage.add_log(meta, note)
        storage.add_log(meta, "素材归档完成")
        return meta

    meta = storage.update_meta(task_id, _finish)
    storage.write_task_aux(task_id, meta)
    return meta


def collect_from_url(task_id: str, url: str, settings: dict, cookie: str = "") -> dict:
    html, final_url = fetch_product_html(url, settings, cookie)
    parsed = parse_html(html, final_url)
    for detail_url in parsed.get("detailUrls", []):
        detail_html, error = fetch_detail_resource(
            detail_url, settings, cookie=cookie, referer=final_url,
        )
        if error:
            parsed["notes"].append(f"详情素材资源未能读取：{error}")
            continue
        if detect_risk(detail_html):
            parsed["notes"].append("详情素材资源触发了风控验证，已停止解析")
            continue
        detail_result = parse_desc_html(detail_html, detail_url)
        if not detail_result["detail"]:
            detail_result = parse_html(detail_html, detail_url)
        parsed = merge_results([parsed, detail_result])
    if not parsed["main"] and not parsed["detail"] and not parsed["sku"] and not parsed["unknown"]:
        raise CollectError("页面中没有识别到商品图片，请用“导入网页文件 / 导入文件夹 / 手动上传”方式")
    return apply_parsed(task_id, parsed, settings, cookie=cookie)


def _classify_path(path: Path) -> str | None:
    parts = [part.lower() for part in path.parts]
    parts.append(path.name.lower())
    joined = " ".join(parts)
    if any(key in joined for key in ("视频", "video", ".mp4", ".mov", ".webm")):
        return "video"
    if any(key in joined for key in ("sku", "规格", "颜色")):
        return "sku"
    if any(key in joined for key in ("详情", "detail", "desc", "描述")):
        return "detail"
    if any(key in joined for key in ("主图", "main", "offerimg")):
        return "main"
    return None


def scan_folder(folder: str) -> dict:
    folder_path = Path(folder)
    if not folder_path.is_dir():
        raise CollectError(f"文件夹不存在: {folder}")
    info = {}
    info_candidates = [folder_path / "info.json"] + list(folder_path.glob("**/info.json"))
    for candidate in info_candidates[:5]:
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                info = loaded
                break
        except (OSError, ValueError):
            continue
    by_kind: dict[str, list[dict]] = {kind: [] for kind in ("main", "detail", "sku", "video")}
    unclassified = []
    for path in folder_path.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in storage.ALLOWED_RAW_EXTS:
            continue
        rel = path.relative_to(folder_path)
        item = {"path": path, "rel": rel.as_posix(), "kind": _classify_path(rel), "name": "", "url": ""}
        if item["kind"]:
            by_kind[item["kind"]].append(item)
        else:
            unclassified.append(item)
    if unclassified:
        by_kind["main"].extend(unclassified)
    sku_names = [str(item.get("name", "")) for item in info.get("skuImages", []) if isinstance(item, dict)]
    sku_urls = [str(item.get("url", "")) for item in info.get("skuImages", []) if isinstance(item, dict)]
    main_urls = [str(item) for item in info.get("mainImages", [])]
    detail_urls = [str(item) for item in info.get("detailImages", [])]
    for kind, urls in (("main", main_urls), ("detail", detail_urls), ("sku", sku_urls)):
        by_kind[kind].sort(key=lambda item: [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", item["rel"])])
        for index, item in enumerate(by_kind[kind]):
            if index < len(urls):
                item["url"] = urls[index]
            if kind == "sku" and index < len(sku_names):
                item["name"] = sku_names[index]
    for kind in by_kind:
        by_kind[kind].sort(key=lambda item: [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", item["rel"])])
    return {
        "folder": folder,
        "info": info,
        "files": by_kind,
        "title": str(info.get("title", "") or folder_path.name),
        "offerId": str(info.get("offerId", "") or ""),
        "sourceUrl": str(info.get("sourceUrl", "") or ""),
        "price": str(info.get("price", "") or ""),
        "counts": {kind: len(items) for kind, items in by_kind.items()},
    }


def collect_from_folder(task_id: str, folder: str, settings: dict) -> dict:
    plan = scan_folder(folder)
    records: dict[str, list[dict]] = {kind: [] for kind in ("main", "detail", "sku", "video")}
    for kind, items in plan["files"].items():
        for index, item in enumerate(items, 1):
            try:
                name = item.get("name") or (Path(item["path"]).stem if kind == "detail" else "")
                records[kind].append(
                    storage.copy_into_raw(task_id, item["path"], kind, index=index, name=name, url=item.get("url", ""))
                )
            except Exception as exc:
                def _log_error(meta, rel=item["rel"], error=exc):
                    storage.add_log(meta, f"导入失败 {rel}: {error}", "warn")
                    return meta

                storage.update_meta(task_id, _log_error)
    sku = []
    for index, rel in enumerate(storage.scan_raw(task_id)["sku"]):
        record = next((item for item in records["sku"] if item.get("file") == rel), None)
        name = (record or {}).get("name", "") or re.sub(r"^sku_\d+_", "", Path(rel).stem)
        sku.append({
            "name": name,
            "price": "",
            "stock": "",
            "image": rel,
            "url": (record or {}).get("url", ""),
        })

    def _finish(meta):
        if plan.get("title") and not meta.get("title"):
            meta["title"] = plan["title"]
        if plan.get("offerId") and not meta.get("offerId"):
            meta["offerId"] = plan["offerId"]
        if plan.get("sourceUrl") and not meta.get("sourceUrl"):
            meta["sourceUrl"] = plan["sourceUrl"]
        meta["raw"] = records
        meta["sku"] = sku
        meta["status"] = "collected"
        meta["statusText"] = "已归档"
        meta["lastError"] = ""
        storage.add_log(
            meta,
            f"文件夹导入完成：主图 {len(records['main'])} / 详情 {len(records['detail'])} / SKU {len(records['sku'])} / 视频 {len(records['video'])}",
        )
        if not any(plan["files"].values()):
            meta["status"] = "failed"
            meta["statusText"] = "采集失败"
            meta["lastError"] = "文件夹中没有找到图片或视频"
        return meta

    meta = storage.update_meta(task_id, _finish)
    storage.write_task_aux(task_id, meta)
    return meta


def collect_from_page_files(task_id: str, files: list[tuple[str, bytes]], settings: dict) -> dict:
    results = [parse_bytes(filename, data) for filename, data in files]
    parsed = merge_results(results)
    if not parsed["main"] and not parsed["detail"] and not parsed["sku"] and not parsed["unknown"]:
        raise CollectError("上传的文件里没有识别到商品图片，请确认保存的是商品页 HTML 或接口 JSON")
    return apply_parsed(task_id, parsed, settings)


def collect_from_zip(task_id: str, zip_path: str, settings: dict) -> dict:
    zip_path = Path(zip_path)
    temp_dir = Path(tempfile.mkdtemp(prefix="taobao_zip_"))
    try:
        with zipfile.ZipFile(zip_path) as archive:
            for member in archive.infolist():
                name = member.filename.replace("\\", "/")
                if name.endswith("/"):
                    continue
                target = (temp_dir / name).resolve()
                if temp_dir.resolve() not in target.parents:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, open(target, "wb") as destination:
                    destination.write(source.read())
        return collect_from_folder(task_id, str(temp_dir), settings)
    finally:
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)


def refresh_meta_from_files(task_id: str, meta: dict | None = None) -> dict:
    meta = meta or storage.load_meta(task_id)
    groups = storage.scan_raw(task_id)
    task_dir = config.TASKS_DIR / task_id
    for kind, rels in groups.items():
        existing = {item.get("file") for item in meta.get("raw", {}).get(kind, [])}
        for rel in rels:
            if rel in existing:
                continue
            path = task_dir / rel
            meta["raw"].setdefault(kind, []).append(storage.file_record(path, task_dir))
        meta["raw"][kind] = [item for item in meta["raw"].get(kind, []) if (task_dir / item.get("file", "")).is_file()]
    if not meta.get("sku") and groups.get("sku"):
        meta["sku"] = storage.rebuild_sku_from_files(task_id)
    if any(groups.values()):
        meta["status"] = "collected"
        meta["statusText"] = "已归档"
    return storage.save_meta(task_id, meta)
