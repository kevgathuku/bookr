// Persist lesson checkboxes per page in localStorage; show x/y progress.
(function () {
  var key = "teach:" + location.pathname;
  var boxes = Array.prototype.slice.call(document.querySelectorAll("ul.check input[type=checkbox]"));
  if (!boxes.length) return;
  var state = {};
  try { state = JSON.parse(localStorage.getItem(key) || "{}"); } catch (e) { state = {}; }
  var bar = document.querySelector("[data-progress]");
  function render() {
    var n = 0;
    boxes.forEach(function (b) {
      var on = !!state[b.dataset.id];
      b.checked = on;
      b.closest("li").classList.toggle("done", on);
      if (on) n++;
    });
    if (bar) bar.textContent = n + " of " + boxes.length + " deliverables done";
  }
  boxes.forEach(function (b) {
    b.addEventListener("change", function () {
      state[b.dataset.id] = b.checked;
      try { localStorage.setItem(key, JSON.stringify(state)); } catch (e) {}
      render();
    });
  });
  render();
})();
