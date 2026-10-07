/**
 * 扩展的界面逻辑。
 *
 * 扩展本身不做任何解析工作 —— 它只负责两件事：
 *   1. 在页面里（主世界）把媒体地址和元信息读出来
 *   2. 丢给本机运行的 video2text 服务，然后展示结果
 *
 * 转写跑在本地服务里（那是 Python + Whisper/FunASR，扩展装不下），
 * 所以任务由服务端持有。这意味着**关掉这个弹窗不会中断任务** ——
 * job id 存在 storage 里，重新打开会接着显示。
 */

const SERVICE = 'http://127.0.0.1:8756';
const JOB_KEY = 'lastJobId';
const POLL_MS = 600;

const $ = (id) => document.getElementById(id);

let serviceUp = false;
let currentJob = null;

// ---------- 服务健康检查 ----------

async function checkService() {
  try {
    const r = await fetch(`${SERVICE}/api/engines`, { cache: 'no-store' });
    if (!r.ok) throw new Error(r.status);
    const data = await r.json();
    serviceUp = true;
    setStatus(true, '服务已连接');

    const sel = $('engine');
    sel.innerHTML = '';
    for (const e of data.engines) {
      const o = document.createElement('option');
      o.value = e.name;
      let label = e.display;
      if (!e.ready) label += '（未装）';
      else if (e.model_cached === false) label += '（模型待下载）';
      o.textContent = label;
      o.disabled = !e.ready;
      sel.appendChild(o);
    }
    // 默认选模型已经在本地的那个 —— 否则用户点了才发现要下 1.6 GB
    const first = data.engines.find((e) => e.ready && e.model_cached)
               || data.engines.find((e) => e.ready);
    if (first) sel.value = first.name;
    return true;
  } catch (e) {
    serviceUp = false;
    setStatus(false, '服务未运行');
    showBanner(
      'warn',
      '连不上本地服务。先在项目目录双击 <code>run.command</code> 把它启动起来，然后重开这个窗口。'
    );
    return false;
  }
}

function setStatus(up, text) {
  const el = $('status');
  el.className = 'dot ' + (up ? 'up' : 'down');
  $('status-text').textContent = text;
}

function showBanner(kind, html) {
  const b = $('banner');
  b.className = 'banner ' + kind;
  b.innerHTML = html;
}

function clearBanner() {
  $('banner').className = '';
  $('banner').innerHTML = '';
}

// ---------- 读取页面 ----------

async function readPage() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) throw new Error('拿不到当前标签页');

  // world: 'MAIN' 是关键 —— content script 默认跑在隔离世界里，
  // 读不到页面的 JS 变量（小红书的 __INITIAL_STATE__ 就在那里面）
  const [result] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    world: 'MAIN',
    func: extractPageData
  });
  return result && result.result ? result.result : null;
}

const PLATFORM_NAMES = {
  bilibili: 'B站',
  xiaohongshu: '小红书',
  youtube: 'YouTube'
};

function renderPage(info) {
  const name = PLATFORM_NAMES[info.platform];
  const badge = $('platform');

  if (!name) {
    badge.textContent = '不支持的页面';
    badge.className = 'badge';
    $('page-title').textContent = '这个页面不是 B站 / 小红书 / YouTube';
    $('page-hint').textContent = '';
    $('go').disabled = true;
    return;
  }

  badge.textContent = name;
  badge.className = 'badge plat';

  $('page-title').textContent = info.title || '(没读到标题，不影响提取)';

  const bits = [];
  if (info.author) bits.push(info.author);
  if (info.media_url) bits.push('已取到媒体直链');
  $('page-hint').textContent = bits.join(' · ');

  $('go').disabled = false;
}

// ---------- 提交任务 ----------

async function start() {
  if (!serviceUp) {
    if (!(await checkService())) return;
  }

  $('go').disabled = true;
  clearBanner();
  $('result').classList.remove('show');
  $('progress').classList.add('show');
  $('logs').innerHTML = '';
  $('stage').textContent = '读取页面…';

  let info;
  try {
    info = await readPage();
    if (!info || !info.platform) throw new Error('这个页面不支持');
  } catch (e) {
    fail(`读不到页面信息：${e.message}`);
    return;
  }

  $('stage').textContent = '提交任务…';

  let jobId;
  try {
    const r = await fetch(`${SERVICE}/api/from-page`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...info,
        engine: $('engine').value,
        language: $('language').value
      })
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${r.status}`);
    }
    jobId = (await r.json()).job_id;
  } catch (e) {
    fail(`提交失败：${e.message}`);
    return;
  }

  // 记下来，弹窗被关掉再打开也能接着看
  await chrome.storage.local.set({ [JOB_KEY]: jobId });
  currentJob = jobId;
  poll(jobId);
}

function poll(jobId) {
  const timer = setInterval(async () => {
    let job;
    try {
      const r = await fetch(`${SERVICE}/api/job/${jobId}`, { cache: 'no-store' });
      if (!r.ok) throw new Error('任务丢失');
      job = await r.json();
    } catch (e) {
      clearInterval(timer);
      fail(`轮询失败：${e.message}`);
      return;
    }

    $('stage').textContent = job.stage || '处理中…';
    const box = $('logs');
    box.innerHTML = '';
    for (const line of job.logs || []) {
      const d = document.createElement('div');
      d.textContent = line;
      box.appendChild(d);
    }
    box.scrollTop = box.scrollHeight;

    if (job.status === 'done') {
      clearInterval(timer);
      render(job);
    } else if (job.status === 'error') {
      clearInterval(timer);
      fail(job.error);
    }
  }, POLL_MS);
}

function fail(message) {
  $('progress').classList.remove('show');
  $('go').disabled = false;
  showBanner('err', String(message).replace(/\n/g, '<br>'));
}

function render(job) {
  const r = job.result;
  $('progress').classList.remove('show');
  $('go').disabled = false;

  const isSub = r.source === 'subtitle';
  const badge = $('r-source');
  badge.className = 'badge ' + (isSub ? 'subtitle' : 'asr');
  badge.textContent = isSub ? '来自字幕' : '本地转写';

  const bits = [];
  if (r.count) bits.push(`${r.count} 句`);
  if (r.duration) bits.push(`${Math.round(r.duration / 60)} 分钟`);
  $('r-meta').textContent = bits.join(' · ');

  $('r-text').textContent = r.text;

  const box = $('r-downloads');
  box.innerHTML = '';
  for (const f of r.formats) {
    const b = document.createElement('button');
    b.className = 'ghost';
    b.textContent = `${f.label} .${f.suffix}`;
    b.onclick = () => {
      chrome.downloads
        ? chrome.downloads.download({ url: `${SERVICE}/api/download/${job.id}/${f.key}` })
        : window.open(`${SERVICE}/api/download/${job.id}/${f.key}`);
    };
    box.appendChild(b);
  }

  $('result').classList.add('show');
}

// ---------- 启动 ----------

async function init() {
  const up = await checkService();

  // 上次没看完的任务接着显示
  const { [JOB_KEY]: lastId } = await chrome.storage.local.get(JOB_KEY);
  if (up && lastId) {
    try {
      const r = await fetch(`${SERVICE}/api/job/${lastId}`, { cache: 'no-store' });
      if (r.ok) {
        const job = await r.json();
        currentJob = lastId;
        if (job.status === 'running') {
          $('progress').classList.add('show');
          poll(lastId);
          return;
        }
        if (job.status === 'done') {
          render(job);
          return;
        }
      }
    } catch (e) {
      /* 拿不到就算了，往下走正常流程 */
    }
  }

  if (!up) return;

  try {
    renderPage(await readPage());
  } catch (e) {
    $('platform').textContent = '读不到页面';
    $('page-title').textContent = e.message;
    $('go').disabled = true;
  }
}

$('go').onclick = start;
init();
