const { spawn, exec } = require("child_process");
const http = require("http");

const nextCli = require.resolve("next/dist/bin/next");

const server = spawn(process.execPath, [nextCli, "dev"], {
  stdio: "inherit",
  cwd: __dirname,
});

let browserOpened = false;

const checkServer = setInterval(() => {
  http
    .get("http://localhost:3000", (response) => {
      if (!browserOpened && response.statusCode >= 200) {
        browserOpened = true;
        clearInterval(checkServer);
        if (process.env.NOVATECH_SKIP_BROWSER !== "1") {
          exec('start "" "http://localhost:3000"');
        }
      }
    })
    .on("error", () => {});
}, 1000);

server.on("error", (error) => {
  console.error("Could not start Next.js:", error.message);
  clearInterval(checkServer);
});

server.on("exit", (code) => {
  clearInterval(checkServer);
  process.exit(code ?? 0);
});
