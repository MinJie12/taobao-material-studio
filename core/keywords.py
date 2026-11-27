# -*- coding: utf-8 -*-
"""关键词分词、分类、主图标签与标题组合。"""
from __future__ import annotations

import re
import threading
from collections import Counter

from . import config, imaging

_ENGINE = None
_ENGINE_LOCK = threading.RLock()

CATEGORY_ORDER = ["core", "style", "selling", "scene", "detail", "color_spec", "other"]


class Engine:
    def __init__(self):
        dictionaries = config.load_dictionaries()
        self.categories = dictionaries.get("categories", {}) or {}
        self.colors = dictionaries.get("colors", {}) or {}
        self.sizes = set(dictionaries.get("sizes", []) or [])
        self.term_category: dict[str, str] = {}
        self.term_weight: dict[str, float] = {}
        self.terms: list[str] = []
        for key, category in self.categories.items():
            weight = float(category.get("weight", 1.0))
            for raw in category.get("words", []) or []:
                word = str(raw).strip()
                if not word:
                    continue
                if word not in self.term_category:
                    self.term_category[word] = key
                    self.term_weight[word] = weight
                if word not in self.terms:
                    self.terms.append(word)
        self.terms.sort(key=len, reverse=True)
        self.term_by_lower = {}
        for term in self.terms:
            self.term_by_lower.setdefault(term.lower(), term)
        self.terms_by_length = sorted(self.term_by_lower.keys(), key=len, reverse=True)
        self.stopwords = config.load_stopwords()
        self.banned = config.load_banned_words()
        self.brands = {item.lower() for item in config.load_brands()}
        self.jieba = None
        try:
            import jieba

            jieba.setLogLevel(60)
            for term in self.terms:
                jieba.add_word(term, freq=2000)
            self.jieba = jieba
        except Exception:
            self.jieba = None

    def clean(self, token: str) -> str:
        token = str(token or "").strip().lower()
        token = re.sub(r"^[^\w\u4e00-\u9fff+%]+|[^\w\u4e00-\u9fff+%]+$", "", token)
        if not token:
            return ""
        if token in self.sizes or token in self.colors:
            return token
        if token.isdigit():
            return ""
        if len(token) == 1 and not re.match(r"[a-z]", token):
            return ""
        if token in self.stopwords or token in self.banned:
            return ""
        return token

    def tokenize_other(self, text: str) -> list[str]:
        text = str(text or "").lower()
        tokens: list[str] = []
        if self.jieba is not None:
            raw_tokens = self.jieba.lcut(text)
        else:
            raw_tokens = []
            for chunk in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9+%]+", text):
                if re.fullmatch(r"[a-z0-9+%]+", chunk):
                    raw_tokens.append(chunk)
                else:
                    raw_tokens.extend(self._max_match(chunk))
        for raw in raw_tokens:
            token = self.clean(raw)
            if not token:
                continue
            if token in self.term_by_lower:
                continue
            if token in self.colors or token in self.sizes:
                continue
            tokens.append(token)
        return tokens

    def _max_match(self, text: str) -> list[str]:
        result = []
        index = 0
        while index < len(text):
            matched = ""
            for term in self.terms_by_length:
                if text.startswith(term, index):
                    matched = term
                    break
            if matched:
                result.append(self.term_by_lower[matched])
                index += len(matched)
            else:
                result.append(text[index])
                index += 1
        return result

    def dictionary_hits(self, text: str) -> dict[str, int]:
        lower = str(text or "").lower()
        hits: dict[str, int] = {}
        for term_lower, term in self.term_by_lower.items():
            if len(term_lower) == 1 and re.match(r"[a-z]", term_lower):
                pattern = rf"(?<![a-z0-9]){re.escape(term_lower)}(?![a-z0-9])"
                count = len(re.findall(pattern, lower))
            else:
                count = lower.count(term_lower)
            if count:
                hits[term] = min(2, count)
        return hits

    def scan_banned_brands(self, text: str, banned_found: set, brand_found: set) -> None:
        lower = str(text or "").lower()
        for word in self.banned:
            if word and word in lower:
                banned_found.add(word)
        for brand in self.brands:
            if not brand:
                continue
            if re.fullmatch(r"[a-z0-9 &'.-]+", brand):
                pattern = rf"(?<![a-z0-9]){re.escape(brand)}(?![a-z0-9])"
                if re.search(pattern, lower):
                    brand_found.add(brand)
            elif brand in lower:
                brand_found.add(brand)

    def contains_banned(self, text: str) -> bool:
        lower = str(text or "").lower()
        return any(word and word in lower for word in self.banned)


def get_engine() -> Engine:
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = Engine()
        return _ENGINE


def reset_engine() -> None:
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None


def _word_entries(category: dict) -> list[dict]:
    return list((category or {}).get("words", []) or [])


def top_words(analysis: dict, key: str, count: int = 5) -> list[str]:
    category = (analysis.get("categories", {}) or {}).get(key, {})
    words = _word_entries(category)
    words.sort(key=lambda item: (item.get("score", 0), item.get("count", 0), len(item.get("word", ""))), reverse=True)
    return [str(item.get("word", "")) for item in words[:count] if item.get("word")]


def _color_words(analysis: dict, count: int) -> list[str]:
    engine = get_engine()
    words = top_words(analysis, "color_spec", 40)
    return [word for word in words if word in engine.colors][:count]


def _spec_words(analysis: dict, count: int) -> list[str]:
    engine = get_engine()
    words = top_words(analysis, "color_spec", 40)
    return [word for word in words if word not in engine.colors][:count]


def default_image_tags(categories: dict, color_tags: list[str] | None = None) -> dict[str, list[str]]:
    analysis = {"categories": categories}

    def top(key: str, count: int) -> list[str]:
        return top_words(analysis, key, count)

    tags = {
        "1": top("core", 2) + top("style", 3),
        "2": top("selling", 5),
        "3": top("scene", 4),
        "4": top("detail", 4),
        "5": top("color_spec", 5) + list(color_tags or []),
    }
    for slot, values in tags.items():
        seen = set()
        cleaned = []
        for word in values:
            if word and word not in seen:
                seen.add(word)
                cleaned.append(word)
        tags[slot] = cleaned[:6]
    return tags


def analyze(
    titles: list[str],
    product_title: str = "",
    image_tags: dict | None = None,
    color_tags: dict | None = None,
) -> dict:
    engine = get_engine()
    competitor_titles = [str(title).strip() for title in (titles or []) if str(title).strip()][:300]
    product_title = str(product_title or "").strip()
    comp_counts: Counter = Counter()
    prod_counts: Counter = Counter()
    other_comp: Counter = Counter()
    other_prod: Counter = Counter()
    banned_found: set[str] = set()
    brand_found: set[str] = set()

    for title in competitor_titles:
        comp_counts.update(engine.dictionary_hits(title))
        other_comp.update(engine.tokenize_other(title))
        engine.scan_banned_brands(title, banned_found, brand_found)
    if product_title:
        prod_counts.update(engine.dictionary_hits(product_title))
        other_prod.update(engine.tokenize_other(product_title))
        engine.scan_banned_brands(product_title, banned_found, brand_found)

    provided_tags: set[str] = set()
    for values in (image_tags or {}).values():
        for word in values or []:
            if word:
                provided_tags.add(str(word))

    categories: dict[str, dict] = {}
    for key in CATEGORY_ORDER:
        if key == "other":
            continue
        category = engine.categories.get(key, {})
        categories[key] = {"name": category.get("name", key), "words": []}

    for term, category_key in engine.term_category.items():
        comp = comp_counts.get(term, 0)
        prod = prod_counts.get(term, 0)
        if not comp and not prod:
            continue
        count = comp + prod * 0.6
        score = count * engine.term_weight.get(term, 1.0)
        sources = []
        if comp:
            sources.append("竞品高频")
        if prod:
            score += 0.8
            sources.append("商品标题")
        if term in provided_tags:
            score += 1.5
            sources.append("主图标签")
        categories.setdefault(category_key, {"name": category_key, "words": []})
        categories[category_key]["words"].append({
            "word": term,
            "count": round(count, 1),
            "score": round(score, 2),
            "source": sources,
        })

    other_words = []
    merged_other = Counter()
    for word, count in other_comp.items():
        merged_other[word] += count
    for word, count in other_prod.items():
        merged_other[word] += count * 0.6
    for word, count in merged_other.most_common(80):
        if len(word) < 2:
            continue
        if len(competitor_titles) > 3 and count < 2:
            continue
        score = count * 0.6
        sources = []
        if other_comp.get(word):
            sources.append("竞品高频")
        if other_prod.get(word):
            score += 0.3
            sources.append("商品标题")
        if word in provided_tags:
            score += 1.0
            sources.append("主图标签")
        other_words.append({
            "word": word,
            "count": round(count, 1),
            "score": round(score, 2),
            "source": sources,
        })
    categories["other"] = {"name": "其他候选词", "words": other_words[:40]}

    for category in categories.values():
        category["words"].sort(
            key=lambda item: (item.get("score", 0), item.get("count", 0), len(item.get("word", ""))),
            reverse=True,
        )
        category["words"] = category["words"][:30]

    color_names: list[str] = []
    for values in (color_tags or {}).values():
        for item in values or []:
            name = item.get("name") if isinstance(item, dict) else item
            if name and name not in color_names:
                color_names.append(str(name))
    default_tags = default_image_tags(categories, color_names)
    final_tags = {}
    for slot in ("1", "2", "3", "4", "5"):
        values = (image_tags or {}).get(slot)
        final_tags[slot] = [str(v) for v in values] if values else default_tags.get(slot, [])

    result = {
        "categories": categories,
        "imageTags": final_tags,
        "colorTags": color_tags or {},
        "bannedFound": sorted(banned_found),
        "brandFound": sorted(brand_found),
        "stats": {
            "titleCount": len(competitor_titles),
            "wordCount": sum(len(category.get("words", [])) for category in categories.values()),
        },
    }
    result["titles"] = generate_titles(result, product_title)
    result["copy"] = suggest_copy(result)
    return result


def _title_candidates(analysis: dict, product_title: str) -> list[dict]:
    top = lambda key, n: top_words(analysis, key, n)
    templates = [
        [("core", 2), ("style", 2), ("selling", 2), ("scene", 1)],
        [("style", 1), ("core", 2), ("selling", 2), ("detail", 1)],
        [("core", 2), ("selling", 2), ("scene", 1), ("color", 1)],
        [("core", 2), ("detail", 2), ("selling", 1), ("style", 1)],
        [("core", 2), ("style", 1), ("scene", 1), ("color", 1), ("spec", 1)],
        [("core", 2), ("selling", 1), ("detail", 1), ("color", 1), ("spec", 1)],
        [("style", 1), ("core", 2), ("scene", 1), ("detail", 1)],
        [("core", 2), ("selling", 2), ("color", 1), ("spec", 1)],
    ]
    score_map = {}
    category_map = {}
    for key, category in (analysis.get("categories", {}) or {}).items():
        for entry in _word_entries(category):
            word = entry.get("word", "")
            if word:
                score_map[word] = max(score_map.get(word, 0), float(entry.get("score", 0) or 0))
                category_map[word] = key

    def words_for(key: str, count: int) -> list[str]:
        if key == "color":
            return _color_words(analysis, count)
        if key == "spec":
            return _spec_words(analysis, count)
        return top(key, count)

    results = []
    seen = set()
    for template in templates:
        words: list[str] = []
        used_categories = set()
        for key, count in template:
            picked = words_for(key, count)
            if picked:
                used_categories.add(key)
            for word in picked:
                if word and word not in words:
                    words.append(word)
        if not words:
            continue
        title = " ".join(words)
        while len(title) > 30 and words:
            words.pop()
            title = " ".join(words)
        if len(title) < 8:
            continue
        normalized = re.sub(r"\s+", "", title).lower()
        if normalized in seen:
            continue
        if get_engine().contains_banned(title):
            continue
        seen.add(normalized)
        word_score = sum(min(1.0, score_map.get(word, 0) / 4.0) for word in words)
        coverage = len(used_categories)
        length = len(title)
        length_bonus = 2.0 if 18 <= length <= 30 else (0.0 if length >= 12 else -2.0)
        overlap = 1.5 if any(word in product_title for word in words[:2]) else 0.0
        score = round(word_score * 2.0 + coverage * 1.2 + length_bonus + overlap, 2)
        results.append({
            "title": title,
            "score": score,
            "length": length,
            "words": words,
            "source": "词库组合",
        })

    if product_title and len(product_title) <= 30 and not get_engine().contains_banned(product_title):
        normalized = re.sub(r"\s+", "", product_title).lower()
        if normalized not in seen:
            results.append({
                "title": product_title,
                "score": 0.0,
                "length": len(product_title),
                "words": [],
                "source": "原标题参考",
            })
    results.sort(key=lambda item: (item.get("score", 0), item.get("length", 0)), reverse=True)
    return results


def generate_titles(analysis: dict, product_title: str = "", count: int = 8) -> list[dict]:
    results = _title_candidates(analysis, product_title)
    return results[: max(1, int(count))]


def generate_titles_from_words(words: list[str], product_title: str = "", count: int = 8) -> list[dict]:
    engine = get_engine()
    base = analyze([], product_title)
    categories = base.get("categories", {})
    for word in words or []:
        word = str(word).strip()
        if not word:
            continue
        key = engine.term_category.get(word)
        if not key:
            key = "color_spec" if (word in engine.colors or word in engine.sizes) else "other"
        category = categories.setdefault(key, {"name": key, "words": []})
        category.setdefault("words", []).append({
            "word": word,
            "count": 1,
            "score": 2.0,
            "source": ["手动选词"],
        })
    base["categories"] = categories
    base["titles"] = generate_titles(base, product_title, count)
    return base["titles"]


NEW_TITLE_LIMIT = 30
NEW_TITLE_COUNT = 5


def recommend_new_titles(product_title: str, competitors: list[str], facts: str = "", preferred: list[str] | None = None) -> list[dict]:
    """Rank confirmed phrases using competitor wording, then combine within the length limit."""
    engine = get_engine()
    ignored = {"新品", "新款", "新上市", "新品上市", "上新"}
    original = re.findall(r"[\w%+.-]+", product_title.strip())[:32]
    title_words = []
    anchors = set()
    for phrase in original:
        # Keep negated claims and numeric specifications together.
        parts = engine.jieba.lcut(phrase) if engine.jieba and not re.search(r"[不无非未\d]", phrase) else [phrase]
        core_index = next((index for index, part in enumerate(parts)
                           if engine.term_category.get(engine.term_by_lower.get(part.casefold(), "")) == "core"), None)
        if core_index is not None:
            prefix = parts[:core_index + 1]
            # Keep a short product phrase together, excluding marketing words.
            product = "".join(prefix)
            banned, brands = set(), set()
            engine.scan_banned_brands(product, banned, brands)
            if len(product) <= 18 and not banned and not brands and not any(part in ignored for part in prefix):
                anchors.add(product.casefold())
                parts = [product, *parts[core_index + 1:]]
        title_words.extend(parts)
    if not anchors and not any(engine.term_category.get(engine.term_by_lower.get(word.casefold(), "")) == "core"
                               for word in title_words):
        # Preserve names of products outside the built-in category dictionary.
        title_words = original if any(len(phrase) <= NEW_TITLE_LIMIT for phrase in original) else title_words
    fact_words = [part.strip() for part in re.split(r"[,，、;；\n]+", facts) if part.strip()]
    competitors = list(dict.fromkeys(title.casefold().strip() for title in competitors if title.strip()))[:300]
    preferred = {word.casefold() for word in (preferred or [])}
    words = {}
    for word in [*title_words, *fact_words]:
        word = word.strip()
        key = word.casefold()
        if key in words or key in ignored or not 1 <= len(word) <= NEW_TITLE_LIMIT:
            continue
        if not re.search(r"[^\W_]", word) or word in engine.stopwords:
            continue
        banned, brands = set(), set()
        engine.scan_banned_brands(word, banned, brands)
        if banned or brands:
            continue
        category = "core" if key in anchors else engine.term_category.get(engine.term_by_lower.get(key, ""), "other")
        if len(word) == 1 and word not in ("女", "男", "童") and category == "other":
            continue
        pattern = re.escape(key)
        if key.isascii():
            pattern = rf"(?<![a-z0-9]){pattern}(?![a-z0-9])"
        match = re.compile(pattern)
        hits = sum(bool(match.search(title)) for title in competitors)
        words[key] = (word, category, hits, key in preferred)
        if len(words) == 40:
            break
    terms = list(words.values())
    if not terms:
        return []
    anchor = next((term[0] for term in terms if term[1] == "core"), terms[0][0])
    profiles = [
        ("核心搜索", ("core", "style", "selling", "scene", "detail")),
        ("卖点优先", ("selling", "core", "detail", "style", "scene")),
        ("场景优先", ("scene", "style", "core", "selling", "detail")),
        ("细节优先", ("detail", "core", "selling", "style", "scene")),
        ("风格优先", ("style", "core", "scene", "detail", "selling")),
    ]
    results = []
    seen = set()
    for label, order in profiles[:NEW_TITLE_COUNT]:
        priorities = {category: len(order) - index for index, category in enumerate(order)}
        ordered = sorted(terms, key=lambda term: -priorities.get(term[1], 0))
        # Keep several alternatives per length and anchor-presence state.
        combinations = {(0, False): [(0, ())]}
        for word, category, hits, picked in ordered:
            for (length, anchored), candidates in list(combinations.items()):
                for score, parts in candidates:
                    separator = " " if parts and re.search(r"[a-z0-9]$", parts[-1], re.I) and re.match(r"[a-z0-9]", word, re.I) else ""
                    size = length + len(separator) + len(word)
                    if size > NEW_TITLE_LIMIT or any(word.casefold() in part.strip().casefold()
                                                     or part.strip().casefold() in word.casefold() for part in parts):
                        continue
                    key = (size, anchored or word == anchor)
                    weight = 2 + priorities.get(category, 0) + min(6, hits) * 2 + int(picked) * 3
                    choices = combinations.get(key, []) + [(score + weight, (*parts, separator + word))]
                    combinations[key] = sorted(choices, reverse=True)[:8]
        ranked = sorted(
            ((length, score, parts) for (length, anchored), candidates in combinations.items() if anchored
             for score, parts in candidates), reverse=True,
        )
        for length, score, parts in ranked:
            title = "".join(parts)
            key = title.replace(" ", "").casefold()
            banned, brands = set(), set()
            engine.scan_banned_brands(title, banned, brands)
            if key in seen or banned or brands:
                continue
            seen.add(key)
            results.append({"title": title, "length": length, "source": label, "words": [part.strip() for part in parts]})
            break
    return results


def suggest_copy(analysis: dict) -> dict:
    top = lambda key, n: top_words(analysis, key, n)
    core = top("core", 2)
    style = top("style", 3)
    selling = top("selling", 4)
    scene = top("scene", 3)
    detail = top("detail", 3)
    colors = _color_words(analysis, 3)
    specs = _spec_words(analysis, 2)

    def join(parts, sep=" "):
        values = [part for part in parts if part]
        return sep.join(values)

    slot1_head = join([style[0] if style else "", core[0] if core else ""]) or join(core[:2]) or "品质好物"
    slot1_sub = join(selling[:2], " · ") or join(style[:2], " · ") or "细节用心 · 舒适百搭"
    slot2_head = join(selling[:2]) or join(style[:2] + detail[:1]) or join(detail[:2]) or "版型升级"
    slot2_sub = join(detail[:2], " · ") or join(selling[:2], " · ") or "面料与做工细节"
    slot3_head = join(scene[:2]) or join(style[:2]) or join(core[:1] + ["日常百搭"]) or "日常百搭"
    slot3_sub = join([style[0] if style else "", core[0] if core else ""], " · ") or "多场景适用"
    slot4_head = join(detail[:2]) or join(selling[:2]) or "细节做工"
    slot4_sub = join(selling[:2], " · ") or join(detail[:2], " · ") or "看得见的品质"
    color_count = len(colors)
    slot5_head = f"{color_count}色可选" if color_count >= 2 else "多色可选"
    slot5_sub = "COLOR OPTIONS"
    bullets = selling[:4] or detail[:4] or ["舒适面料", "细节用心", "百搭好穿"]
    badge = f"{color_count}色可选" if color_count >= 2 else ""
    footer = join(selling[:3], " · ") or join(core[:1] + style[:2], " · ")
    return {
        "slots": {
            "1": {"headline": slot1_head, "subhead": slot1_sub, "bullets": bullets, "badge": badge, "footer": footer},
            "2": {"headline": slot2_head, "subhead": slot2_sub, "bullets": selling[:4], "badge": "", "footer": footer},
            "3": {"headline": slot3_head, "subhead": slot3_sub, "bullets": scene[:4], "badge": "", "footer": footer},
            "4": {"headline": slot4_head, "subhead": slot4_sub, "bullets": detail[:4], "badge": "", "footer": footer},
            "5": {"headline": slot5_head, "subhead": slot5_sub, "bullets": colors[:4], "badge": "", "footer": footer},
        },
        "colors": colors,
        "specs": specs,
    }


def analyze_task_colors(task_id: str, raw_groups: dict) -> dict:
    engine = get_engine()
    result = {}
    for index, rel in enumerate(raw_groups.get("main", [])[:5], 1):
        path = config.TASKS_DIR / task_id / rel
        result[str(index)] = imaging.analyze_image_colors(path, engine.colors)
    return result
