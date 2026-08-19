# Security Policy

## Scope

DiskWiper can issue destructive storage commands. A protection or authorization
failure that could select the wrong disk is a security issue, not merely a bug.

## Reporting

Please do not report suspected vulnerabilities in a public issue. Use GitHub's
private security advisory feature for this repository. Include reproduction steps,
the affected version or commit, and a minimal synthetic example. Do not attach
real disk serial numbers, device paths, logs, inventory captures, or other
identifying data.

If private advisories are unavailable, contact the repository owner privately
through the GitHub profile before disclosing the issue publicly.

## Supported versions

Only the latest published release receives security fixes while this project is
in alpha. Physical-disk behavior is not guaranteed safe for any purpose; users
must review the code and independently verify every selected device.