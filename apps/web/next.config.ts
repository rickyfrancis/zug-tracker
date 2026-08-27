import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits .next/standalone with a self-contained server.js, which keeps the
  // production image small (see apps/web/Dockerfile).
  output: "standalone",
};

export default nextConfig;
