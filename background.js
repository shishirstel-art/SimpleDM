const API = "http://127.0.0.1:9614/add";

async function send(url, referrer) {
  let cookie = "";
  try {
    const cs = await chrome.cookies.getAll({ url });
    cookie = cs.map(c => c.name + "=" + c.value).join("; ");
  } catch (e) {}
  try {
    const r = await fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-SimpleDM": "1" },
      body: JSON.stringify({ url, referrer, cookie })
    });
    return r.ok;
  } catch (e) {
    return false; // app not running -> let the browser download normally
  }
}

// Catch every browser download and hand it to the app
chrome.downloads.onCreated.addListener(async (item) => {
  const url = item.finalUrl || item.url;
  if (!/^(https?:|magnet:)/i.test(url)) return;
  if (await send(url, item.referrer)) {
    chrome.downloads.cancel(item.id, () => chrome.downloads.erase({ id: item.id }));
  }
});

// Right-click a link -> "Download with SimpleDM" (also works for magnet links)
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "simpledm", title: "Download with SimpleDM", contexts: ["link"]
  });
});
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId === "simpledm") send(info.linkUrl, tab && tab.url);
});
