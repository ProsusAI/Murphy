# Process Models & Petri Nets in Murphy

This note outlines how **process models** (Petri nets, BPMN, or similar) could be integrated into Murphy to make tests more **structured**, with traceability and conformance guarantees. It draws on the referenced work (conformance checking, ProMoAI, agentic design with reactive Petri nets, neuro-symbolic reasoning).

---

## 1. Why process models help
im thinking - is there a way to have petri-nets or process models integrated
Today Murphy uses:

- **Test plan**: free-form scenarios with `steps_description` and `success_criteria`.
- **Execution**: agent produces an **action trace** (navigate, click, type, scroll, done, …).
- **Judging**: LLM compares trace + screenshots to success criteria.

Process models add:

- **Explicit allowed flows**: which action sim thinking - is there a way to have petri-nets or process models integrated iequences are valid (e.g. “submit only after fill_form”).
- **Conformance metrics**: recall (how much of the trace the model allows) and precision (how much of the model was exercised).
- **Coverage**: which paths through the flow were tested (e.g. happy path vs. error branch).
- **Reuse**: one model can drive many scenarios (e.g. one net per user flow, many tests per net).

This aligns with the neuro-symbolic idea (Belle & Marcus): keep **symbolic** structure (process model) for guarantees and **neural** execution (LLM agent) for perception and action.

---

## 2. Integration options

### Option A: Process model as test specification (conformance only)

**Idea:** A process model describes the *intended* flow (e.g. BPMN or Petri net). Murphy runs scenarios as today; after execution, the **trace** is replayed on the model and conformance is measured.

**Mechanics:**

- **Model**: Activities = high-level steps (e.g. `navigate_home`, `click_create`, `fill_form`, `submit`, `see_confirmation`). Optional: gateways for branches (e.g. success / error).
- **Trace**: Map raw actions (navigate, click, input_text, …) to model activities (via rules or a small mapping layer). Result = **event log**: one trace per scenario run.
- **Conformance** (as in Molka et al.):
  - **Replay**: Can the trace be replayed on the net from start to end? → recall (fitness).
  - **Footprint**: Directly-follows from trace vs. from model → local recall/precision.
- **Output**: Add to report: “Trace conforms: yes/no”, “Fitness: 0.92”, “Deviations: …”.

**Pros:** Small change (post-processing + optional model field). No change to generation or execution.  
**Cons:** Model must be provided or learned; mapping from low-level actions to activities needs design.

---

### Option B: Process model drives test design (generation)

**Idea:** Use the process model to **generate or constrain** scenarios (like ProMoAI: text → model, then model → structured output).

**Mechanics:**

- **From model to scenarios:**
  - Each path (start → end) in the net → one scenario, or
  - Each transition → one step in a scenario; scenarios = selected paths (e.g. main path + a few alternates).
- **From analysis to model:**
  - LLM or tool (e.g. ProMoAI-style) turns `identified_user_flows` + features into a process model (BPMN or Petri net).
  - Then derive scenarios from that model instead of (or in addition to) free-form generation.

**Pros:** Tests become structurally tied to the intended flow; coverage of the model is explicit.  
**Cons:** Requires model discovery or authoring; may need to handle large/loopy nets (path explosion).

---

### Option C: Process model as orchestrator (execution control)

**Idea:** Like Marino et al.: the process net is the **orchestrator**. Transitions = tasks (e.g. “fill payment form”, “submit order”). Murphy’s agent is invoked per transition; the net advances only when the task is done (token game).

**Mechanics:**

- **Reactive Petri net**: places = states; (external) transitions = test steps/tasks.
- **Scheduler**: Enabled transitions → choose one → invoke agent with task description → on success, fire transition and advance marking.
- **Trace**: Sequence of fired transitions (+ optional low-level actions per transition).

**Pros:** Execution is guaranteed to follow the model; clear state and progress.  
**Cons:** Bigger change to execution loop; need a clear notion of “task done” (e.g. agent says done or a checker validates).

---

### Option D: Lightweight “trace vs. flow” (minimal first step)

**Idea:** No full process model yet. Add **structured flow** as an optional part of a scenario: an ordered list of high-level steps (e.g. `["navigate_to_home", "open_create_ui", "fill_form", "submit", "see_confirmation"]`). After execution, compare the **observed trace** (after mapping) to this list: order, missing steps, extra steps.

**Mechanics:**

- **Scenario**: Optional `expected_flow: list[str]` (or a reference to a small DSL/YAML flow).
- **Execution**: Unchanged; we still get an action list.
- **Post-run**: Map actions → abstract steps (e.g. “click Create” → `open_create_ui`); compute edit distance or “longest common subsequence” vs. `expected_flow`; report “flow compliance” and deviations.

**Pros:** Very small change; no Petri/BPMN dependency; experiments with “structure” quickly.  
**Cons:** No branches, no formal conformance (recall/precision) like in process mining.

---

## 3. Recommended direction

- **Short term:** **Option D** — add optional `expected_flow` (or similar) to scenarios and a **flow compliance** check in the report. This gives immediate structure without new formats or libraries.
- **Next:** **Option A** — allow an optional **process model** (e.g. BPMN or Petri net) per flow or per plan. After execution, map traces to activities, run **replay** and/or **footprint** conformance (reuse ideas from Molka et al.), and report fitness and deviations. This stays “post-hoc” and doesn’t force changes to generation or execution.
- **Later:** **Option B** for generation (derive scenarios from a discovered or authored model) and **Option C** only if you want execution to be fully driven by the net (e.g. for strict compliance or multi-agent orchestration).

---

## 4. Concrete implementation hints (Option A)

- **Activity alphabet**: Define a fixed set of abstract activities (e.g. `navigate`, `click`, `type`, `submit`, `see_toast`, …) or allow per-plan mapping from action types + context (e.g. “click + Create button” → `open_create_ui`).
- **Trace → event log**: One row per action (or per “step” after grouping): `scenario_id`, `order`, `activity_name`, optional `payload` (e.g. URL, element).
- **Model format**: Start with something simple (e.g. a small Petri net or BPMN subset) or a list of allowed **directly-follows** pairs; avoid state-space explosion by keeping models small (one net per user flow).
- **Conformance**: Implement replay (token game on the net) and/or directly-follows comparison; output recall (and precision if you derive allowed behaviour from the model).
- **Dependencies**: Consider a lightweight library (e.g. `pm4py` for replay and footprint, or a minimal custom replay for a simple net format) so you don’t tie Murphy to a heavy stack.

---

## 5. References (from your PDFs)

- **Belle & Marcus (Neuro-Symbolic):** Symbolic structure for reasoning and guarantees; temporal/dynamic aspects; reward machines for RL.
- **Molka et al. (Conformance for BPMN):** Directly-follows footprint, log replay on model, recall/precision, no need for full state-space exploration.
- **ProMoAI:** LLM → process model (POWL/BPMN/PNML); process model as first-class artefact.
- **Marino et al. (Agentic design):** Reactive Petri nets; transitions = tasks; scheduler assigns agents; process model as orchestration layer.

If you want to pursue one option in code next, Option D (expected_flow + flow compliance) or Option A (process model + conformance in report) are the most direct next steps.
