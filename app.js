(() => {
  const shouldForceTop = !window.location.hash || window.location.hash === "#video";

  function forceTopOnLoad() {
    window.scrollTo(0, 0);
  }

  if (shouldForceTop) {
    forceTopOnLoad();
    requestAnimationFrame(forceTopOnLoad);
    window.addEventListener("load", () => {
      requestAnimationFrame(forceTopOnLoad);
      window.setTimeout(forceTopOnLoad, 80);
    });
    window.addEventListener("pageshow", () => {
      requestAnimationFrame(forceTopOnLoad);
    });
  }

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- header scroll state ---------- */

  const header = document.querySelector(".site-header");

  function updateHeader() {
    if (header) {
      header.classList.toggle("is-scrolled", window.scrollY > 8);
    }
  }

  updateHeader();
  window.addEventListener("scroll", updateHeader, { passive: true });

  /* ---------- smooth-scroll buttons ---------- */

  document.querySelectorAll("[data-scroll-target]").forEach((control) => {
    control.addEventListener("click", (event) => {
      const targetId = control.getAttribute("data-scroll-target");
      const target = targetId ? document.getElementById(targetId) : null;
      if (!target) {
        return;
      }
      event.preventDefault();
      target.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" });
    });
  });

  /* ---------- reveal on scroll ---------- */

  const revealTargets = [...document.querySelectorAll(".reveal")];

  if (reducedMotion || !("IntersectionObserver" in window)) {
    revealTargets.forEach((el) => el.classList.add("is-visible"));
  } else {
    const revealObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            revealObserver.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -6% 0px" }
    );
    revealTargets.forEach((el) => revealObserver.observe(el));
  }

  /* ---------- animated stat counters ---------- */

  const counters = [...document.querySelectorAll("[data-count]")];

  function animateCount(el) {
    const target = Number(el.dataset.count) || 0;
    const suffix = el.dataset.suffix || "";
    if (reducedMotion || target === 0) {
      el.textContent = `${target}${suffix}`;
      return;
    }
    const duration = 1200;
    const start = performance.now();
    function tick(now) {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      el.textContent = `${Math.round(target * eased)}${suffix}`;
      if (t < 1) {
        requestAnimationFrame(tick);
      }
    }
    requestAnimationFrame(tick);
  }

  if (counters.length) {
    if (reducedMotion || !("IntersectionObserver" in window)) {
      counters.forEach(animateCount);
    } else {
      const countObserver = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              animateCount(entry.target);
              countObserver.unobserve(entry.target);
            }
          });
        },
        { threshold: 0.5 }
      );
      counters.forEach((el) => countObserver.observe(el));
    }
  }

  /* ---------- hero terminal typing loop ---------- */

  const typeTarget = document.querySelector("[data-type-target]");
  const outLines = [...document.querySelectorAll("[data-out-line]")];
  const terminal = document.querySelector("[data-terminal]");
  const command =
    'premode compile --plugin literal_symbol "Fix the failing test" --profile lite';

  function runTerminal() {
    if (!typeTarget) {
      return;
    }
    if (reducedMotion) {
      typeTarget.textContent = command;
      outLines.forEach((line) => line.classList.add("is-shown"));
      return;
    }

    let i = 0;
    typeTarget.textContent = "";
    outLines.forEach((line) => line.classList.remove("is-shown"));

    function typeChar() {
      if (i <= command.length) {
        typeTarget.textContent = command.slice(0, i);
        i += 1;
        window.setTimeout(typeChar, 18 + Math.random() * 26);
      } else {
        outLines.forEach((line, index) => {
          window.setTimeout(() => line.classList.add("is-shown"), 340 + index * 320);
        });
        // idle, then loop
        window.setTimeout(runTerminal, 340 + outLines.length * 320 + 6500);
      }
    }

    window.setTimeout(typeChar, 500);
  }

  if (terminal && !reducedMotion && "IntersectionObserver" in window) {
    let started = false;
    const termObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && !started) {
            started = true;
            runTerminal();
            termObserver.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.35 }
    );
    termObserver.observe(terminal);
  } else {
    runTerminal();
  }

  /* ---------- workflow scroll scrubbing ---------- */

  const workflow = document.querySelector(".workflow-story");
  const steps = [...document.querySelectorAll("[data-story-step]")];
  const productStates = [...document.querySelectorAll("[data-product-state]")];
  const progressNumber = document.querySelector("[data-progress-number]");
  const panelState = document.querySelector("[data-panel-state]");
  const stateLabels = ["Prompt", "Inspect", "Compile", "Tune"];
  const stackedStory = window.matchMedia("(max-width: 960px)");

  function setActiveStep(step) {
    if (!workflow) {
      return;
    }
    const activeStep = Math.max(1, Math.min(4, step));
    if (workflow.dataset.activeStep === String(activeStep)) {
      return;
    }
    workflow.dataset.activeStep = String(activeStep);
    steps.forEach((item) => {
      item.classList.toggle("is-active", item.dataset.storyStep === String(activeStep));
    });
    productStates.forEach((item) => {
      item.classList.toggle("is-active", item.dataset.productState === String(activeStep));
    });
    if (progressNumber) {
      progressNumber.textContent = String(activeStep).padStart(2, "0");
    }
    if (panelState) {
      panelState.textContent = stateLabels[activeStep - 1];
    }
  }

  let autoTimer = null;

  function startAutoCycle() {
    if (autoTimer) {
      return;
    }
    let current = Number(workflow?.dataset.activeStep) || 1;
    setActiveStep(current);
    autoTimer = window.setInterval(() => {
      current = (current % 4) + 1;
      setActiveStep(current);
    }, 3400);
  }

  function stopAutoCycle() {
    if (autoTimer) {
      window.clearInterval(autoTimer);
      autoTimer = null;
    }
  }

  function updateWorkflowProgress() {
    if (!workflow || reducedMotion || stackedStory.matches) {
      return;
    }
    const rect = workflow.getBoundingClientRect();
    const travel = Math.max(1, rect.height - window.innerHeight);
    const progress = Math.min(1, Math.max(0, -rect.top / travel));
    setActiveStep(Math.min(4, Math.floor(progress * 4) + 1));
  }

  function syncStoryMode() {
    if (!workflow || reducedMotion) {
      return;
    }
    if (stackedStory.matches) {
      // on phones the section isn't tall enough to scrub — auto-play instead
      startAutoCycle();
    } else {
      stopAutoCycle();
      updateWorkflowProgress();
    }
  }

  if (workflow) {
    if (reducedMotion) {
      setActiveStep(4);
    } else {
      syncStoryMode();
      window.addEventListener("scroll", updateWorkflowProgress, { passive: true });
      window.addEventListener("resize", syncStoryMode);
      if (stackedStory.addEventListener) {
        stackedStory.addEventListener("change", syncStoryMode);
      }
      // let users tap a step to jump the preview
      steps.forEach((item) => {
        item.addEventListener("click", () => {
          stopAutoCycle();
          setActiveStep(Number(item.dataset.storyStep));
          if (stackedStory.matches) {
            startAutoCycleDelayed();
          }
        });
      });
    }
  }

  let resumeTimer = null;

  function startAutoCycleDelayed() {
    if (resumeTimer) {
      window.clearTimeout(resumeTimer);
    }
    resumeTimer = window.setTimeout(startAutoCycle, 8000);
  }
})();
