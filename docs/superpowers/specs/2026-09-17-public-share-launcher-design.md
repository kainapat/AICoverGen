# AICoverGen Public Share Launcher Design

## Goal

Provide an explicit one-click way to expose the local AICoverGen WebUI through a temporary Gradio HTTPS URL without changing the safety or behavior of the normal local launcher.

## Decisions

- `run_aicovergen.bat` remains local/LAN-only.
- `run_aicovergen_share.bat` is the deliberate opt-in entry point for internet sharing.
- Share links are temporary, unauthenticated, and intended only for trusted recipients.
- The launcher reports the generated public URL in the existing Carbon console.
- Local and LAN access remain available if public tunnel creation fails.

## Components

### Public Share Launcher

`run_aicovergen_share.bat` configures the same UTF-8 and cache environment as the normal launcher, then invokes `launch.py --share`.

### Launcher Argument Forwarding

`launch.py` accepts `--share`. In share mode it appends `--share` to the `src/webui.py` child-process arguments; otherwise, the child command remains unchanged.

### Tunnel Status Capture

The existing stdout stream captures Gradio output. It recognizes:

- `Running on public URL: https://<id>.gradio.live` as tunnel success.
- `Could not create share link.` as tunnel failure.

The success URL is displayed in Carbon Cyan. A tunnel failure is displayed as unavailable while preserving the usable local and LAN URLs.

## Runtime Flow

1. User launches `run_aicovergen_share.bat`.
2. `launch.py --share` performs its existing port cleanup and virtual-environment checks.
3. `launch.py` starts `src/webui.py --listen --listen-port 7860 --share` with stdout captured.
4. Local socket readiness and public tunnel setup proceed concurrently.
5. After the local socket is ready, the launcher waits up to 35 seconds for a tunnel success or explicit failure.
6. The ready card displays Local, Network, and Public URL status.
7. Closing the launcher terminates the WebUI process tree and its Gradio tunnel.

## Error Handling

- A transient Gradio tunnel failure does not terminate the local WebUI.
- A reported tunnel failure stops the public-link wait immediately and displays an actionable unavailable state.
- A tunnel operation that emits neither success nor failure times out after 35 seconds; the card reports the timeout and retains the local URL.
- Existing WebUI startup timeout and orphan-process cleanup remain unchanged.

## Security Boundary

The Gradio share URL has no application authentication. Anyone possessing it can operate the WebUI and consume local GPU resources. The URL must only be shared with trusted recipients. Public mode is never enabled by the normal launcher.

## Verification

- Compile `launch.py` with the project Python interpreter.
- Start `run_aicovergen_share.bat` through the process supervisor.
- Require both port 7860 readiness and capture of a `*.gradio.live` URL.
- Request the generated public URL and require HTTP 200.
- Confirm the Carbon ready card displays the same URL.
