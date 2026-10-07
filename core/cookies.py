"""浏览器 cookie 探测与提取。

B站的 AI 字幕必须登录态才返回（匿名调用永远拿到空数组），小红书的 xsec_token
部分内容也要登录态。所以启动时要能回答两个问题：

  1. 用户的登录态在哪个浏览器里
  2. 缺哪个站点的登录态（缺了要让前端明说，否则用户会以为工具坏了）

首次探测要解密浏览器 cookie 库，比较慢，所以结果缓存起来。
"""

import threading

BROWSERS = [
    "chrome",
    "safari",
    "edge",
    "firefox",
    "brave",
    "chromium",
    "opera",
    "vivaldi",
    "whale",
]

# 判定"已登录"的 cookie 名。SESSDATA 是B站的登录票据，
# web_session 是小红书的，a1 是小红书的设备指纹（未登录也有，故只作为弱信号）。
SITES: dict[str, tuple[str, tuple[str, ...]]] = {
    "bilibili": ("bilibili.com", ("SESSDATA",)),
    "xiaohongshu": ("xiaohongshu.com", ("web_session",)),
}

_cache: dict[str, dict] | None = None
# 解密浏览器 cookie 库要 2~5 秒，不能每次请求都重来一遍
_jars: dict[str, object] = {}
_lock = threading.Lock()


def _get_jar(browser: str):
    """取（并缓存）某个浏览器的 cookie jar，不可用则返回 None。"""
    with _lock:
        if browser in _jars:
            return _jars[browser]

    try:
        from yt_dlp.cookies import extract_cookies_from_browser

        jar = extract_cookies_from_browser(browser)
    except Exception:
        jar = None

    with _lock:
        _jars[browser] = jar
    return jar


def _scan_browser(browser: str) -> dict:
    """返回 {'available': bool, 'total': int, 'sites': {site: bool}}"""
    jar = _get_jar(browser)
    if jar is None:
        return {"available": False, "total": 0, "sites": {}}

    names_by_domain: dict[str, set[str]] = {}
    total = 0
    for c in jar:
        total += 1
        names_by_domain.setdefault(c.domain, set()).add(c.name)

    sites = {}
    for site, (domain, markers) in SITES.items():
        found = set()
        for dom, names in names_by_domain.items():
            if domain in dom:
                found |= names
        sites[site] = any(m in found for m in markers)

    return {"available": True, "total": total, "sites": sites}


def probe(refresh: bool = False) -> dict:
    """扫描所有浏览器，返回 {browser: {...}}。结果会缓存。"""
    global _cache
    if refresh:
        with _lock:
            _jars.clear()
            _cache = None
    if _cache is None:
        _cache = {b: _scan_browser(b) for b in BROWSERS}
    return _cache


def summary() -> dict:
    """给前端用的摘要：每个站点该用哪个浏览器、还缺什么。"""
    data = probe()
    result: dict[str, dict] = {}
    for site in SITES:
        usable = [b for b, info in data.items() if info["sites"].get(site)]
        result[site] = {
            "logged_in": bool(usable),
            # 优先 chrome：它是多数人的主力浏览器，cookie 也最全
            "browser": ("chrome" if "chrome" in usable else usable[0]) if usable else None,
            "candidates": usable,
        }
    return result


def best_browser(site: str) -> str | None:
    """拿到某站点登录态最可用的浏览器名。"""
    return summary().get(site, {}).get("browser")


def cookie_header(site: str) -> str:
    """拼出可直接塞进 HTTP 请求头的 cookie 串。没有登录态则返回空串。"""
    browser = best_browser(site)
    if not browser:
        return ""

    jar = _get_jar(browser)
    if jar is None:
        return ""

    domain = SITES[site][0]
    pairs = [f"{c.name}={c.value}" for c in jar if domain in c.domain]
    return "; ".join(pairs)


def cookie_header_for_bilibili() -> str:
    """B站直调官方 API 用。"""
    return cookie_header("bilibili")
