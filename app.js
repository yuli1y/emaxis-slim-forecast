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

const DATA_PATH = "data/snapshot.json";

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

function setPending(valueNode, changeNode, message) {
  valueNode.textContent = "未更新";
  changeNode.textContent = message;
  changeNode.classList.remove("gain", "loss");
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
    if (forecast.status !== "ready") {
      setPending(valueNode, changeNode, forecast.message || "更新後に表示します。");
      continue;
    }
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
    const response = await fetch(`${DATA_PATH}?t=${Date.now()}`, { cache: "no-store" });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "データを取得できませんでした。");
    render(data);
  } catch (error) {
    ids.method.textContent = "データを取得できませんでした。";
    ids.error.textContent =
      "data/snapshot.jsonを読み込めません。GitHub Pagesまたはローカルの簡易HTTPサーバー経由で開いてください。";
    ids.error.hidden = false;
  } finally {
    ids.refresh.disabled = false;
  }
}

ids.refresh.addEventListener("click", load);
load();
