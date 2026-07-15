# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in StratTraderPro, please report it
**privately** so it can be addressed before public disclosure.

- Use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  (**Security → Report a vulnerability** on this repository), or
- Open a regular issue **only** for low-severity, non-exploitable problems.

Please include enough detail to reproduce the issue: affected component,
version/commit, and a minimal proof of concept where possible.

## Scope and expectations

StratTraderPro is **self-hosted, best-effort, open-source software** maintained
in spare time. There is:

- **No bounty program.** Reports are handled on a volunteer basis.
- **No SLA.** We aim to acknowledge reports within a reasonable time and fix
  confirmed issues in a future release, but make no guarantee of turnaround.

You are the operator of your own instance. Securing your deployment — secrets,
network exposure, broker API keys, and the machine it runs on — is your
responsibility. See the `## Self-hosting` and `## Disclaimer` sections of the
README.

## Supported versions

Only the latest `main` is supported. There are no backported security fixes to
older tags.
