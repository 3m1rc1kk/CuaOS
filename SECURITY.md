# 🔒 Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest (main branch) | ✅ Yes |
| older commits | ⚠️ Best effort |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, **please do not open a public issue.** Instead:

1. **Email:** Send a detailed report to the project maintainer via private message or email (ishakemir454@gmail.com).

2. **Include:**
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)
3. **Response time:** We aim to acknowledge reports within **48 hours** and provide a fix or mitigation within **7 days** for critical issues.

## Security Architecture

### Sandbox Isolation

The CUA agent operates inside a **Docker container** (`trycua/cua-xfce`), which provides a layer of isolation between the AI agent and the host system:

```
┌─────────────────────────────────────┐
│  Host Machine                       │
│  ┌───────────────────────────────┐  │
│  │  Docker Container (Sandbox)   │  │
│  │  ┌─────────────────────────┐  │  │
│  │  │  XFCE Desktop (VNC)     │  │  │
│  │  │  Agent actions run HERE │  │  │
│  │  └─────────────────────────┘  │  │
│  └───────────────────────────────┘  │
│  PyQt6 UI + LLM (host-side)        │
└─────────────────────────────────────┘
```

- The agent **cannot** access host files, network services, or processes directly.
- All interactions go through the container's REST API on a **localhost-only** port.
- The container has **no privileged access** to the host.

### Built-in Safety Guards

| Guard | Description |
|-------|-------------|
| **Coordinate Validation** | All click coordinates are validated to be within `[0.0, 1.0]` range before execution |
| **Repeat Detection** | Agent automatically stops if the same action is repeated consecutively (prevents infinite loops) |
| **Step Limit** | Maximum number of steps per command is enforced (`MAX_STEPS`, default: 20) |
| **Input Sanitization** | User commands are sanitized before being passed to the LLM |
| **Plan Verification** | Each plan step is verified against success criteria using the vision model before advancing |
| **GPU Conflict Prevention** | Auto GPU detection prevents loading two models on the same GPU (avoids CUDA double-free crashes) |
| **Model File Validation** | Local model file paths are validated for existence and `.gguf` extension before loading |

## Known Security Considerations

### ⚠️ LLM Prompt Injection

The agent uses a vision-language model to interpret screenshots and decide actions. Like all LLM-based systems, it is potentially susceptible to **prompt injection** attacks:

- **Risk:** Malicious text displayed on the VM screen could influence the agent's behavior.
- **Mitigation:** The agent operates in an isolated sandbox, limiting the blast radius. The repeat guard and step limit provide additional boundaries.
- **Recommendation:** Do not point the agent at untrusted websites or content without supervision.

### ⚠️ Docker Container Security

- The sandbox container runs a full Linux desktop. While isolated, Docker is **not a security boundary** equivalent to a VM.
- **Recommendation:** Keep Docker and the container image updated. Do not run the container with `--privileged` or `--net=host` flags.

### ⚠️ Network Exposure

- The container API listens on `localhost:8001` by default. It is **not** exposed to the network.
- The VNC server inside the container is also bound to localhost.
- **Recommendation:** Do not change port bindings to `0.0.0.0` in production environments.

### ⚠️ Model Files

- The GGUF model is downloaded from HuggingFace on first run. Always verify you are downloading from the intended repository.
- Local model file paths specified via the GUI file browser are validated for existence and `.gguf` extension.
- **Recommendation:** Check the model repository URL in `src/config.py` before first run. Only load models from trusted sources.

### ⚠️ Local Model File Browser

- The GUI file browser (`📂 Browse` button) allows selecting local `.gguf` files. The selected path is stored in `PLANNER_GGUF_LOCAL_PATH`.
- **Risk:** A user could select a malicious or corrupted model file.
- **Mitigation:** Only `.gguf` files are accepted; the file dialog filters by extension.
- **Recommendation:** Only load models from trusted sources. Verify model integrity with checksums when possible.

### ⚠️ Auto GPU Layer Detection

- The auto GPU detection feature runs `nvidia-smi` via subprocess to query available VRAM.
- **Risk:** Minimal; `nvidia-smi` is a standard NVIDIA tool with read-only access.
- **Mitigation:** Subprocess call uses a 5-second timeout and captures output only (`capture_output=True`).

## Best Practices

1. **Run in a dedicated environment** — Use a separate user account or VM for running the agent.
2. **Keep the sandbox updated** — Regularly pull the latest container image: `docker pull trycua/cua-xfce:latest`.
3. **Monitor agent actions** — Use the Mission Control UI to watch the agent in real-time; stop it if behavior seems unexpected.
4. **Limit step count** — Keep `MAX_STEPS` reasonable (default: 20) to prevent runaway executions.
5. **Review logs** — Check the structured logs after each run; export them via the JSON export feature for auditing.
6. **Do not store credentials** — Never ask the agent to handle passwords, API keys, or other secrets inside the sandbox.
7. **Network isolation** — If possible, restrict the container's outbound network access using Docker network policies.

## Dependencies & Supply Chain

Key dependencies and their security considerations:

| Package | Purpose | Trust Level |
|---------|---------|-------------|
| `PyQt6` | GUI framework | High (Qt Company) |
| `llama-cpp-python` | LLM inference (executor & planner) | Medium (community fork with CUDA) |
| `transformers` | Translation model | High (Hugging Face) |
| `huggingface_hub` | Model downloading | High (Hugging Face) |
| `Pillow` | Image processing | High (PSF) |
| `requests` | HTTP client | High (PSF) |
| `docker` (runtime) | Container runtime | High (Docker Inc.) |

## Disclosure Policy

- We follow **coordinated disclosure** — please allow us reasonable time to fix issues before public disclosure.
- Contributors who report valid vulnerabilities will be credited in the release notes (unless they prefer anonymity).
- We do not currently have a bug bounty program.
