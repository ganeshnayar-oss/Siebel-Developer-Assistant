# Siebel Open UI Plugin

`Siebel Open UI` is a local Codex plugin for prompt-first Siebel Tools and Open UI automation.

It lets a user configure only the Siebel Web Tools connection details, then ask for repository changes in plain English, for example:

- `create an opportunity list applet that includes name, revenue, and sales stage`
- `create a contact form applet called Prospect with first name, last name, email address, phone number, and customer type`
- `add My Opportunity to a new Opportunities custom view`

The plugin uses live Siebel Web Tools REST metadata to infer repository details where possible instead of forcing the user to know class names, templates, child object paths, or other Siebel internals.

## What This Plugin Includes

- Codex plugin manifest: `.codex-plugin/plugin.json`
- MCP server definition: `.mcp.json`
- Codex skill: `skills/siebel-open-ui/SKILL.md`
- Local Siebel knowledge graph: `knowledge/siebel_knowledge_graph.json`
- MCP entrypoint: `scripts/siebel_open_ui_mcp.py`
- Siebel Web Tools adapter: `scripts/example_siebel_adapter.py`
- Local config: `scripts/siebel_open_ui.config.json` (create from the example; ignored by git)
- Example config: `scripts/siebel_open_ui.config.example.json`

## What It Can Do

- Show setup guidance and validate whether config is complete
- Test the live Siebel Web Tools connection
- Parse prompt requests into a structured applet plan
- Parse prompt requests into a structured business component plan
- Parse prompt requests into a structured workflow plan
- Create shell business components from business-facing prompts
- Create list applets
- Create form applets
- Create business services
- Create workflow processes
- Add applets to existing views
- Create a new view from an existing repository pattern and register it under a screen

## Live Flows Already Validated

The plugin has already been used successfully against a live Siebel environment to:

- connect to the configured Web Tools workspace branch
- create the list applet `My Opportunity`
- create the form applet `Prospect`
- create the custom view `My Custom View`
- register `My Custom View` under `Opportunities Screen`
- place `My Opportunity` on that custom view

## How Another Person Uses It

### 1. Put the plugin in a Codex-accessible plugins folder

For a workspace-local setup, place the plugin at:

```text
<workspace>/plugins/siebel-open-ui
```

This project already uses:

```text
./plugins/siebel-open-ui
```

### 2. Register the plugin in a marketplace file

For a workspace-local plugin, create or update:

```text
<workspace>/.agents/plugins/marketplace.json
```

Example:

```json
{
  "name": "local-workspace",
  "interface": {
    "displayName": "Local Workspace Plugins"
  },
  "plugins": [
    {
      "name": "siebel-open-ui",
      "source": {
        "source": "local",
        "path": "./plugins/siebel-open-ui"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Developer Tools"
    }
  ]
}
```

This repository includes a workspace-local marketplace file at `.agents/plugins/marketplace.json`.

### 3. Make sure the MCP server is available

The plugin includes `.mcp.json`:

```json
{
  "mcpServers": {
    "siebel-open-ui": {
      "command": "python3",
      "args": [
        "./scripts/siebel_open_ui_mcp.py"
      ],
      "cwd": "."
    }
  }
}
```

In this environment, the MCP server is also registered globally in Codex config, but another user can rely on the plugin-local `.mcp.json` if their Codex install reads plugin MCP definitions automatically after reload.

### 4. Configure only the connection details

Edit:

```text
scripts/siebel_open_ui.config.json
```

Required connection values:

- `oracle_guid`
- `webtools_url`
- `workspace_branch`
- `username`
- `password`
- `verify_tls`

Example:

```json
{
  "connection": {
    "oracle_guid": "myuser",
    "webtools_url": "https://host:port/siebel/v1.0/workspace/dev_branch",
    "workspace_branch": "dev_branch",
    "username": "SADMIN",
    "password": "secret",
    "verify_tls": false
  },
  "defaults": {
    "default_project": "Opportunity",
    "default_mode": "Base",
    "auto_place_on_view": false
  }
}
```

Notes:

- Set `verify_tls` to `false` if the environment uses an internal or self-signed certificate chain.
- If the config file should live somewhere else, set `SIEBEL_PLUGIN_CONFIG` to its absolute path before starting the plugin.

### 5. Restart Codex or reopen the workspace

Codex needs to reload the workspace so it discovers:

- the plugin marketplace entry
- the plugin manifest
- the MCP server definition

### 6. Load or enable the plugin in Codex

Look for the plugin:

- display name: `Siebel Open UI`
- plugin id: `siebel-open-ui`

### 7. Start prompting

The intended user experience is prompt-first. The user should not need to manually call REST endpoints or know Siebel repository internals.

Example prompts:

```text
create an opportunity list applet that includes name, revenue, and sales stage
```

```text
create a contact form applet called Prospect with first name, last name, email address, phone number, and customer type
```

```text
add My Opportunity to a new Opportunities custom view
```

```text
create a contact capture business component for contacts
```

```text
create a business component called Billing Account Snapshot for accounts
```

```text
create a business service called Prospect Sync Service using class CSSService
```

```text
create a workflow named SR Assignment Workflow for the Service Request business object
```

## MCP Tools Exposed

- `describe_setup`
- `test_connection`
- `plan_applet_request`
- `plan_business_component_request`
- `plan_business_service_request`
- `plan_workflow_request`
- `create_applet_from_prompt`
- `create_business_component_from_prompt`
- `create_business_service_from_prompt`
- `create_workflow_from_prompt`
- `create_workspace`
- `create_applet`
- `create_business_component`
- `create_business_service`
- `create_workflow`
- `add_applet_to_view`
- `create_view_on_screen`

## Recommended Usage Pattern

For a new user:

1. Run `describe_setup`
2. Run `test_connection`
3. Use a natural-language prompt or a planning tool such as `plan_applet_request`, `plan_business_component_request`, `plan_business_service_request`, or `plan_workflow_request`
4. Execute creation through the plugin

## Knowledge Graph

The plugin now keeps a local memory file at:

```text
knowledge/siebel_knowledge_graph.json
```

Use it as a reusable memory layer for:

- known view-to-applet relationships
- protected shared applets
- validated business-service targets
- environment-specific REST constraints
- safe mutation playbooks

This reduces repeated probing of Siebel for facts we have already validated in this environment. Live Siebel metadata is still the source of truth. If live metadata disagrees with the knowledge graph, trust live Siebel and then update the knowledge graph so the correction is preserved for future runs.

## Important Behavior

- The adapter uses the configured workspace branch and validates it is reachable.
- The current `create_workspace` behavior validates an existing workspace branch rather than provisioning a brand-new one through Siebel.
- The plugin tries to discover repository defaults from live metadata before creating objects.
- The user wanted that discovery-first behavior specifically so class names and view internals do not need to be supplied manually.
- Business component prompts are intended to be business-user centric. Ask for the business entity such as contacts, accounts, opportunities, or orders. The plugin infers the technical class automatically.
- Business component creation currently creates the shell `Business Component` row itself. Repository fields, joins, links, and applets remain follow-on steps.
- If the prompt does not make the base entity or table clear, the plugin should ask about the business entity or source table, not about the Siebel class.
- Business service creation currently creates the service shell itself; child methods and arguments are not automated yet.

## Field Mapping Notes

Natural-language labels are sometimes broader than the actual Siebel field names. For example:

- `phone number` may map to `Cellular Phone #`, `Work Phone #`, or another repository field depending on the target object
- `customer type` may map to `Type`

When there is a clean live repository match, the plugin uses that. If there is a real ambiguity or a risky target choice, a human confirmation step is still appropriate.

## Current Limitations

- Workspace provisioning is not implemented as a true create-new-workspace operation through Siebel REST
- Some repository objects still require environment-specific tuning
- View creation is based on cloning a known working repository pattern, which is safer than inventing a layout from scratch but still depends on existing source metadata
- Form applet layout creation currently focuses on control creation, not full pixel-perfect Open UI presentation design
- Business service method creation is not included in the current implementation

## Files to Hand Off

If another developer or admin needs this plugin, these are the key files:

- `.codex-plugin/plugin.json`
- `.mcp.json`
- `skills/siebel-open-ui/SKILL.md`
- `knowledge/siebel_knowledge_graph.json`
- `scripts/siebel_open_ui_mcp.py`
- `scripts/example_siebel_adapter.py`
- `scripts/siebel_open_ui.config.example.json`

## Summary

This plugin is ready for another Codex user to install, configure with connection details, load into Codex, and use by prompt to create Siebel applets and related Open UI repository objects.
