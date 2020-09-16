const { createAppAuth } = require("@octokit/auth-app");
const { Octokit } = require("@octokit/core");
const { paginateRest } = require("@octokit/plugin-paginate-rest");

const APP_ID = process.env.APP_ID;
const PRIVATE_KEY = process.env.PRIVATE_KEY;
const DISPATCH_EVENT_NAME = process.env.DISPATCH_EVENT_NAME;
const EVENT_PAYLOAD = JSON.parse(process.env.EVENT_PAYLOAD_JSON);

const OctokitWithPagination = Octokit.plugin(paginateRest);

main();

async function main() {
  try {
    const octokit = new OctokitWithPagination({
      auth: {
        id: APP_ID,
        privateKey: PRIVATE_KEY,
      },
      authStrategy: createAppAuth,
    });

    const installations = await octokit.paginate("GET /app/installations", {
      mediaType: { previews: ["machine-man"] },
      per_page: 100,
    });

    for (const {
      id,
      account: { login },
    } of installations) {
      console.log("Installation found: %s (%d)", login, id);

      const installationOctokit = new OctokitWithPagination({
        auth: {
          id: APP_ID,
          privateKey: PRIVATE_KEY,
          installationId: id,
        },
        authStrategy: createAppAuth,
      });

      const repositories = await installationOctokit.paginate(
        "GET /installation/repositories",
        {
          mediaType: { previews: ["machine-man"] },
          per_page: 100,
        }
      );

      console.log(
        "Repositories found on %s: %d. Dispatching events",
        login,
        repositories.length
      );

      for (const { name, full_name: fullRepoName } of repositories) {
        await installationOctokit.request(
          "POST /repos/:owner/:repo/dispatches",
          {
            owner: login,
            repo: name,
            event_type: DISPATCH_EVENT_NAME,
            client_payload: EVENT_PAYLOAD,
          }
        );
        console.log("Event distpatched for %s", fullRepoName);
      }
    }
  } catch (error) {
    console.log(error);
    process.exit(1)
  }
}
