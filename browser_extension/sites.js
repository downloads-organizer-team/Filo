const DEFAULT_SITE = "https://clc.chosun.ac.kr";
const HOST = "kr.ac.course_downloads";

function httpsOrigin(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" ? parsed.origin : "";
  } catch { return ""; }
}
async function siteScript(origin) {
  const scripts = await chrome.scripting.getRegisteredContentScripts();
  return scripts.find(script => script.matches.includes(origin + "/*"));
}
async function connected(origin) {
  if (!origin || origin !== httpsOrigin(origin)) return false;
  if (origin !== DEFAULT_SITE && !await siteScript(origin)) return false;
  return chrome.permissions.contains({origins:[origin + "/*"]});
}
async function enableSite(origin) {
  const result = await chrome.runtime.sendNativeMessage(HOST,{type:"enable-site",pageOrigin:origin});
  if (!result.ok) throw Error("앱에서 ‘브라우저 출처 연결’을 누른 뒤 다시 시도하세요.");
  if (await siteScript(origin)) return;
  const digest = await crypto.subtle.digest("SHA-256",new TextEncoder().encode(origin));
  const id = "site-" + Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2,"0")).join("");
  await chrome.scripting.registerContentScripts([{id,matches:[origin+"/*"],js:["course.js"],
    allFrames:true,runAt:"document_start",persistAcrossSessions:true}]);
}
