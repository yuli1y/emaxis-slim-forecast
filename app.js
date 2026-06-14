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
  forecast6Label: document.querySelector("#forecast-6-label"),
  forecast18Label: document.querySelector("#forecast-18-label"),
  forecast6: document.querySelector("#forecast-6"),
  change6: document.querySelector("#change-6"),
  time6: document.querySelector("#time-6"),
  forecast18: document.querySelector("#forecast-18"),
  change18: document.querySelector("#change-18"),
  time18: document.querySelector("#time-18"),
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
  const d = new Date(data.asOf);
  const timeVal = d.getHours() * 60 + d.getMinutes();
  return timeVal >= 1380 || timeVal < 360 || data.currentSlot === "next";
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
  ids.forecast6Label.textContent = forecastDate ? `昼の予想 (${forecastDate})` : "昼の予想 (6:00〜18:00)";
  ids.forecast18Label.textContent = forecastDate ? `夜の予想 (${forecastDate})` : "夜の予想 (18:00〜23:00)";
  ids.latestNav.textContent = `${yen.format(data.fund.nav)}円`;
  setChange(ids.actualChange, data.fund.actualChange, data.fund.actualChangePct);
  renderChart(data);

  const nextForecastWindow = isNextForecastWindow(data);
  for (const forecast of data.forecasts) {
    const isMorning = forecast.slot === "06:00";
    const valueNode = isMorning ? ids.forecast6 : ids.forecast18;
    const changeNode = isMorning ? ids.change6 : ids.change18;
    const timeNode = isMorning ? ids.time6 : ids.time18;

    if (nextForecastWindow) {
      setPending(valueNode, changeNode, `${rawForecastDate} ${forecast.slot}更新後に表示します。`);
      timeNode.textContent = "";
      continue;
    }
    if (forecast.status !== "ready") {
      setPending(valueNode, changeNode, forecast.message || "更新後に表示します。");
      timeNode.textContent = "";
      continue;
    }
    valueNode.textContent = `${yen.format(forecast.predictedNav)}円`;
    setChange(changeNode, forecast.change, forecast.changePct);

    if (forecast.asOf) {
      const d = new Date(forecast.asOf);
      timeNode.textContent = `${d.getHours()}:${String(d.getMinutes()).padStart(2, "0")} 更新`;
    } else {
      timeNode.textContent = "";
    }
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

const triggerBtn = document.querySelector("#trigger-workflow");
if (triggerBtn) {
  triggerBtn.addEventListener("click", async () => {
    let token = localStorage.getItem("github_pat");
    if (!token) {
      token = prompt(
        "GitHubの個人用アクセストークン(PAT)を入力してください。\n" +
        "※トークンはあなたのブラウザ内(localStorage)にのみ安全に保存されます。\n" +
        "※手順：Settings ➔ Developer settings ➔ Personal access tokens (classic) ➔ repo & workflow 権限をチェックして生成してください。"
      );
      if (!token) return;
      token = token.trim();
      localStorage.setItem("github_pat", token);
    }

    triggerBtn.disabled = true;
    triggerBtn.textContent = "更新中...";
    try {
      const res = await fetch("https://api.github.com/repos/yuli1y/emaxis-slim-forecast/actions/workflows/update-snapshot.yml/dispatches", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Accept": "application/vnd.github+json",
        },
        body: JSON.stringify({ ref: "main" })
      });
      if (res.status === 204) {
        alert("更新リクエストを送信しました！\nGitHub Actionsが起動します。約30秒後に右上の「↻」ボタンを押して再読み込みしてください。");
      } else {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.message || `エラーコード: ${res.status}`);
      }
    } catch (e) {
      alert(`エラーが発生しました:\n${e.message}\nトークンが無効である可能性があります。再入力してください。`);
      localStorage.removeItem("github_pat");
    } finally {
      triggerBtn.disabled = false;
      triggerBtn.textContent = "今すぐ更新";
    }
  });
}
