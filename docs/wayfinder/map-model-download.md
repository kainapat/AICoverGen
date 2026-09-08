# Wayfinder Map — Reliable Voice-Model Downloading

## Destination

User can get a voice model into `rvc_models/` reliably: gated HuggingFace repos either
download with the user's own token or fail with a message that tells exactly what to do
instead of a raw `HTTP Error 401`.

## Notes

- Domain: AICoverGen WebUI (`src/webui.py:download_online_model`), `urllib` vs `huggingface_hub`
- Skills every session should consult: grilling, domain-modeling
- Facts already established:
  - `sail-rvc/Aldeano_Minecraft__RVC_V2_-_500_Epochs_` returns 401 anonymously → gated/private repo
  - Current downloader uses `urllib.request.urlretrieve` with no credentials → 401 on any gated repo
  - `huggingface_hub 0.36.2` is already installed (via gradio) → token auth possible without new deps
  - Multi-URL path (`webui.py:100-108`) and single-URL path (`webui.py:110`) handle query strings inconsistently

## Decisions so far

*(empty — map just charted)*

## Open decision tickets

### T1 — Gated-repo strategy (grilling, HITL)
How should gated HF repos be handled?
(a) HF token field in WebUI + download via `huggingface_hub`
(b) Manual download + Upload-model-tab guidance only
(c) Both: try anonymous, on 401 show guidance + token option

### T2 — Friendly download errors (grilling, HITL)
Map HTTP errors to guidance (401 → needs login/token, 403 → forbidden, 404 → removed/renamed)?
Or keep raw exception text?

### T3 — HF token provisioning (task, HITL — only if T1 picks token)
Human checklist: create read-token at huggingface.co/settings/tokens, decide where it lives
(env var vs WebUI session field).

## Not yet specified

- Exact UX of a token field (which tab, session-only or persisted)
- Whether pixeldrain multi-URL path needs the same treatment
- Whether to unify single-URL and multi-URL query-string stripping

## Out of scope

- Rewriting the whole downloader (progress bars, resume, mirrors)
- Training or hosting voice models ourselves
