# Code Review and Task List Update Prompt

Please do a "git pull" to get the latest code changes before doing a full review of the entire app and create/update the tasklist.md with any new tasks/features that were found that need to be completed and mark any completed tasklist items as done. If there are any bugs found during the review, add them to the bug list section of the tasklist.md file. Make sure to check the servers.md file for any updates on server information and the OS support priority matrix for any changes in supported operating systems. Also, review the preferred backend stack and application types sections for any updates on the technologies being used in the project.

TASK-LIST.md format:

# Task List For <APP-NAME>

> **Audited:** <DATETIME> \ <NUMBER-OF-COMMITS> commits since last audit
> **Method:** Full codebase review of all controllers, models, services, views, routes, agent code, and database schema.  
> **Codebase:** <ROUNDED-LINES-COUNT> lines | <NUMBER-OF-CONTROLLERS> controllers | <NUMBER-OF-MODELS> models | <NUMBER-OF-SERVICES> services | <NUMBER-OF-VIEWS> views | <NUMBER-OF-MIGRATIONS> migrations | <NUMBER-OF-GO-AGENT-FILES> Go agent files  
> **Target Launch:** April 1, 2026 (flexible — QUALITY is the priority, not speed)

---

# Overall Progress Percentage: <%>

## Summary ##

|    Area    |    Completed    |    Remaining    |    Completion    |
|------------|-----------------|-----------------|------------------|
| <Section name> | <Completed-Items-Count> | <Items-Remaining> | <Completion%> |

---
# Task List Items #
## <Section name> ##
### <SubSection name> ### [add subsections as required]
[ ] - <Uncomplete task>
[X] - <Completed task>

---

# Bug List # 

|    Area    |    Completed    |    Remaining    |    Completion    |
|------------|-----------------|-----------------|------------------|
| <Section name> | <Completed-Bug-Count> | <Bugs-Remaining> | <Completion%> |

---
## <Section name> ##
### <SubSection name> ### [add subsections as required]
[ ] - <Unfixed bug>
[X] - <Fixed bug>
