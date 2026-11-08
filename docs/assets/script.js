/* GitHub Pages site interactions:
   - pause the diagram's SMIL animation until it scrolls into view,
   - highlight the diagram node matching the clicked step card.
*/
(function () {
  var svg = document.getElementById("flow-svg");
  var box = document.querySelector(".diagram-box");

  // Start paused; play when the diagram is visible.
  if (svg && svg.pauseAnimations) {
    try {
      svg.pauseAnimations();
    } catch (e) {
      /* older browsers: animations just play */
    }
    var io = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            try {
              svg.unpauseAnimations();
            } catch (e) {}
            io.disconnect();
          }
        });
      },
      { threshold: 0.3 }
    );
    if (box) io.observe(box);
  }

  // Step cards <-> diagram nodes.
  var steps = document.querySelectorAll("#steps .step");
  var detail = document.getElementById("step-detail");

  function clearHighlight() {
    document.querySelectorAll("#flow-svg g.node").forEach(function (g) {
      g.classList.remove("hl");
    });
    steps.forEach(function (s) {
      s.classList.remove("active");
    });
  }

  steps.forEach(function (step) {
    step.addEventListener("click", function () {
      clearHighlight();
      step.classList.add("active");
      var node = document.getElementById(step.dataset.node);
      if (node) node.classList.add("hl");
      if (detail) {
        detail.innerHTML =
          "<b>" + step.dataset.title + "</b> — " + step.dataset.body;
      }
    });
  });

  // Default highlight: the Request node.
  var first = document.getElementById("node-request");
  if (first) first.classList.add("hl");
})();
