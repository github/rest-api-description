# OpenAPI Extensions

This document describes the [OpenAPI extensions](https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.3.md#specification-extensions) used in GitHub's REST API OpenAPI descriptions.

## `x-displayName`

### Purpose

To define a display name, typically for documentation interfaces, for the corresponding tag.

### Usage

This applies to the [Tag Object](https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.3.md#tagObject).

The value should be a string.

#### Example usage

```yml
tags:
  name: actions
  description: Endpoints to manage GitHub Actions using the REST API.
  x-displayName: GitHub Actions
```

## `x-github`

### Purpose

Provides extra information used to generate Octokit SDKs.

### Usage

The `x-github` specification extension is applied to the [Operation Object](https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.3.md#operationObject).

| Field Name  |	Type	   | Description  |
| :---------- | :------: | :----------- |
| triggersNotification | boolean   | Operations that trigger notification are more likely to trigger abuse limits. We increase the default throttling from 1s between requests to 3s between requests for these operations. |
| deprecationDate        | string   | The date when we publicly announce that the operation will eventually be removed. After this date, the `deprecated` property should also be set to `true`. Format: `YYYY-MM-DD` |
| removalDate        | string   | The date when we stop displaying documentation for the operation on docs.github.com and stop including it in new Octokit major versions. Format: `YYYY-MM-DD` |
| githubCloudOnly | boolean | Used in a [separate plugin](https://github.com/octokit/plugin-enterprise-cloud.js/) for GitHub Enterprise Cloud users. |
| enabledForGitHubApps       | boolean   | True if this operation is enabled for apps |
| previews      | array   | Previews will be deprecated soon. An array of API previews, with name, description, and whether the preview is required for this particular operation. |

#### Example usage

```yml
x-github:
  enabledForGitHubApps: true
  githubCloudOnly: false
  previews: []
```

## `x-multi-segment`

Path parameter extension marking a certain parameter as supporting multiple URL segments. It's recommended to use an URL encoded value when possible.

### Usage

The `x-multi-segment` extension applies only on [path parameters](https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.3.md#parameter-object). The value should be a boolean. Defaults to false.

#### Example

```yml
- name: ref
  in: path
  required: true
  schema:
    type: string
  x-multi-segment: true
```
