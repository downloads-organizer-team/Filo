async function show() {
  const byId = id => document.getElementById(id);
  try {
    const reply = await chrome.runtime.sendNativeMessage("kr.ac.course_downloads",{type:"ping"});
    byId("bridge").textContent = reply.ok ? "파일 정리 앱 연결됨" : "앱에서 ‘브라우저 출처 연결’을 눌러 주세요.";
  } catch {
    byId("bridge").textContent = "앱에서 ‘브라우저 출처 연결’을 눌러 주세요.";
  }
  const [tab] = await chrome.tabs.query({active:true,currentWindow:true});
  const origin = httpsOrigin(tab?.url);
  if (origin && !tab.incognito && !await connected(origin)) {
    byId("course").textContent = "현재 사이트 · " + origin;
    const connect = byId("connect");
    connect.hidden = false;
    connect.onclick = async () => {
      try {
        const granted = await chrome.permissions.request({origins:[origin + "/*"]});
        if (!granted) { byId("course").textContent = "사이트 연결을 취소했습니다."; return; }
        await enableSite(origin);
        connect.hidden = true;
        byId("course").textContent = "연결됨 · 이 페이지를 새로고침하세요.";
      } catch { byId("course").textContent = "연결 실패 · 앱의 ‘브라우저 출처 연결’을 확인하세요."; }
    };
  } else if (origin && !tab.incognito) {
    const page = await chrome.tabs.sendMessage(tab.id,{type:"course-snapshot"},{frameId:0}).catch(() => null);
    byId("course").textContent = page ? "현재 페이지 · " + (page.pageTitle || origin) + (page.courseName ? " · 강좌 " + page.courseName : "") : "연결됨 · 이 페이지를 새로고침하세요.";
  } else { byId("course").textContent = "출처를 기록할 HTTPS 웹페이지에서 여세요."; }
  const {lastSaved} = await chrome.storage.local.get("lastSaved");
  if (lastSaved) byId("last").textContent = "최근 기록 · " + (lastSaved.course || "페이지 출처 저장") + " · " + new Date(lastSaved.time).toLocaleString("ko-KR");
}
show();
