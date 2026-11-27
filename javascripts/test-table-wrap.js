/* テスト表のコードを、意味の切れ目（= _ / - . @ のあと）で折り返せるようにする。
 * あわせて、テストケース表（.test-cases）の同じ「観点」が続く行を縦に結合して見せる。
 * 印刷と PDF でも使う。すでに処理済みの要素は触らない。
 */
(() => {
  const SPLIT = /(?<=[=/_@.\-])(?=[^=/_@.\-]{2})/;

  function wrapCode(code) {
    if (code.dataset.wrapDone === "1") return;
    if (code.querySelector("wbr")) {
      code.dataset.wrapDone = "1";
      return;
    }
    const text = code.textContent;
    const parts = text.split(SPLIT);
    if (parts.length < 2) return;
    const nodes = [];
    parts.forEach((part, i) => {
      if (i) nodes.push(document.createElement("wbr"));
      nodes.push(document.createTextNode(part));
    });
    code.replaceChildren(...nodes);
    code.dataset.wrapDone = "1";
  }

  function mergeViewColumn(table) {
    if (table.dataset.mergeDone === "1") return;
    const tbody = table.tBodies[0];
    if (!tbody) return;
    const rows = Array.from(tbody.rows);
    if (rows.length < 2) return;

    // 列番号を固定してから結合する（削除後に :nth-child がずれないようにする）
    rows.forEach((row) => {
      Array.from(row.cells).forEach((cell, idx) => {
        cell.dataset.col = String(idx + 1);
      });
    });

    const colIndex = 1; // 2列目：観点
    let anchor = null;
    let anchorText = "";
    let span = 1;

    rows.forEach((row) => {
      const cell = row.cells[colIndex];
      if (!cell) {
        anchor = null;
        anchorText = "";
        span = 1;
        return;
      }
      const text = cell.textContent.replace(/\s+/g, " ").trim();
      if (anchor && text !== "" && text === anchorText) {
        span += 1;
        anchor.rowSpan = span;
        cell.remove();
      } else {
        anchor = cell;
        anchorText = text;
        span = 1;
      }
    });

    tbody.dataset.merged = "1";
    table.dataset.mergeDone = "1";
  }

  function run() {
    document.querySelectorAll(".test-cases code, .test-views code").forEach(wrapCode);
    document.querySelectorAll(".test-cases table").forEach(mergeViewColumn);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
