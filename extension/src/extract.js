/**
 * 在页面主世界里执行的提取函数。
 *
 * 注意：这个函数会被序列化后送进页面执行，所以**不能引用任何外部作用域的变量**，
 * 所有依赖都必须写在函数体内部。它也是为什么扩展要在这里做这件事的原因 ——
 * 主世界能读到页面的 JS 变量（content script 跑在隔离世界里读不到），
 * 而人已经在页面上登录好了，媒体地址就在手边，不用再远程抓一次。
 *
 * 返回的对象必须是可 JSON 序列化的。
 */
function extractPageData() {
  const href = location.href;
  const host = location.hostname;
  const out = {
    url: href,
    platform: '',
    media_url: '',
    title: '',
    author: '',
    extra: ''
  };

  const pickStreamUrl = (note) => {
    const video = note && note.video;
    const stream = video && video.media && video.media.stream;

    // 按 h264 / h265 / av1 的顺序找，h264 兼容性最好。
    // 注意这里不能因为 stream 缺失就提前返回 —— 下面那个 originVideoKey
    // 兜底是没有 stream 时唯一的路。
    const codecs = ['h264', 'h265', 'av1'];
    for (let i = 0; i < codecs.length; i++) {
      const arr = stream && stream[codecs[i]];
      if (arr && arr.length) {
        const f = arr[0];
        if (f.masterUrl) return f.masterUrl;
        if (f.backupUrls && f.backupUrls.length) return f.backupUrls[0];
      }
    }

    const key = video && video.consumer && video.consumer.originVideoKey;
    return key ? 'https://sns-video-bd.xhscdn.com/' + key : '';
  };

  if (host.indexOf('xiaohongshu.com') >= 0 || host.indexOf('rednote.com') >= 0) {
    out.platform = 'xiaohongshu';

    const m = location.pathname.match(/\/(?:explore|discovery\/item)\/([0-9a-fA-F]+)/);
    const noteId = m ? m[1] : '';

    let note = null;
    const state = window.__INITIAL_STATE__;
    const map = state && state.note && state.note.noteDetailMap;
    if (map) {
      if (noteId && map[noteId] && map[noteId].note) {
        note = map[noteId].note;
      } else {
        // 页面上的 id 和 URL 里的对不上时（比如从信息流点进来的），取第一个有数据的
        for (const k in map) {
          if (map[k] && map[k].note) {
            note = map[k].note;
            break;
          }
        }
      }
    }

    if (note) {
      out.title = note.title || '';
      out.extra = note.desc || '';
      out.author = (note.user && (note.user.nickname || note.user.nickName)) || '';
      out.media_url = pickStreamUrl(note);
    }
    // 拿不到就把 title 留空 —— 让本地服务按 URL 再试一次，而不是在这里编一个
  } else if (host.indexOf('bilibili.com') >= 0) {
    out.platform = 'bilibili';
    const state = window.__INITIAL_STATE__;
    const vd = state && (state.videoData || (state.videoInfo && state.videoInfo.videoData));
    if (vd) {
      out.title = vd.title || '';
      out.author = (vd.owner && vd.owner.name) || '';
    }
  } else if (host.indexOf('youtube.com') >= 0) {
    out.platform = 'youtube';
    const h1 = document.querySelector('h1.ytd-watch-metadata, h1.style-scope.ytd-watch-metadata');
    if (h1) out.title = h1.textContent.trim();
    const ch = document.querySelector('ytd-channel-name a, #owner #channel-name a');
    if (ch) out.author = ch.textContent.trim();
  }

  if (!out.title) {
    const t = document.title || '';
    // 去掉站点后缀，B站 和 YouTube 都会往标题后面缀东西
    out.title = t.replace(/\s*[-_|]\s*(bilibili|哔哩哔哩|YouTube).*$/i, '').trim();
  }

  return out;
}
