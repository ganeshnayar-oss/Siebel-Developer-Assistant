---
name: siebel-open-ui
description: Use this skill when the user wants to automate Siebel workspace creation, business component creation, applet creation, business service creation, workflow creation, or Open UI view updates through prompt-based requests in the local Siebel plugin.
---

# Siebel Open UI

Use this skill when the user wants to work on Siebel configuration from Codex using natural-language requests.

## Local memory

Before probing live Siebel for known patterns or previously learned environment quirks, consult:

- `knowledge/siebel_knowledge_graph.json`

Treat it as a local memory layer for:

- known view-to-applet relationships
- protected shared applets
- validated business-service targets
- environment-specific REST limitations
- safe mutation playbooks

If live metadata disagrees with the knowledge graph, trust live Siebel and update the knowledge graph after the work is complete.

## Available MCP tools

- `describe_setup`: inspect config path, connection readiness, and setup guidance
- `test_connection`: validate the configured connection details
- `validate_workspace_target`: confirm the selected workspace branch and optional view/applet resolve correctly before making changes
- `plan_applet_request`: convert a prompt into a structured applet plan
- `plan_business_component_request`: convert a prompt into a structured business component plan
- `plan_business_service_request`: convert a prompt into a structured business service plan
- `plan_workflow_request`: convert a prompt into a structured workflow plan
- `create_applet_from_prompt`: execute a prompt-driven applet request
- `create_business_component_from_prompt`: execute a prompt-driven business component request
- `create_business_service_from_prompt`: execute a prompt-driven business service request
- `create_workflow_from_prompt`: execute a prompt-driven workflow request
- `create_workspace`: create a workspace explicitly
- `create_applet`: create an applet explicitly
- `create_business_component`: create a business component explicitly
- `create_business_service`: create a business service explicitly
- `create_workflow`: create a workflow explicitly
- `add_applet_to_view`: place an applet on a target view
- `create_view_on_screen`: create a new view on a screen explicitly

## Working rules

1. Call `describe_setup` first if the plugin might not be configured yet.
2. Call `test_connection` before making changes against a real environment.
3. Prefer `plan_applet_request` before `create_applet_from_prompt` whenever the prompt names user-facing fields instead of exact Siebel BC field names.
4. The applet planning flow now resolves requested labels against real Business Component fields and returns `field_analysis`, `inferred_field_choices`, and `unresolved_fields`.
5. Respect the config flag `workflow.human_in_the_loop.confirm_bc_field_choices`.
6. If that flag is `true` and the plugin had to infer a BC field choice, stop and ask the human to confirm the resolved fields before creating the applet.
7. If `create_applet_from_prompt` returns `Siebel applet confirmation required`, review `plan.field_analysis` with the human and rerun only after approval with `confirmed_field_choices=true`.
8. If `unresolved_fields` is not empty, do not create the applet. Ask the human which exact BC fields should be used.
9. Prefer `plan_business_component_request` or `create_business_component_from_prompt` when the user describes a business component in plain English.
10. Keep business component prompts business-user centric. Ask about the business entity or source table only when needed. Do not ask the user for a Siebel class name unless they explicitly want to control it.
11. The business component planner should infer the class from live repository patterns when possible and otherwise fall back automatically.
12. Business component creation currently creates the shell Business Component row only. If the user also wants fields, joins, links, or applets, treat those as follow-on steps.
13. Prefer `plan_business_service_request` or `create_business_service_from_prompt` when the user describes a business service in plain English.
14. Prefer `plan_workflow_request` or `create_workflow_from_prompt` when the user describes a workflow in plain English.
15. Keep inferred workspace, applet, business component, business service, workflow, field, and view names explicit in your responses, but do not force technical Siebel terms into the user's prompt if they are not needed.
16. Use an explicit workspace name whenever the human gives one. If no workspace is supplied, call out that the run is using the config-default branch.
17. Run `validate_workspace_target` before modifying an existing view, applet, business service wiring, or workflow dependency in a live workspace.
18. If a view references multiple applet variants, do not assume the correct target from naming alone. Report the referenced applets and target the one the view actually resolves in the chosen branch.
19. The configured workspace branch must already exist in Siebel Web Tools; if the adapter reports branch or repository-object errors, surface the raw message and stop rather than guessing.
20. Treat `Order Entry - Order Form Applet Dashboard (Sales)` on the Sales line-item views as a protected shared applet. Avoid broad applet-header rewrites on that object.
21. When adding buttons or invocation wiring to a shared applet, prefer minimal child-row changes first and compare the mutated applet header against `MAIN` before and after the change.
22. If a no-script button path cannot satisfy the required user feedback or method invocation behavior, use the smallest possible fallback and revalidate the shared applet in a fresh Inspect session immediately after the change.
23. Record durable Siebel discoveries, object relationships, and environment-specific REST constraints in `knowledge/siebel_knowledge_graph.json` so future runs do not need to rediscover them from scratch.
24. For `ecommunications` navigation work, do not report success from repository readback alone. Verify the live application in Inspect or browser runtime after changing `Screen Menu Item`, `Page Tab`, or related navigation rows.
25. When adding a new top-level screen under `Siebel Universal Agent`, do not default the `Screen Menu Item` sequence to the global max value. Start from a visible sequence near `Web Call Center Home Screen` and confirm the item is actually rendered in the runtime menu.
26. If a new screen resolves by direct `GotoView` URL but still does not appear in the live menu, treat that as an unresolved runtime-navigation failure, not a successful registration.
27. Treat `Screen Menu Item Locale`, `Page Tab Locale`, and `Screen View Locale` as unstable in this environment: `describe` may succeed while `GET` returns `404` and `PUT` may return `500`. Do not promise menu visibility fixes through those child rows unless runtime validation proves it.
28. For newly created `ecommunications` views, validate runtime access separately from runtime navigation. A view can have valid repository rows and still fail at runtime because it is not granted through the active responsibility.
29. If runtime returns `SBL-DAT-00329` with text like `The responsibility of user 'SADMIN' does not allow accessing view 'C360'`, classify the issue as a responsibility or access-layer gap, not a screen-menu or page-tab problem.
30. When a new view hits `SBL-DAT-00329`, do not keep retrying `Screen Menu Item`, `Page Tab`, or locale changes as the primary fix. Move to responsibility or access verification and record the blocking object path if the environment does not expose it cleanly.
31. If the environment blocks `Responsibility`, `Responsibility View`, or `View Responsibility` metadata paths, state that clearly and preserve the runtime error evidence in `knowledge/siebel_knowledge_graph.json` so future runs do not rediscover the same dead end.
