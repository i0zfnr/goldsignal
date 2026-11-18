import("./ryaze-server.mjs").catch(error => {
  console.error(error);
  process.exitCode = 1;
});
