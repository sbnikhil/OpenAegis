# OpenAegis

Production-grade, security-hardened AI agent platform addressing critical vulnerabilities in autonomous agent systems.

## Problem Statement

Security researchers identified 512 vulnerabilities in OpenClaw, including 8 critical RCE flaws, 341 malicious skills (12% of marketplace), and 135,000 publicly exposed instances. OpenAegis implements defense-in-depth architecture to prevent these attack vectors.

## Architecture
```
User (CLI) → Agent Core (LangGraph) → Security Layer (Sentinel) → Sandboxed Execution
     ↓              ↓                        ↓                           ↓
  Session      Claude API              NeMo Guardrails              Docker/E2B
     ↓              ↓                        ↓                           ↓
  Memory       LanceDB (RAG)           Redline Rules              Network Monitor
```

## Quick Start
```bash
# Setup
python3 -m venv venv
source venv/bin/activate
make install

# Start local services
make dev-up

# Deploy infrastructure
make tf-init
make tf-apply

# Run agent
python -m src.core.cli chat
```

## Planned Tech Stack

- **Cloud:** AWS (S3, Secrets Manager, Lambda, CloudWatch)
- **IaC:** Terraform
- **AI:** Claude 3.5 Sonnet, LangGraph, LanceDB
- **Security:** NeMo Guardrails, Docker sandboxing, AST analysis
- **Observability:** Prometheus, Grafana, AWS X-Ray

## Testing
```bash
make test          # Full test suite
make test-unit     # Unit tests only
make lint          # Code quality checks
```

## License
MIT