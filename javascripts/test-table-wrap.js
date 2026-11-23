/* テスト表のコードを、意味の切れ目（= _ / - . @ のあと）で折り返せるようにする。
 * 印刷と PDF でも使う。すでに wbr があるときは触らない。
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

  function run() {
    document.querySelectorAll(".test-cases code, .test-views code").forEach(wrapCode);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run);
  } else {
    run();
  }
})();
