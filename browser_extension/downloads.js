importScripts("sites.js");
const minute = 60000;
const queue = chrome.storage.local;
const session = chrome.storage.session;
let tail = Promise.resolve();
function serial(work) {
  tail = tail.then(work).catch(error => console.warn("다운로드 기록", error.message));
  return tail;
}
function urlKey(value) {
  try { const u = new URL(value); u.hash = ""; return u.href; } catch { return ""; }
}
async function recent() {
  const {observations = []} = await session.get("observations");
  return observations.filter(row => Date.now() - row.time < 2 * minute);
}
async function remember(snapshot, tab, target, time, network = false) {
  if (!await connected(httpsOrigin(snapshot?.page))) return;
  const rows = await recent();
  rows.push({tab, target: urlKey(target), page: urlKey(snapshot.page), pageTitle: snapshot.pageTitle,
    courseName: snapshot.courseName, time, network});
  await session.set({observations: rows.slice(-100)});
}
chrome.runtime.onMessage.addListener((message, sender) => {
  if (message.type === "course-click" && sender.tab && !sender.tab.incognito && httpsOrigin(sender.url)) {
    const time = Date.now();
    serial(() => remember({...message, page: sender.url}, sender.tab.id, message.target, time));
  }
});
// e-Class can start a download from a script or a POST with no attachment href on screen.
chrome.webRequest.onBeforeRequest.addListener(request => {
  if (request.tabId < 0 || !/\/file_download[^/]*\.acl$/i.test(new URL(request.url).pathname)) return;
  serial(async () => {
    const tab = await chrome.tabs.get(request.tabId);
    if (tab.incognito) return;
    const rows = await recent();
    const click = rows.slice().reverse().find(r => !r.network && r.tab === request.tabId &&
      Math.abs(request.timeStamp-r.time)<5000 && (r.target === urlKey(request.url) || !r.target));
    let snap = click;
    if (!snap) {
      const frame = request.parentFrameId >= 0 && ["sub_frame","main_frame"].includes(request.type)
        ? request.parentFrameId : Math.max(request.frameId, 0);
      snap = await chrome.tabs.sendMessage(request.tabId, {type:"course-snapshot"}, {frameId:frame}).catch(() => null);
    }
    await remember(snap, request.tabId, request.url, request.timeStamp, true);
  });
}, {urls:["https://*/*"]});

async function bind(item) {
  if (item.incognito) return null;
  const start = Date.parse(item.startTime);
  const targets = [urlKey(item.url), urlKey(item.finalUrl)].filter(Boolean);
  const ref = urlKey(item.referrer);
  const rows = (await recent()).filter(r => Math.abs(start-r.time)<minute);
  let matches = rows.filter(r => r.target && targets.includes(r.target));
  if (matches.length && ref && matches.some(r => r.page === ref)) matches = matches.filter(r => r.page === ref);
  if (!matches.length && ref && new URL(ref).pathname !== "/")
    matches = rows.filter(r => r.page === ref && !r.target && Math.abs(start-r.time)<5000);
  if (!matches.length) return null;
  const first = matches[0];
  const origin = httpsOrigin(first.page);
  if (!await connected(origin) || (ref && httpsOrigin(ref) !== origin)) return null;
  if (!matches.every(r => r.page === first.page && r.courseName === first.courseName && r.pageTitle === first.pageTitle)) return null;
  const page = new URL(first.page);
  const courseId = page.pathname.match(/\/courses\/(\d+)(?:\/|$)/i)?.[1] ||
    page.searchParams.get("course_id") || page.searchParams.get("courseid") ||
    (page.pathname.endsWith("/course/view.php") && page.searchParams.get("id")) || "";
  return {courseName:first.courseName, pageTitle:first.pageTitle, pageUrl:first.page, pageOrigin:origin,
    courseId:/^[\w.-]{1,100}$/.test(courseId) ? courseId : "", startTime:item.startTime};
}
async function processItem(item) {
  if (!item || item.incognito) return;
  const key = "download:" + item.id;
  let record = (await queue.get(key))[key];
  if (record?.startTime !== item.startTime) record = null;
  if (!record) {
    record = await bind(item);
    if (!record) return;
    await queue.set({[key]:record});
  }
  if (item.state === "interrupted") {
    if (!item.canResume) await queue.remove(key);
    return;
  }
  if (item.state !== "complete" || !item.filename || !item.endTime) return;
  if (!await connected(record.pageOrigin)) { await queue.remove(key); return; }
  const result = await chrome.runtime.sendNativeMessage(HOST,{
    type:"download", ...record, path:item.filename,
    endTime:item.endTime, size:item.fileSize
  });
  if (result.ok || result.skip) await queue.remove(key);
  if (result.ok) await queue.set({lastSaved:{time:Date.now(),course:record.courseName||record.pageTitle}});
}
chrome.downloads.onCreated.addListener(item => serial(() => processItem(item)));
chrome.downloads.onChanged.addListener(delta => {
  if (delta.state || delta.filename) serial(async () => processItem((await chrome.downloads.search({id:delta.id}))[0]));
});
async function retry() {
  for (const [key,record] of Object.entries(await queue.get(null))) {
    if (!key.startsWith("download:")) continue;
    const [item] = await chrome.downloads.search({id:Number(key.slice(9))});
    if (!item || item.startTime !== record.startTime) await queue.remove(key);
    else await processItem(item);
  }
}
chrome.alarms.onAlarm.addListener(a => { if (a.name === "retry") serial(retry); });
function schedule() {
  chrome.alarms.create("retry", {periodInMinutes:2});
  serial(retry);
}
chrome.runtime.onStartup.addListener(schedule);
chrome.runtime.onInstalled.addListener(schedule);
