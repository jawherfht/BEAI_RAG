import type { NextConfig } from "next";

const config: NextConfig = {
  // The Docker image builds a self-contained server (NEXT_OUTPUT=standalone); `next start` in
  // dev/E2E uses the regular output.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  reactStrictMode: true,
  // No next/image optimisation: keeps the optional LGPL libvips (sharp) out of the build.
  images: { unoptimized: true },
  poweredByHeader: false,
};

export default config;
