---
name: murphy
description: Runs a focused Murphy Lite website test for one goal and one behavioral persona, then reviews the report and screenshot evidence. Use when the user asks an agent to run Murphy, test a website as a persona, evaluate a JET ordering goal, or analyze a Murphy persona run.
---

# Murphy skill

Run one safe, focused Murphy scenario. Do not commit or push files.

## Defaults

Use these values only when the user does not supply alternatives:

- JET UK URL: `https://www.just-eat.co.uk`
- JET UK delivery postcode: `EC1A 1BB`
- Ordering goal: Add one suitable item to the basket and make sure that the basket contains the selected item.
- Mode: Lite
- Parallel sessions: `1`
- Maximum steps: `15`
- Browser: Visible

For a no-supply exercise, use `HS9 5XD`. Treat this as a test hypothesis until the site shows that no restaurants deliver.

Stop before checkout unless the user explicitly requests a checkout workflow.
For an explicit checkout address-entry workflow, click the checkout button and acknowledge informational notices using only clearly labeled non-transactional continuation controls.
Treat a checkout page showing `Delivery address`, `Full address required`, or an address edit/selection control as the address-entry boundary.
Stop immediately when any of those indicators is visible. Do not search for another continuation control.
Do not enter, select, change, or submit an address. Do not interact with payment or order controls.
If checkout is disabled, unclickable, or blocked before address entry, capture the visible state, report the blocker, and stop. Never place an order.
Always use `--lite` unless the user explicitly requests full mode.

## Inputs

Resolve these inputs from the request:

1. Target URL.
2. Persona name.
3. Goal.
4. Postcode or location context.
5. Authentication requirement.

If the request says JET UK, use the JET UK defaults. Ask one focused question only when a missing input changes the test materially.

## Persona resolution

Read `../murphy_workshop/output/personas.json` when it exists. Use the current persona names because generated names can change between discovery runs.

Known workshop persona themes include:

- A habitual user who follows the shortest familiar route.
- A cautious user who examines dietary and allergy information.
- A diet-focused user who relies on filters.
- An impatient user who abandons after friction or empty results.

Match the requested persona to its current slug. Do not infer demographic, medical, or protected characteristics from behavior events.

If the persona file does not exist, run:

```bash
uv run python workshop/generate_synthetic_posthog.py
uv run python workshop/discover_personas_from_csv.py --output-dir ../murphy_workshop/output
uv run python workshop/build_workshop_personas.py
```

Tell the user that persona discovery uses synthetic data when this path is used.

## Create one scenario

Prefer an existing single-scenario plan in `workshop/plans/` when its persona and goal match the request.

Otherwise, create a temporary YAML plan under `../murphy_workshop/output/skill-plans/`. Include:

- `url`
- One scenario only
- A concrete description
- `priority: critical`
- A valid feature category
- The resolved `test_persona` slug
- Ordered steps
- A measurable success criterion

Include the postcode in the steps. Require visible basket validation for add-to-basket goals.

For allergy goals, evaluate whether the UI clearly communicates its limitations and gives an understandable, safe next action.
A generic disclaimer can pass when it is clear and actionable. Do not require item-specific allergen data or infer medical safety.

For an explicit checkout address-entry goal, allow the agent to click checkout and acknowledge informational notices with non-transactional continuation controls.
The success criterion must require a visible delivery-address entry or selection page without entering address or payment information.
Use `--max-steps 25` for this workflow so basket cleanup and informational notices do not force skipped validation.

## Run Murphy

Create a unique output directory under `../murphy_workshop/output/skill-runs/`.

For a public site, run:

```bash
BROWSER_USE_HEADLESS=false uv run murphy \
  --url "<target-url>" \
  --plan "<plan-path>" \
  --personas ../murphy_workshop/output/personas.json \
  --lite \
  --no-auth \
  --parallel 1 \
  --max-steps 15 \
  --output-dir "<output-directory>"
```

If the site requires authentication, replace `--no-auth` with `--auth` and prefix the command:

```bash
MURPHY_AUTO_AUTH=true BROWSER_USE_HEADLESS=false uv run murphy ...
```

Run this command as an agent-managed background process. Do not open a separate terminal window.
Tell the user to complete login in the visible browser. Murphy detects the signed-in state and continues without terminal input.
Monitor the background process until it finishes, then review its report.
Set `MURPHY_AUTH_TIMEOUT_SECONDS` only when the default five-minute login window is insufficient.

Do not start more than one Murphy scenario at a time. Do not retry a bot-protection block repeatedly.

## Review the result

After the command finishes:

1. Read `evaluation_report.md`.
2. Read the relevant result in `evaluation_report.json`.
3. Open each screenshot linked to a claimed visual flaw.
4. Compare the observed outcome with the scenario success criterion.
5. Do not use the Lite grade as the sole pass-or-fail decision.

Classify each reported problem:

- **Product finding:** The action trace and evidence support the claim.
- **Test limitation:** Bot protection, missing fixtures, or agent navigation caused the result.
- **Unsupported claim:** The available evidence does not show the claim.

If Cloudflare, a CAPTCHA, login, or missing permissions blocks the application, report a test limitation. Do not describe the blocked run as a product evaluation.

## Response

Return:

- Persona
- Goal and postcode
- Outcome against the success criterion
- Evidence-backed findings
- Unsupported claims
- Test limitations
- Report path

Keep the summary concise. State clearly when human or policy review is necessary.
