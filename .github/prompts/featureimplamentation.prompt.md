# Feature Implementation Prompt

this prompt is designed to guide developers through the process of implementing a new feature in a web application, ensuring that they follow best practices for planning, coding, testing, and deploying their changes. The instructions are structured to help maintain code quality and consistency across the project while also considering the specific requirements of the target operating systems and desktop environments.

For server information and supported operating systems, see /docs/servers.md for server information and the OS support priority matrix for supported operating systems. Also, review the preferred backend stack and application types sections for the technologies being used in the project.

---

## Feature Implementation Instructions

1. **Pull latest changes** before starting:
   ```bash
   git pull
   ```

2. **Understand the feature request fully** — read any linked issues, specs, or descriptions. Ask clarifying questions if the scope is ambiguous.

3. **Plan before coding:**
   - Identify which files, routes, controllers, models, views, or services are affected.
   - Determine if database migrations or schema changes are needed.
   - Decide on the backend stack components required (DB engine, web server config, etc.).
   - Consider the OS support matrix — ensure the implementation is compatible with the highest-priority targets.
   - If the feature touches API endpoints, define the request/response contract before writing code.
   - Evaluate any new libraries or packages before adding them as dependencies.
   - Determine if a feature flag is appropriate for staged or risky rollouts.

4. **Implement the feature:**
   - Write clean, readable code using the preferred languages listed above.
   - Follow existing project conventions (naming, file structure, patterns).
   - Keep changes minimal and focused — do not refactor unrelated code.
   - If the app has a desktop GUI component, test against the DE priority matrix (KDE first).
   - Apply appropriate input validation, authentication/authorisation checks, and guard against injection vulnerabilities.
   - Handle error cases gracefully — new code paths should not fail silently.
   - Store any new config or secrets in environment variables — never hardcode them.

5. **Test locally** before deploying:
   - Verify the feature works as intended on the developer environment (Debian 13 / Firefox).
   - Write new tests covering the feature's behaviour where applicable.
   - Run existing test suites and linters to check for regressions.
   - Confirm that existing functionality is not broken by the change.

6. **Deploy to server(s)** via SSH:
   - Run any pending database migrations on the server before or after file transfer as appropriate.
   - Transfer updated files using `scp` or `rsync`.
   - Restart any affected services on the server.
   - Verify the deployment by checking the live app and reviewing logs.

7. **Commit with a clear message** describing what was implemented and why.
