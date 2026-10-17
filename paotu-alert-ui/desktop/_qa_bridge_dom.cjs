// 自检用：不靠真鼠标，直接验「页面上那几个控件有没有把调用打到桥上」。
//   NODE_PATH=<node工作区>/node_modules node _qa_dom.cjs
// 覆盖：#view=map 的「收回控制台」按钮 / D 键，#view=full 的「分离地图」按钮 / D 键，
//       #view=panel 的「收回地图」按钮，以及输入框里的键盘守卫。
const { chromium } = require('playwright');

const FILE = 'file:///D:/wbworkspace/2026-10-08-17-29-12/fangkuai-chuanshuo/paotu-alert-ui/index.html';
const ok = [];
const bad = [];

const STUB = () => {
  window.__calls = [];
  window.pywebview = {
    api: new Proxy({}, {
      get: (_, k) => (...a) => { window.__calls.push(String(k)); return { ok: true }; },
    }),
  };
  window.PaoTuAlertUI.setAdapter({
    onDetachMap: () => { window.pywebview.api.detach_map(); },
    onAttachMap: () => { window.pywebview.api.attach_map(); },
    setMode: () => {}, applySettings: () => {}, onScan: () => {}, onPause: () => {},
    isMarkOn: () => true,
  });
};

(async () => {
  const browser = await chromium.launch({ channel: 'msedge' });

  async function run(name, hash, action, expect) {
    const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
    const errs = [];
    page.on('pageerror', e => errs.push(String(e)));
    await page.goto(FILE + hash);
    await page.waitForFunction(() => !!window.PaoTuAlertUI, null, { timeout: 8000 });
    await page.evaluate(STUB);
    await action(page);
    const calls = await page.evaluate(() => window.__calls);
    const got = calls[calls.length - 1] || '(无)';
    const pass = got === expect && errs.length === 0;
    (pass ? ok : bad).push(`${pass ? 'PASS' : 'FAIL'}  ${name}  → 桥收到 ${got}（期望 ${expect}）`
      + (errs.length ? `  页面报错: ${errs}` : ''));
    await page.close();
  }

  const click = id => async p => { await p.click(id); await p.waitForTimeout(250); };
  const key = k => async p => { await p.keyboard.press(k); await p.waitForTimeout(250); };

  await run('view=map   点「⤢ 收回控制台」', '#view=map', click('#btnDetachBack'), 'attach_map');
  await run('view=map   按 D',              '#view=map', key('d'),                   'attach_map');
  await run('view=full  点「⧉ 分离地图」',   '#view=full', click('#btnDetach'),      'detach_map');
  await run('view=full  按 D',              '#view=full', key('d'),                  'detach_map');
  await run('view=panel 点「⤢ 收回地图」',  '#view=panel', click('#btnAttach'),     'attach_map');

  // 键盘守卫：输入框里敲 d 不该触发分离
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  await page.goto(FILE + '#view=full');
  await page.waitForFunction(() => !!window.PaoTuAlertUI, null, { timeout: 8000 });
  await page.evaluate(STUB);
  await page.evaluate(() => {
    const i = document.createElement('input');
    i.id = '__t';
    document.body.appendChild(i);
    i.focus();
  });
  await page.keyboard.type('ddd');
  await page.waitForTimeout(200);
  const guarded = await page.evaluate(() => window.__calls.length);
  (guarded === 0 ? ok : bad).push(
    `${guarded === 0 ? 'PASS' : 'FAIL'}  输入框里敲 d 不触发分离（键盘守卫）→ 桥收到 ${guarded} 次`);
  await page.close();

  await browser.close();
  console.log([...ok, ...bad].join('\n'));
  console.log(`\n通过 ${ok.length} / 失败 ${bad.length}`);
  process.exit(bad.length ? 1 : 0);
})();
