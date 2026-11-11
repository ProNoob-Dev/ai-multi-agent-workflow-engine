/* Live workflow simulation (docs site).
 *
 * A request enters as a moving particle. The router lights up, routes it to
 * one domain agent, the agent calls MCP tools, a money move holds at the
 * human gate (HITL), and a failure runs the saga's compensations in reverse.
 * Play advances on a timer, Step advances one step, Reset clears the run.
 * Under prefers-reduced-motion every step lands at once: the state is the
 * same, nothing travels.
 */
(function () {
  "use strict";

  var panel = document.getElementById("sim-panel");
  var flow = document.getElementById("sim-flow");
  var dot = document.getElementById("sim-particle");
  var narration = document.getElementById("sim-narration");
  var traceList = document.getElementById("sim-trace-list");
  var playBtn = document.getElementById("sim-play");
  var stepBtn = document.getElementById("sim-step");
  var resetBtn = document.getElementById("sim-reset");
  var approveBtn = document.getElementById("sim-approve");
  var rejectBtn = document.getElementById("sim-reject");
  var requestText = document.getElementById("sim-request-text");
  var routerNote = document.getElementById("sim-router-note");
  var hitlNote = document.getElementById("sim-hitl-note");
  var resultTitle = document.getElementById("sim-result-title");
  var resultNote = document.getElementById("sim-result-note");
  var toolsBox = document.getElementById("sim-tools");

  if (!panel || !dot) return;

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var STEP_MS = reduced ? 0 : 950;

  /* Scenario scripts. Each step: station to light, optional chip to light,
     narration line, trace row, and what happens next. */
  var SCENARIOS = {
    validate: {
      request: "\u201CValidate invoice INV-1001\u201D",
      tools: ["lookup_invoice", "validate_invoice"],
      steps: [
        { station: "sim-node-request", note: "\u201CValidate invoice INV-1001\u201D enters the engine.", trace: ["request", "received"] },
        { station: "sim-node-router", note: "The router reads the sentence and picks an intent: invoice.", trace: ["router", "classify intent \u2192 invoice"] },
        { station: "sim-node-agents", chip: '[data-agent="InvoiceAgent"]', note: "InvoiceAgent takes the job. The other three stay dark.", trace: ["agent", "InvoiceAgent takes over"] },
        { station: "sim-node-mcp", chip: '[data-tool="lookup_invoice"]', note: "InvoiceAgent calls lookup_invoice through the MCP server.", trace: ["tool", "lookup_invoice \u00B7 INV-1001 found"] },
        { station: "sim-node-mcp", chip: '[data-tool="validate_invoice"]', note: "validate_invoice checks the purchase order, duplicates and due date.", trace: ["tool", "validate_invoice \u00B7 PO matches, no duplicate"] },
        { station: "sim-node-result", note: "INV-1001 is valid: PO matches, no duplicate, not overdue.", trace: ["result", "valid \u00B7 with citations"], kind: "ok", end: "valid" }
      ]
    },
    approve: {
      request: "\u201CApprove payment for invoice INV-1003\u201D",
      tools: ["lookup_invoice", "validate_invoice", "reserve_payment", "post_ledger_entry", "notify_vendor"],
      steps: [
        { station: "sim-node-request", note: "\u201CApprove payment for invoice INV-1003\u201D enters the engine.", trace: ["request", "received"] },
        { station: "sim-node-router", note: "The router reads the sentence and picks an intent: invoice.", trace: ["router", "classify intent \u2192 invoice"] },
        { station: "sim-node-agents", chip: '[data-agent="InvoiceAgent"]', note: "InvoiceAgent takes the job. The other three stay dark.", trace: ["agent", "InvoiceAgent takes over"] },
        { station: "sim-node-mcp", chip: '[data-tool="lookup_invoice"]', note: "InvoiceAgent calls lookup_invoice through the MCP server.", trace: ["tool", "lookup_invoice \u00B7 INV-1003 found"] },
        { station: "sim-node-mcp", chip: '[data-tool="validate_invoice"]', note: "validate_invoice checks the purchase order, duplicates and due date.", trace: ["tool", "validate_invoice \u00B7 valid, \u20B91,850 due"] },
        { station: "sim-node-hitl", gate: true, note: "This is a payment, so the flow stops here. The gate waits for a human.", trace: ["gate", "interrupt() \u00B7 awaiting approval"] },
        { station: "sim-node-saga", chip: '[data-saga="reserve"]', note: "Approved. The saga reserves the funds.", trace: ["saga", "reserve funds"] },
        { station: "sim-node-saga", chip: '[data-saga="ledger"]', note: "Ledger entry posted.", trace: ["saga", "post ledger entry"] },
        { station: "sim-node-saga", chip: '[data-saga="notify"]', note: "Vendor notified. Three steps, all applied.", trace: ["saga", "notify vendor"] },
        { station: "sim-node-result", note: "Payment for INV-1003 is posted, with the ledger entry and the notification on the trace.", trace: ["result", "payment posted"], kind: "ok", end: "posted" }
      ]
    },
    "approve-fail": {
      request: "\u201CApprove payment for invoice INV-1003\u201D",
      tools: ["lookup_invoice", "validate_invoice", "reserve_payment", "post_ledger_entry", "notify_vendor"],
      steps: [
        { station: "sim-node-request", note: "\u201CApprove payment for invoice INV-1003\u201D enters the engine.", trace: ["request", "received"] },
        { station: "sim-node-router", note: "The router reads the sentence and picks an intent: invoice.", trace: ["router", "classify intent \u2192 invoice"] },
        { station: "sim-node-agents", chip: '[data-agent="InvoiceAgent"]', note: "InvoiceAgent takes the job. The other three stay dark.", trace: ["agent", "InvoiceAgent takes over"] },
        { station: "sim-node-mcp", chip: '[data-tool="lookup_invoice"]', note: "InvoiceAgent calls lookup_invoice through the MCP server.", trace: ["tool", "lookup_invoice \u00B7 INV-1003 found"] },
        { station: "sim-node-mcp", chip: '[data-tool="validate_invoice"]', note: "validate_invoice checks the purchase order, duplicates and due date.", trace: ["tool", "validate_invoice \u00B7 valid, \u20B91,850 due"] },
        { station: "sim-node-hitl", gate: true, note: "This is a payment, so the flow stops here. The gate waits for a human.", trace: ["gate", "interrupt() \u00B7 awaiting approval"] },
        { station: "sim-node-saga", chip: '[data-saga="reserve"]', note: "Approved. The saga reserves the funds.", trace: ["saga", "reserve funds"] },
        { station: "sim-node-saga", chip: '[data-saga="ledger"]', note: "Ledger entry posted.", trace: ["saga", "post ledger entry"] },
        { station: "sim-node-saga", chip: '[data-saga="notify"]', fail: true, note: "The notify step fails. The saga stops and undoes what it did.", trace: ["saga", "notify vendor \u00B7 FAILED"], kind: "fail" },
        { station: "sim-node-saga", chip: '[data-saga="ledger"]', comp: "2 \u00B7 Ledger entry reversed", note: "Compensation 1 of 2: the ledger entry is reversed.", trace: ["saga", "reverse ledger entry"], kind: "comp" },
        { station: "sim-node-saga", chip: '[data-saga="reserve"]', comp: "1 \u00B7 Reservation released", note: "Compensation 2 of 2: the reservation is released.", trace: ["saga", "release reservation"], kind: "comp" },
        { station: "sim-node-result", note: "Payment not applied. Every step undone, nothing left half-applied.", trace: ["result", "not applied \u00B7 cleanly undone"], kind: "ok", end: "undone" }
      ]
    }
  };

  var scenario = "validate";
  var index = 0;
  var playing = false;
  var waitingGate = false;
  var timer = null;
  var startedAt = 0;

  function $(id) { return document.getElementById(id); }

  function moveDotTo(el, onRail) {
    if (!el) return;
    var pr = panel.getBoundingClientRect();
    var r = el.getBoundingClientRect();
    var x = onRail ? r.left - pr.left + 17 : r.left - pr.left + r.width / 2;
    var y = r.top - pr.top + r.height / 2;
    dot.style.transform = "translate(" + x.toFixed(1) + "px," + y.toFixed(1) + "px)";
    dot.classList.add("go");
  }

  function clearMarks() {
    Array.prototype.forEach.call(document.querySelectorAll(".sim-station"), function (s) {
      s.classList.remove("on", "done", "holding");
    });
    Array.prototype.forEach.call(document.querySelectorAll(".sim-chip"), function (c) {
      c.classList.remove("on", "done", "failed", "comp");
    });
  }

  function buildTools() {
    toolsBox.innerHTML = "";
    SCENARIOS[scenario].tools.forEach(function (name) {
      var chip = document.createElement("span");
      chip.className = "sim-chip";
      chip.setAttribute("data-tool", name);
      chip.textContent = name;
      toolsBox.appendChild(chip);
    });
  }

  function resetRun() {
    stopTimer();
    index = 0;
    playing = false;
    waitingGate = false;
    startedAt = 0;
    clearMarks();
    buildTools();
    dot.classList.remove("go");
    dot.style.transform = "";
    traceList.innerHTML = '<li class="t-empty">No run yet. Press Play the run.</li>';
    narration.textContent = "Press Play the run to send the request through the engine.";
    requestText.textContent = SCENARIOS[scenario].request;
    routerNote.textContent = "Reads the request and picks an intent.";
    hitlNote.textContent = "Money moves stop here. Nothing is paid without a human.";
    resultTitle.textContent = "Result";
    resultNote.textContent = "Answer, citations, trace, cost.";
    approveBtn.disabled = true;
    rejectBtn.disabled = true;
    playBtn.disabled = false;
    stepBtn.disabled = false;
    playBtn.textContent = "\u25B6 Play the run";
    /* Saga chips back to their step names. */
    var names = { reserve: "1 \u00B7 Reserve funds", ledger: "2 \u00B7 Post ledger entry", notify: "3 \u00B7 Notify vendor" };
    Array.prototype.forEach.call(document.querySelectorAll("[data-saga]"), function (c) {
      c.textContent = names[c.getAttribute("data-saga")];
    });
  }

  function elapsed() {
    return startedAt ? Math.round(performance.now() - startedAt) : 0;
  }

  function appendTrace(step, kind) {
    var empty = traceList.querySelector(".t-empty");
    if (empty) empty.remove();
    var li = document.createElement("li");
    if (kind) li.className = kind;
    var label = document.createElement("b");
    label.textContent = step.trace[0];
    li.appendChild(label);
    li.appendChild(document.createTextNode(" " + step.trace[1] + " "));
    var ms = document.createElement("span");
    ms.className = "t-ms";
    ms.textContent = elapsed() + " ms";
    li.appendChild(ms);
    traceList.appendChild(li);
  }

  function runStep(step) {
    var station = $(step.station);
    if (station) {
      station.classList.remove("on");
      station.classList.add("on");
    }
    var chipEl = null;
    if (step.chip) {
      chipEl = document.querySelector(step.chip);
      if (chipEl) {
        if (step.comp) chipEl.textContent = step.comp;
        chipEl.classList.add(step.fail ? "failed" : step.comp ? "comp" : "on");
      }
    }
    moveDotTo(chipEl || station, !chipEl);
    narration.textContent = step.note;
    appendTrace(step, step.kind);
    if (step.station === "sim-node-router") {
      routerNote.innerHTML = "Intent: <b>invoice</b>.";
    }
    if (step.end) {
      resultTitle.textContent = step.end === "valid" ? "Result: valid" :
        step.end === "posted" ? "Result: paid" :
        step.end === "undone" ? "Result: undone" : "Result";
      resultNote.textContent = step.note;
    }
    if (step.gate) {
      waitingGate = true;
      if (station) station.classList.add("holding");
      hitlNote.textContent = "Holding. The payment waits for your decision.";
      approveBtn.disabled = false;
      rejectBtn.disabled = false;
      playBtn.disabled = true;
      stepBtn.disabled = true;
    }
  }

  function finishStepVisuals() {
    Array.prototype.forEach.call(document.querySelectorAll(".sim-station.on"), function (s) {
      s.classList.remove("on");
      s.classList.add("done");
    });
    Array.prototype.forEach.call(document.querySelectorAll(".sim-chip.on"), function (c) {
      c.classList.remove("on");
      c.classList.add("done");
    });
  }

  function advance() {
    var steps = SCENARIOS[scenario].steps;
    if (index >= steps.length) { stopPlaying(); return; }
    if (!startedAt) startedAt = performance.now();
    finishStepVisuals();
    var step = steps[index];
    index += 1;
    runStep(step);
    if (step.gate) { stopTimer(); return; }
    if (index >= steps.length) { stopPlaying(); return; }
    if (playing) schedule();
  }

  function schedule() {
    stopTimer();
    timer = setTimeout(advance, STEP_MS);
  }

  function stopTimer() {
    if (timer) { clearTimeout(timer); timer = null; }
  }

  function stopPlaying() {
    stopTimer();
    playing = false;
    playBtn.textContent = "\u25B6 Play the run";
    playBtn.disabled = false;
    stepBtn.disabled = false;
  }

  function play() {
    if (waitingGate) return;
    if (index >= SCENARIOS[scenario].steps.length) resetRun();
    playing = true;
    playBtn.textContent = "\u275A\u275A Pause the run";
    stepBtn.disabled = true;
    advance();
  }

  function pause() {
    stopTimer();
    playing = false;
    playBtn.textContent = "\u25B6 Play the run";
    stepBtn.disabled = false;
  }

  function decide(approved) {
    if (!waitingGate) return;
    waitingGate = false;
    approveBtn.disabled = true;
    rejectBtn.disabled = true;
    var gate = $("sim-node-hitl");
    if (gate) gate.classList.remove("holding");
    if (approved) {
      hitlNote.textContent = "Approved by a human. The saga runs.";
      appendTrace({ trace: ["gate", "approved by human"] }, "ok");
      playBtn.disabled = false;
      stepBtn.disabled = false;
      if (playing) schedule();
      else advance();
    } else {
      hitlNote.textContent = "Rejected. No side effects.";
      resultTitle.textContent = "Result: rejected";
      resultNote.textContent = "Rejected. No reservation, no ledger entry, no notification.";
      appendTrace({ trace: ["gate", "rejected by human"] }, "ok");
      var station = $("sim-node-result");
      if (station) station.classList.add("done");
      moveDotTo(station, true);
      narration.textContent = "Rejected. No side effects: no reservation, no ledger entry, no notification.";
      /* Mark the run finished so Play starts a fresh run instead of
         continuing into the saga. */
      index = SCENARIOS[scenario].steps.length;
      stopPlaying();
    }
  }

  playBtn.addEventListener("click", function () {
    if (playing) pause();
    else play();
  });
  stepBtn.addEventListener("click", function () {
    if (playing || waitingGate) return;
    advance();
  });
  resetBtn.addEventListener("click", resetRun);
  approveBtn.addEventListener("click", function () { decide(true); });
  rejectBtn.addEventListener("click", function () { decide(false); });

  Array.prototype.forEach.call(
    document.querySelectorAll(".sim-scenario"),
    function (btn) {
      btn.addEventListener("click", function () {
        Array.prototype.forEach.call(
          document.querySelectorAll(".sim-scenario"),
          function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        scenario = btn.getAttribute("data-scenario");
        resetRun();
      });
    });

  /* Keep the particle on its station after a resize. */
  var rt = 0;
  window.addEventListener("resize", function () {
    clearTimeout(rt);
    rt = setTimeout(function () {
      var steps = SCENARIOS[scenario].steps;
      if (index > 0 && index <= steps.length) {
        var step = steps[index - 1];
        var target = step.chip ? document.querySelector(step.chip) : $(step.station);
        moveDotTo(target, !step.chip);
      }
    }, 150);
  });

  buildTools();
})();
