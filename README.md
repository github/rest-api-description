# GitHub's REST API OpenAPI Description

This repository contains [OpenAPI](https://www.openapis.org/) descriptions for [GitHub's REST API](https://docs.github.com/rest).

## What is OpenAPI?

From the [OpenAPI Specification](https://github.com/OAI/OpenAPI-Specification):

> The OpenAPI Specification (OAS) defines a standard, programming language-agnostic interface description for HTTP APIs, which allows both humans and computers to discover and understand the capabilities of a service without requiring access to source code, additional documentation, or inspection of network traffic. When properly defined via OpenAPI, a consumer can understand and interact with the remote service with a minimal amount of implementation logic. Similar to what interface descriptions have done for lower-level programming, the OpenAPI Specification removes guesswork in calling a service.

## Project Status

This project is currently in **BETA**. We expect this description to be accurate but it is in **active development**. If you've identified a mismatch between GitHub API's behavior and these descriptions, [please open an issue.](https://github.com/github/rest-api-description/issues/new?template=schema-inaccuracy.md)

## Description Formats

Each OpenAPI document is available in two formats: **bundled** and **dereferenced**.

  - The bundled descriptions are single file artifacts that make usages of OpenAPI **components** for reuse and portability. This is the preferred way of interacting with GitHub's OpenAPI description.
  - Certain tools have poor support for references to components within the artifact. We highly encourage to look into tooling that supports referenced components, but since that's not always possible, we also provide a fully dereferenced version of the description as well, without any references.

## Vendor Extensions

We use various vendor extensions for concepts that are harder to express with OpenAPI components and/or are specific to GitHub. For more information on the extensions used in these description, check out [extensions.md](extensions.md)

## Limitations

  - Not all headers are described in the OpenAPI documents, expect those to be added over time.
  - Certain GitHub API resources use multi segment path parameters, which aren't supported by the OpenAPI specification. For the time being, we have annotated such parameters with a `x-multi-segment` extension. In general, URL encoding those parameters is a good idea.
  - A lot of operations described in these documents are accessible through multiple paths. For the time being we have described the most common way to access these operations, but are working on a way to describe alias paths and/or describe all possible paths.
  - This repository only contains the bundled and dereferenced versions of our REST API descriptions. We're looking into offering a fully **referenced** directory structure for easier browsing.

## Contributing

Because this description is used across GitHub's whole API development experience, we don't currently accept pull requests that directly modify the description. This repository is automatically kept up to date with the description used to validate GitHub API requests as well as powering contract tests. See [CONTRIBUTING.md](CONTRIBUTING.md) for more details.

## License

github/rest-api-description is licensed under the [MIT license](LICENSE.md)


## Contact

You may contact [opensource+rest-api-description@github.com](mailto:opensource+rest-api-description@github.com) with any questions related to this repository.
