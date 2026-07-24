// Stamp a unique build id before each build. next.config reads `.build-id`
// (bakes it into the client as NEXT_PUBLIC_BUILD_ID) and `public/build-id.txt`
// is served statically so a running client can poll it and detect a new
// deploy → auto-reload. Both come from the SAME value so they always match.
import { writeFileSync } from "node:fs";

const id = String(Date.now());
writeFileSync(new URL("../.build-id", import.meta.url), id, "utf8");
writeFileSync(new URL("../public/build-id.txt", import.meta.url), id, "utf8");
console.log("build id:", id);
