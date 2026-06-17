# Security Policy

## Supported Agent Deployment

The supported deployment model is:

Windows Service Agent

The Agent must be installed and configured by an Administrator on the Windows workstation.

## Do Not Commit

Do not commit:

- site_config.json
- database backups
- private files
- logs with tokens or sessions
- SSL private keys
- real server IP addresses
- internal hostnames
- workstation secrets
- generated audit files with private paths

## Allowed Placeholder Examples

The documentation may use placeholders such as:

- https://farabi.example.com
- http://FARABI-SERVER-IP
- SITE_NAME
- REPOSITORY_URL

## Local Agent Endpoint

The Agent uses a local workstation endpoint:

http://127.0.0.1:8787

This endpoint should not be exposed publicly.

## Installer Integrity

Current installer SHA256:

6792b3644e457ab031c234e3405e9d7d8ad7e22c2ba230a946f14de568c71f1d
