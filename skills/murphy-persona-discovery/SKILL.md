---
name: murphy-persona-discovery
description: Extracts behavioral personas for Murphy from a PostHog-style CSV using the workshop discovery pipeline. Use when the user asks to generate personas, discover personas, extract personas from analytics or PostHog data, cluster user behavior, or summarize personas from the default workshop mock dataset.
---

# Murphy persona discovery

Discover personas from a PostHog-style CSV. Do not commit or push files.

## Goal

Run the existing workshop persona-discovery pipeline, using the workshop mock CSV and discovery script by default, then summarize the personas that were produced.

## Defaults

Use these values unless the user supplies alternatives:

- Murphy repo: current workspace
- Input CSV: `workshop/synthetic_posthog_events.csv`
- Discovery script: `workshop/discover_personas_from_csv.py`
- Output directory: `workshop/output`
- Provider: `openai`
- Model: `gpt-5-mini`

Use the current script defaults for:

- `--discovery-sessions`
- `--scoring-sessions`
- `--clusters`
- `--concurrency`
- `--seed`

## Inputs

Resolve these from the request when present:

1. Input CSV path
2. Discovery script path
3. Output directory
4. Provider and model
5. Whether to use mock data or a user-provided export

If the user mentions `@Murphy/workshop/discover_personas_from_csv.py`, resolve it to the repository path `workshop/discover_personas_from_csv.py`.

Ask one focused question only when the repo path or input CSV is unclear.

## Preconditions

Before running discovery:

1. Confirm the workspace is the Murphy repo.
2. Confirm the discovery script exists.
3. Confirm the input CSV exists.
4. Confirm at least one supported LLM provider key is configured in `.env` or the environment.

Supported provider keys include:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GOOGLE_API_KEY`
- `AZURE_OPENAI_KEY`
- `MISTRAL_API_KEY`
- `GROQ_API_KEY`
- `CEREBRAS_API_KEY`
- `OPENROUTER_API_KEY`

If the default mock CSV does not exist, run:

```bash
uv run python workshop/generate_synthetic_posthog.py
```

Tell the user when synthetic data had to be generated.

If no provider key is configured, stop and explain that persona discovery needs one LLM provider key, but not a separate embeddings-provider key.

## Run

Use:

```bash
uv run python workshop/discover_personas_from_csv.py
```

If the user supplied a different input, script, output directory, provider, or model, pass the corresponding flags.

Use the script defaults unless the user explicitly asks to change them.

## Review

After the command finishes:

1. Read the generated persona output in `workshop/output/personas.json` unless the user supplied a different output directory.
2. Summarize each persona with:
   - name
   - short description
   - size
   - 2-3 distinguishing traits
3. Report the number of personas created and the silhouette score when available.
4. If the input was the default mock CSV, say clearly that the personas come from synthetic workshop data.

## Response

Return:

- Input CSV used
- Discovery script used
- Whether the data was synthetic or user-provided
- Output path
- Number of personas created
- Persona summary list
- Silhouette score when available
- First blocker, if discovery could not run

Keep the response concise.
