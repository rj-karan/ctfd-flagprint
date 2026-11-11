# Security

Flagprint runs inside CTFd's admin trust boundary. What it protects:

- the per-team secret and every team's flag, which only admins can read;
- the files it issues, which only the owning team (or an admin) can download;
- the sandbox that runs `generate.py`: no network, all capabilities dropped, memory, pid and time limits.

What it does **not** protect against: an admin uploading a hostile `generate.py`. Script delivery needs the Docker
socket, and anyone who can create challenges can run code in a container on the host. Give admin rights accordingly.

## Reporting a vulnerability

Use GitHub's private reporting: **Security → Report a vulnerability** on the repository, or
[this link](https://github.com/rj-karan/ctfd-flagprint/security/advisories/new). Please don't open a public issue
for anything that could let a player read another team's flag or file.

You'll get a reply within a few days. Fixed issues are credited in the changelog unless you'd rather stay anonymous.

Supported: the latest release on CTFd 3.8.x.
