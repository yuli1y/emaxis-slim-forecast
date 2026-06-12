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
  forecast10Label: document.querySelector("#forecast-10-label"),
  forecast18Label: document.querySelector("#forecast-18-label"),
  forecast10: document.querySelector("#forecast-10"),
  change10: document.querySelector("#change-10"),
  error10: document.querySelector("#error-10"),
  forecast18: document.querySelector("#forecast-18"),
  change18: document.querySelector("#change-18"),
  error18: document.querySelector("#error-18"),
  acwiReturn: document.querySelector("#acwi-return"),
  fxReturn: document.querySelector("#fx-return"),
  asOf: document.querySelector("#as-of"),
  method: document.querySelector("#method"),
  error: document.querySelector("#error"),
  refresh: document.querySelector("#refresh"),
  chartArea: document.querySelector("#chart-area"),
  chartLine: document.querySelector("#chart-line"),
  chartLatest: document.querySelector("#chart-latest"),
  chartRange: document.querySelector("#chart-range"),
};

const DATA_PATH = "data/snapshot.json";
const FALLBACK_ESTIMATED_ERROR_PCT = 0.01;

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

function setEstimateError(node, value) {
  if (!Number.isFinite(value)) {
    node.textContent = "";
    return;
  }
  node.textContent = `誤差目安 ±${yen.format(value)}円`;
}

function shortDate(dateText) {
  const parts = dateText.split("/");
  if (parts.length !== 3) return dateText;
  return `${Number(parts[1])}/${Number(parts[2])}`;
}

function nextBusinessDate(dateText) {
  const parts = dateText.split("/").map(Number);
  if (parts.length !== 3 || parts.some(Number.isNaN)) return "";
  const target = new Date(parts[0], parts[1] - 1, parts[2] + 1);
  while (target.getDay() === 0 || target.getDay() === 6) {
    target.setDate(target.getDate() + 1);
  }
  return `${target.getFullYear()}/${String(target.getMonth() + 1).padStart(2, "0")}/${String(
    target.getDate(),
  ).padStart(2, "0")}`;
}

function isNextForecastWindow(data) {
  const hour = new Date(data.asOf).getHours();
  return hour >= 23 || hour < 10 || data.currentSlot === "next";
}

function chartPath(points, width, height, pad) {
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  return points
    .map((point, index) => {
      const x = pad + (index / Math.max(points.length - 1, 1)) * (width - pad * 2);
      const y = pad + (1 - (point.value - min) / span) * (height - pad * 2);
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

function renderChart(data) {
  const history = (data.fund.history || []).filter((point) => Number.isFinite(point.value));
  const latest = history.at(-1) || { date: data.fund.navDate, value: data.fund.nav };

  ids.chartLatest.textContent = `${yen.format(Math.round(latest.value))}円`;
  ids.chartRange.textContent =
    history.length > 1 ? `${history[0].date} - ${history.at(-1).date}` : "履歴データ待ち";

  if (history.length < 2) {
    ids.chartLine.setAttribute("d", "");
    ids.chartArea.setAttribute("d", "");
    return;
  }

  const width = 640;
  const height = 180;
  const pad = 12;
  const line = chartPath(history, width, height, pad);
  const area = `${line} L${width - pad} ${height - pad} L${pad} ${height - pad} Z`;
  ids.chartLine.setAttribute("d", line);
  ids.chartArea.setAttribute("d", area);
}

function render(data) {
  ids.error.hidden = true;
  ids.navDate.textContent = `基準日 ${data.fund.navDate}`;
  const rawForecastDate = data.forecastDate || nextBusinessDate(data.fund.navDate);
  const forecastDate = rawForecastDate ? shortDate(rawForecastDate) : "";
  ids.forecast10Label.textContent = forecastDate ? `${forecastDate} 午前10時` : "午前10時";
  ids.forecast18Label.textContent = forecastDate ? `${forecastDate} 午後6時` : "午後6時";
  ids.latestNav.textContent = `${yen.format(data.fund.nav)}円`;
  setChange(ids.actualChange, data.fund.actualChange, data.fund.actualChangePct);
  renderChart(data);

  const nextForecastWindow = isNextForecastWindow(data);
  for (const forecast of data.forecasts) {
    const isMorning = forecast.slot === "10:00";
    const valueNode = isMorning ? ids.forecast10 : ids.forecast18;
    const changeNode = isMorning ? ids.change10 : ids.change18;
    const errorNode = isMorning ? ids.error10 : ids.error18;
    if (nextForecastWindow) {
      setPending(valueNode, changeNode, `${rawForecastDate} ${forecast.slot}更新後に表示します。`);
      setEstimateError(errorNode, null);
      continue;
    }
    if (forecast.status !== "ready") {
      setPending(valueNode, changeNode, forecast.message || "更新後に表示します。");
      setEstimateError(errorNode, null);
      continue;
    }
    valueNode.textContent = `${yen.format(forecast.predictedNav)}円`;
    setChange(changeNode, forecast.change, forecast.changePct);
    setEstimateError(
      errorNode,
      forecast.estimatedErrorYen || Math.round(forecast.predictedNav * FALLBACK_ESTIMATED_ERROR_PCT),
    );
  }

  setPercent(ids.acwiReturn, data.market.acwi.return);
  setPercent(ids.fxReturn, data.market.usdJpy.return);
  ids.asOf.textContent = new Date(data.asOf).toLocaleString("ja-JP", {
    dateStyle: "short",
    timeStyle: "medium",
  });
  ids.method.textContent = data.method;

  document.querySelectorAll(".forecast").forEach((panel) => {
    panel.classList.toggle("active", !nextForecastWindow && panel.dataset.slot === data.currentSlot);
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
