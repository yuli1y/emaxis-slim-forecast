const yen = new Intl.NumberFormat("ja-JP");
const pct = new Intl.NumberFormat("ja-JP", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const ids = {
  navDate: document.querySelector("#nav-date"),
  latestNav: document.querySelector("#latest-nav"),
  actualChange: document.querySelector("#actual-change"),
  forecast06: document.querySelector("#forecast-06"),
  change06: document.querySelector("#change-06"),
  forecast18: document.querySelector("#forecast-18"),
  change18: document.querySelector("#change-18"),
  acwiReturn: document.querySelector("#acwi-return"),
  fxReturn: document.querySelector("#fx-return"),
  asOf: document.querySelector("#as-of"),
  method: document.querySelector("#method"),
  error: document.querySelector("#error"),
  refresh: document.querySelector("#refresh"),
};

const API_PATH = "api/snapshot";

function signed(value) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${yen.format(value)}円`;
}

function setChange(node, value, percentValue) {
  node.textContent = `${signed(value)} / ${pct.format(percentValue)}`;
  node.classList.toggle("gain", value > 0);
  node.classList.toggle("loss", value < 0);
}

function setPercent(node, value) {
  node.textContent = pct.format(value);
  node.classList.toggle("gain", value > 0);
  node.classList.toggle("loss", value < 0);
}

function render(data) {
  ids.error.hidden = true;
  ids.navDate.textContent = data.fund.navDate;
  ids.latestNav.textContent = `${yen.format(data.fund.nav)}円`;
  setChange(ids.actualChange, data.fund.actualChange, data.fund.actualChangePct);

  for (const forecast of data.forecasts) {
    const isMorning = forecast.slot === "06:00";
    const valueNode = isMorning ? ids.forecast06 : ids.forecast18;
    const changeNode = isMorning ? ids.change06 : ids.change18;
    valueNode.textContent = `${yen.format(forecast.predictedNav)}円`;
    setChange(changeNode, forecast.change, forecast.changePct);
  }

  setPercent(ids.acwiReturn, data.market.acwi.return);
  setPercent(ids.fxReturn, data.market.usdJpy.return);
  ids.asOf.textContent = new Date(data.asOf).toLocaleString("ja-JP", {
    dateStyle: "short",
    timeStyle: "medium",
  });
  ids.method.textContent = data.method;

  document.querySelectorAll(".forecast").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.slot === data.currentSlot);
  });
}

async function load() {
  ids.refresh.disabled = true;
  try {
    ids.method.textContent = "データ取得中です。";
    const response = await fetch(API_PATH, { cache: "no-store" });
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
      throw new Error(
        "価格APIが見つかりません。python3 server.py で起動し、http://localhost:8765 を開いてください。GitHubのファイル表示やGitHub PagesだけではPython APIが動きません。"
      );
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "データを取得できませんでした。");
    render(data);
  } catch (error) {
    const offline =
      error instanceof TypeError
        ? "価格APIに接続できません。python3 server.py で起動し、http://localhost:8765 を開いてください。"
        : error.message;
    ids.method.textContent = "データを取得できませんでした。";
    ids.error.textContent = offline;
    ids.error.hidden = false;
  } finally {
    ids.refresh.disabled = false;
  }
}

ids.refresh.addEventListener("click", load);
load();
setInterval(load, 10 * 60 * 1000);
