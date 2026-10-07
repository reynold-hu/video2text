/**
 * extractPageData 的测试。
 *
 * 用 node 直接跑：  node test/extract.test.js
 *
 * 这个函数有两个容易出错的地方，所以值得单独测：
 *   1. 它会被序列化送进页面执行，引用任何外部变量都会在今天没问题、明天报
 *      ReferenceError。这里让它在只有几个浏览器全局的沙箱里跑，一引用外部就炸。
 *   2. 小红书的 __INITIAL_STATE__ 结构是嵌套的、且不同入口拿到的 key 不一定一致，
 *      取不到就该老实返回空，交给本地服务兜底，而不是编一个出来。
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const source = fs.readFileSync(path.join(__dirname, '..', 'src', 'extract.js'), 'utf8');

/** 在只有浏览器全局的沙箱里跑一遍，确认没有外部依赖。 */
function run(globals) {
  const sandbox = {
    location: { href: 'https://example.com/', hostname: 'example.com', pathname: '/' },
    document: { title: '', querySelector: () => null },
    ...globals
  };
  sandbox.window = sandbox;
  const ctx = vm.createContext(sandbox);
  vm.runInContext(source, ctx);
  return vm.runInContext('extractPageData()', ctx);
}

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed++;
    console.log(`  ok  ${name}`);
  } catch (e) {
    console.error(`  FAIL ${name}\n       ${e.message}`);
    process.exitCode = 1;
  }
}

// ---------- 自包含性 ----------

test('不引用任何外部变量', () => {
  const out = run({});
  assert.strictEqual(typeof out, 'object');
});

// ---------- 小红书 ----------

const XHS_NOTE_ID = '6ac3474a000000000202a171';

function xhsSandbox(note, { keyAs = XHS_NOTE_ID } = {}) {
  return {
    location: {
      href: `https://www.xiaohongshu.com/explore/${XHS_NOTE_ID}?xsec_token=ABC123`,
      hostname: 'www.xiaohongshu.com',
      pathname: `/explore/${XHS_NOTE_ID}`
    },
    document: { title: '', querySelector: () => null },
    __INITIAL_STATE__: { note: { noteDetailMap: { [keyAs]: { note } } } }
  };
}

const FULL_NOTE = {
  title: 'ESP32-C3开发板帮你拦截广告',
  desc: '正文文案内容',
  user: { nickname: '某博主' },
  video: {
    media: {
      stream: {
        h264: [{ masterUrl: 'https://sns-video-bd.xhscdn.com/h264.mp4', backupUrls: ['https://backup.mp4'] }],
        h265: [{ masterUrl: 'https://sns-video-bd.xhscdn.com/h265.mp4' }]
      }
    },
    consumer: { originVideoKey: 'origin/key.mp4' }
  }
};

test('小红书：提取标题/正文/作者/媒体地址', () => {
  const out = run(xhsSandbox(FULL_NOTE));
  assert.strictEqual(out.platform, 'xiaohongshu');
  assert.strictEqual(out.title, 'ESP32-C3开发板帮你拦截广告');
  assert.strictEqual(out.extra, '正文文案内容');
  assert.strictEqual(out.author, '某博主');
  assert.strictEqual(out.media_url, 'https://sns-video-bd.xhscdn.com/h264.mp4');
});

test('小红书：优先 h264', () => {
  const out = run(xhsSandbox(FULL_NOTE));
  assert.ok(out.media_url.includes('h264'), out.media_url);
});

test('小红书：没有 h264 时退回 h265', () => {
  const note = JSON.parse(JSON.stringify(FULL_NOTE));
  delete note.video.media.stream.h264;
  const out = run(xhsSandbox(note));
  assert.ok(out.media_url.includes('h265'), out.media_url);
});

test('小红书：masterUrl 缺失时用 backupUrls', () => {
  const note = JSON.parse(JSON.stringify(FULL_NOTE));
  delete note.video.media.stream.h264[0].masterUrl;
  const out = run(xhsSandbox(note));
  assert.strictEqual(out.media_url, 'https://backup.mp4');
});

test('小红书：stream 缺失时用 originVideoKey 拼', () => {
  const note = JSON.parse(JSON.stringify(FULL_NOTE));
  delete note.video.media.stream;
  const out = run(xhsSandbox(note));
  assert.strictEqual(out.media_url, 'https://sns-video-bd.xhscdn.com/origin/key.mp4');
});

test('小红书：URL 里的 id 对不上时取第一个有数据的笔记', () => {
  // 从信息流点进来时，页面上的 id 和地址栏里的可能不一致
  const out = run(xhsSandbox(FULL_NOTE, { keyAs: 'someotherid' }));
  assert.strictEqual(out.title, 'ESP32-C3开发板帮你拦截广告');
});

test('小红书：拿不到笔记数据时全部留空，交给服务端兜底', () => {
  // 这正是 token 过期时页面返回的降级状态 —— 不能编造内容
  const out = run({
    location: xhsSandbox(FULL_NOTE).location,
    document: { title: '', querySelector: () => null },
    __INITIAL_STATE__: { note: { noteDetailMap: {} } }
  });
  assert.strictEqual(out.platform, 'xiaohongshu');
  assert.strictEqual(out.title, '');
  assert.strictEqual(out.media_url, '');
});

test('小红书：完全没有 __INITIAL_STATE__ 也不崩', () => {
  const out = run({
    location: xhsSandbox(FULL_NOTE).location,
    document: { title: '', querySelector: () => null }
  });
  assert.strictEqual(out.platform, 'xiaohongshu');
  assert.strictEqual(out.media_url, '');
});

test('小红书：保留带 xsec_token 的完整地址', () => {
  const out = run(xhsSandbox(FULL_NOTE));
  assert.ok(out.url.includes('xsec_token='), out.url);
});

// ---------- B站 ----------

test('B站：从 __INITIAL_STATE__.videoData 取标题和作者', () => {
  const out = run({
    location: { href: 'https://www.bilibili.com/video/BV1xx411c7mD', hostname: 'www.bilibili.com', pathname: '/video/BV1xx411c7mD' },
    document: { title: 'x', querySelector: () => null },
    __INITIAL_STATE__: { videoData: { title: '视频标题', owner: { name: 'UP主' } } }
  });
  assert.strictEqual(out.platform, 'bilibili');
  assert.strictEqual(out.title, '视频标题');
  assert.strictEqual(out.author, 'UP主');
  // B站 不需要直链，走官方字幕接口更准
  assert.strictEqual(out.media_url, '');
});

// ---------- YouTube ----------

test('YouTube：从 DOM 取标题和频道名', () => {
  const out = run({
    location: { href: 'https://www.youtube.com/watch?v=x', hostname: 'www.youtube.com', pathname: '/watch' },
    document: {
      title: 'fallback',
      querySelector: (sel) => (sel.includes('h1') ? { textContent: '  视频标题  ' } : { textContent: '频道名' })
    }
  });
  assert.strictEqual(out.platform, 'youtube');
  assert.strictEqual(out.title, '视频标题');
  assert.strictEqual(out.author, '频道名');
});

// ---------- 兜底 ----------

test('未知站点：platform 为空，标题回退到 document.title 并去掉站点后缀', () => {
  const out = run({
    location: { href: 'https://example.com/x', hostname: 'example.com', pathname: '/x' },
    document: { title: '某个标题 - 哔哩哔哩', querySelector: () => null }
  });
  assert.strictEqual(out.platform, '');
  assert.strictEqual(out.title, '某个标题');
});

test('返回的对象可 JSON 序列化', () => {
  // executeScript 的返回值要跨进程传回，带函数或循环引用会失败
  const out = run(xhsSandbox(FULL_NOTE));
  assert.doesNotThrow(() => JSON.parse(JSON.stringify(out)));
});

console.log(`\n${passed} passed`);
