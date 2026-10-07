"""URL 识别、短链展开、平台归一化。

三个平台各自的链接形态差异很大，这里统一收口：
  - 小红书分享出来是一整段带文案的话，链接夹在中间，得先抠出来
  - 小红书/B站都有短链（xhslink.com / b23.tv），yt-dlp 不认，得先展开成真实 URL
  - 小红书改名叫 rednote 了，但 yt-dlp 的 extractor 只认 xiaohongshu.com（issue #16519）
"""

import re

import requests

UA_DESKTOP = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

PLATFORM_NAMES = {
    "bilibili": "B站",
    "youtube": "YouTube",
    "xiaohongshu": "小红书",
}

# 短链域名 → 平台
SHORT_LINKS = {
    "b23.tv": "bilibili",
    "xhslink.com": "xiaohongshu",
    "xhs.link": "xiaohongshu",
}

_DOMAINS = {
    "bilibili": ("bilibili.com", "b23.tv"),
    "youtube": ("youtube.com", "youtu.be"),
    "xiaohongshu": ("xiaohongshu.com", "xhslink.com", "rednote.com", "xhs.link"),
}


class UnsupportedURL(ValueError):
    """链接不属于任何支持的平台。"""


def extract_url(text: str) -> str:
    """从一段文本里抠出第一个 URL。

    小红书 App 的分享是「39 这个博主讲得真好 😆 http://xhslink.com/a/xxx 复制本条信息，
    打开【小红书】」这种，直接拿去请求必然失败，所以要先提链接。
    """
    text = (text or "").strip()
    m = re.search(r"https?://[^\s，。、；）)】\]\"'<>]+", text)
    return m.group(0).rstrip(".,;)") if m else text


def host_of(url: str) -> str:
    m = re.match(r"https?://([^/?#]+)", url)
    return (m.group(1) if m else "").lower().removeprefix("www.").removeprefix("m.")


def detect(url: str) -> str:
    """判定平台。识别不出就抛 UnsupportedURL。"""
    host = host_of(url)
    for platform, domains in _DOMAINS.items():
        if any(host == d or host.endswith("." + d) for d in domains):
            return platform
    raise UnsupportedURL(
        f"无法识别的链接：{host or url[:60]}\n目前支持 B站 / 小红书 / YouTube"
    )


def expand(url: str) -> str:
    """展开短链，返回真实 URL。非短链原样返回。

    用 range 头只取跳转本身，不拉正文，省流量也快。
    """
    host = host_of(url)
    if host not in SHORT_LINKS:
        return url

    ua = UA_MOBILE if SHORT_LINKS[host] == "xiaohongshu" else UA_DESKTOP
    try:
        r = requests.get(
            url,
            headers={"User-Agent": ua},
            allow_redirects=True,
            timeout=15,
            stream=True,
        )
        final = r.url
        r.close()
    except requests.RequestException:
        # 展开失败就把原链接交出去，让下游给出更具体的报错
        return url

    return normalize(final)


def normalize(url: str) -> str:
    """把平台内部的域名变体归一成 yt-dlp / 官方 API 认的形式。"""
    # 小红书改名 rednote 后 yt-dlp 尚未支持，换回旧域名
    url = re.sub(r"https?://(www\.)?rednote\.com/", "https://www.xiaohongshu.com/", url)
    # 移动端域名统一成 www
    url = re.sub(r"https?://m\.bilibili\.com/", "https://www.bilibili.com/", url)
    url = re.sub(r"https?://m\.youtube\.com/", "https://www.youtube.com/", url)
    return url


def resolve(text: str) -> tuple[str, str]:
    """一步到位：原始输入 → (平台, 归一化后的真实 URL)。"""
    url = normalize(extract_url(text))
    platform = detect(url)
    return platform, expand(url)
